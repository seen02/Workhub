import copy, os, tempfile, unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from . import outline,store,domain,auth
from .main import app

ADMIN={'sub':'a','email':'admin@example.com','admin':True}
WORKER={'sub':'w','email':'worker@example.com','admin':False}

class UnlinkTests(unittest.TestCase):
    def setUp(self):
        from .testing_acl import allow_fixture
        allow_fixture(self)
        link_access=patch.object(outline.permissions,'require_project_linkable');link_access.start();self.addCleanup(link_access.stop)
        acl=patch.object(outline.permissions, "Access");acl.start();self.addCleanup(acl.stop)
        self.folder=tempfile.TemporaryDirectory();self.patches=[]
        self.start(patch.object(store,'DB',os.path.join(self.folder.name,'db')));store.init()
        store.put('collection','c');store.put('projects',[{'id':'c','name':'P'},{'id':'other','name':'Other'}]);store.put('task-parent:c',{'id':'root','ready':True})
        self.docs={'root':{'id':'root','title':'업무 목록','text':'안내','collectionId':'c','url':'/doc/root','parentDocumentId':None},
            'task':{'id':'task','title':'업무','text':domain.render({'project':'P','owner':WORKER['email'],'status':'미착수'}),'collectionId':'c','url':'/doc/task','revision':1,'updatedAt':'now','publishedAt':'now'},
            'ref':{'id':'ref','title':'PRD','text':'자료','collectionId':'c'}}
        self.calls=[];self.fail_delete=False;self.lost_delete=False
        self.start(patch.object(outline,'all_items',return_value=[{'id':'c','name':'P','permission':'read_write'},{'id':'other','name':'Other','permission':'read_write'}]));outline.PROJECTS_CACHE['until']=0
        self.start(patch.object(outline,'api',side_effect=self.api));outline.record(self.docs['task'])
        store.put('chat-context:w:r',{'collectionId':'c','taskId':'task'})
    def start(self,p):self.patches.append(p);return p.start()
    def tearDown(self):
        app.dependency_overrides.clear()
        for p in reversed(self.patches):p.stop()
        outline.PROJECTS_CACHE['until']=0;self.folder.cleanup()
    def api(self,name,body,missing_ok=False):
        self.calls.append((name,copy.deepcopy(body)))
        if name=='documents.info':return copy.deepcopy(self.docs.get(body['id']))
        if name=='documents.delete':
            if self.fail_delete:raise HTTPException(502,'delete failed')
            self.assertEqual(body,{'id':'root','permanent':False});self.docs.pop('root',None)
            if self.lost_delete:self.lost_delete=False;raise TimeoutError('lost response')
            return None
        raise AssertionError('Unexpected API, including forbidden collection deletion: '+name)
    def test_default_preserves_all_outline_documents_and_parent_mapping(self):
        before=copy.deepcopy(self.docs);result=outline.unlink_project(ADMIN,'c','default-1')
        self.assertEqual(self.docs,before);self.assertEqual(self.calls,[]);self.assertFalse(result['collectionDeleted']);self.assertFalse(result['taskListDeleted'])
        self.assertEqual(store.get('task-parent:c')['id'],'root');self.assertIsNone(store.get('chat-context:w:r'))
        self.assertEqual(outline.tasks(),[]);self.assertEqual(outline.history(),[])
        with store.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        with self.assertRaises(HTTPException):outline.project('c')
        with self.assertRaises(HTTPException):outline.tasks('c')
        self.assertEqual(outline.project()['id'],'other')
    def test_worker_cannot_preview_or_unlink(self):
        for call in (lambda:outline.unlink_preview(WORKER,'c'),lambda:outline.unlink_project(WORKER,'c','worker-1',True,'root')):
            with self.assertRaises(HTTPException) as e:call()
            self.assertEqual(e.exception.status_code,403)
        self.assertEqual(self.calls,[])
    def test_optional_delete_targets_only_recorded_root_soft_delete(self):
        result=outline.unlink_project(ADMIN,'c','delete-1',True,'root')
        self.assertTrue(result['taskListDeleted']);self.assertIn('ref',self.docs);self.assertIsNone(store.get('task-parent:c'))
        self.assertEqual([b for n,b in self.calls if n=='documents.delete'],[{'id':'root','permanent':False}])
    def test_foreign_parent_id_or_moved_parent_cannot_be_deleted(self):
        with self.assertRaises(HTTPException):outline.unlink_project(ADMIN,'c','bad-id-1',True,'ref')
        self.docs['root']['collectionId']='other'
        self.assertIsNone(outline.unlink_preview(ADMIN,'c')['parent'])
        with self.assertRaises(HTTPException):outline.unlink_project(ADMIN,'c','moved-1',True,'root')
        self.assertFalse(any(n=='documents.delete' for n,b in self.calls));self.assertEqual(len(outline.projects()),2)
    def test_delete_failure_keeps_project_linked_and_tasks_active(self):
        self.fail_delete=True
        with self.assertRaises(HTTPException):outline.unlink_project(ADMIN,'c','failed-1',True,'root')
        self.assertEqual(len(outline.projects()),2);self.assertEqual(len(outline.tasks('c')),1)
    def test_lost_delete_response_retry_finishes_without_second_delete(self):
        self.lost_delete=True
        with self.assertRaises(TimeoutError):outline.unlink_project(ADMIN,'c','retry-1',True,'root')
        result=outline.unlink_project(ADMIN,'c','retry-1',True,'root')
        self.assertTrue(result['unlinked']);self.assertEqual(sum(n=='documents.delete' for n,b in self.calls),1)
    def test_repeated_old_request_cannot_unlink_reconnected_project(self):
        first=outline.unlink_project(ADMIN,'c','stable-1')
        store.put('projects',[{'id':'c','name':'P'}]);self.assertEqual(outline.unlink_project(ADMIN,'c','stable-1'),first)
        self.assertEqual(outline.project('c')['id'],'c')
        with self.assertRaises(HTTPException):outline.unlink_project(ADMIN,'c','stable-1',True,'root')
    def test_last_project_stays_empty_and_does_not_seed_default(self):
        store.put('projects',[{'id':'c','name':'P'}]);outline.unlink_project(ADMIN,'c','empty-1')
        self.assertEqual(outline.projects(),[]);self.assertEqual(outline.tasks(),[])
        with self.assertRaises(HTTPException):outline.project()
        self.assertEqual(store.get('projects'),[])
    def test_old_pending_report_cannot_write_after_unlink(self):
        p=outline.propose(WORKER,'task',{'status':'진행 중'},'before-unlink')
        outline.unlink_project(ADMIN,'c','pending-1')
        with self.assertRaises(HTTPException):outline.confirm(WORKER,p['id'])
        self.assertFalse(any(n=='documents.update' for n,b in self.calls))
    def test_relink_preserves_root_and_recovers_same_task_id(self):
        outline.unlink_project(ADMIN,'c','relink-1')
        with patch.object(outline,'ensure_member'):
            outline.register_project(ADMIN,'','c','reconnect-1')
        outline.record(self.docs['task']);self.assertEqual(outline.tasks('c')[0]['id'],'task');self.assertEqual(store.get('task-parent:c')['id'],'root')
    def test_api_default_and_forbidden_collection_delete_parameter(self):
        app.dependency_overrides[auth.current]=lambda:ADMIN
        client=TestClient(app)
        with patch.object(outline,'unlink_project',return_value={'unlinked':True}) as unlink:
            self.assertEqual(client.post('/api/projects/c/unlink',json={'idem':'request-1'}).status_code,200)
            unlink.assert_called_once_with(ADMIN,'c','request-1',False,'')
            self.assertEqual(client.post('/api/projects/c/unlink',json={'idem':'request-2','delete_collection':True}).status_code,422)

if __name__=='__main__':unittest.main()
