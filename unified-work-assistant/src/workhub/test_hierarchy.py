import copy, os, tempfile, unittest
from unittest.mock import patch
from fastapi import HTTPException
from . import outline, store, domain

USER={'sub':'u','email':'worker@example.com','admin':False}

class HierarchyTests(unittest.TestCase):
    def setUp(self):
        from .testing_acl import allow_fixture
        allow_fixture(self)
        self.folder=tempfile.TemporaryDirectory();self.stack=[]
        self.start(patch.object(store,'DB',os.path.join(self.folder.name,'test.db')));store.init()
        self.docs={};self.creates=[];self.lose_response=False
        self.start(patch.object(outline,'api',side_effect=self.api))
        self.start(patch.object(outline,'all_items',side_effect=lambda _,body:list(copy.deepcopy(d) for d in self.docs.values() if d['collectionId']==body['collectionId'] and not d.get('deletedAt'))))
        self.start(patch.object(outline,'projects',return_value=[{'id':'c','name':'P','code':'c'},{'id':'other','name':'Q','code':'other'}]))
    def start(self,p):self.stack.append(p);return p.start()
    def tearDown(self):
        for p in reversed(self.stack):p.stop()
        self.folder.cleanup()
    def api(self,name,body,missing_ok=False):
        if name=='documents.info':return copy.deepcopy(self.docs.get(body['id'])) if missing_ok else copy.deepcopy(self.docs[body['id']])
        if name=='documents.create':
            assert body['id'] not in self.docs
            d={**body,'url':'/doc/'+body['id'],'revision':1,'updatedAt':'now','publishedAt':'now'}
            self.docs[d['id']]=d;self.creates.append(body)
            if self.lose_response:self.lose_response=False;raise TimeoutError('lost response')
            return copy.deepcopy(d)
        raise AssertionError(name)
    def root(self,id='existing',**overrides):
        d={'id':id,'title':'업무 목록','text':'프로젝트 안내','collectionId':'c','publishedAt':'now','url':'/doc/'+id,**overrides}
        self.docs[id]=d;return d
    def test_new_tasks_share_one_parent_and_parent_is_not_a_task(self):
        fields={'owner':USER['email'],'status':'미착수'}
        a=outline.create(USER,'A',fields,'a',collection_id='c');b=outline.create(USER,'B',fields,'b',collection_id='c')
        self.assertEqual(a['parentDocumentId'],b['parentDocumentId']);self.assertEqual(len(self.creates),3)
        parent=self.docs[a['parentDocumentId']];self.assertIsNone(outline.projected(parent));self.assertFalse(parent.get('parentDocumentId'))
        self.assertEqual(len(outline.tasks('c')),2)
        self.assertEqual(outline.create(USER,'A',fields,'a',collection_id='c')['id'],a['id']);self.assertEqual(len(self.creates),3)
    def test_existing_root_adopted_without_rewriting_and_rename_keeps_id(self):
        d=self.root();before=copy.deepcopy(d);self.assertEqual(outline.task_parent('c'),before)
        d['title']='프로젝트 업무';self.assertEqual(outline.task_parent('c')['id'],d['id']);self.assertEqual(len(self.creates),0)
    def test_each_project_has_its_own_parent(self):
        self.assertNotEqual(outline.task_parent('c')['id'],outline.task_parent('other')['id'])
    def test_lost_response_recovers_reserved_parent_without_duplicates(self):
        self.lose_response=True
        with self.assertRaises(TimeoutError):outline.task_parent('c')
        parent=outline.task_parent('c');self.assertEqual(parent['id'],self.creates[0]['id']);self.assertEqual(len(self.creates),1)
    def test_deleted_archived_or_moved_root_blocks_new_task_without_duplicate(self):
        for change in ({'deletedAt':'now'},{'archivedAt':'now'},{'collectionId':'other'},{'parentDocumentId':'elsewhere'}):
            self.docs.clear();store.put('task-parent:c',{'id':'existing','ready':True});self.root(**change)
            with self.assertRaises(HTTPException):outline.task_parent('c')
        self.assertEqual(self.creates,[])
    def test_ambiguous_roots_and_task_named_root_rejected(self):
        self.root();self.root('duplicate')
        with self.assertRaises(HTTPException):outline.task_parent('c')
        del self.docs['duplicate'];self.docs['existing']['text']=domain.render({'project':'P','owner':USER['email'],'status':'미착수'})
        with self.assertRaises(HTTPException):outline.task_parent('c')
        self.assertIsNone(store.get('task-parent:c'));self.assertEqual(self.creates,[])
    def test_nested_title_is_not_adopted(self):
        self.root(parentDocumentId='reference');parent=outline.task_parent('c');self.assertNotEqual(parent['id'],'existing')
    def test_unauthorized_creation_does_not_create_parent(self):
        with self.assertRaises(HTTPException):outline.create(USER,'A',{'owner':'other@example.com','status':'미착수'},'bad',collection_id='c')
        self.assertEqual(self.creates,[])
    def test_known_parent_does_not_depend_on_stale_list_results(self):
        parent=outline.task_parent('c')
        with patch.object(outline,'all_items',return_value=[]) as listing:
            self.assertEqual(outline.task_parent('c')['id'],parent['id'])
        listing.assert_not_called();self.assertEqual(len(self.creates),1)

if __name__=='__main__':unittest.main()
