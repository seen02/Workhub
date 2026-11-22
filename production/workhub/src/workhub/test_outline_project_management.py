import hashlib, hmac, json, os, tempfile, time, unittest, uuid
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from . import store, outline, project_service as service, outline_bridge as bridge
from .main import app

ADMIN={'sub':'admin','email':'a@example.test','admin':True}
USER={'sub':'user','email':'u@example.test','admin':False}

class ProjectManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DB',self.tmp.name+'/test.sqlite3');p.start();self.addCleanup(p.stop)
        store.init();store.put('projects',[])
        p=patch.object(outline.permissions,'Access');self.access=p.start().return_value;self.addCleanup(p.stop)
        self.access.require.return_value={'id':'c','name':'Project','permission':'read_write'};self.access.collections={'c':{'name':'Project','permission':'read_write'}}
        p=patch.object(bridge,'managers',return_value=[{'id':'admin','email':'a@example.test','name':'Admin'}]);p.start();self.addCleanup(p.stop)
        p=patch.object(outline,'api');self.api=p.start();self.addCleanup(p.stop)
        p=patch.object(outline.permissions,'require_create');self.create_access=p.start();self.addCleanup(p.stop)
        p=patch.object(outline.permissions,'require_project_linkable');self.link_access=p.start();self.addCleanup(p.stop)
        self.parent_patch=patch.object(outline,'task_parent',return_value={'id':'p'})
        self.parent=self.parent_patch.start();self.addCleanup(self.parent_patch.stop)
        self.addCleanup(lambda:setattr(outline,'PROJECTS_CACHE',{'until':0,'available':{}}))
    def request(self,revision=0,**kwargs):
        return {'collectionId':'c','requestId':str(uuid.uuid4()),'expectedRevision':revision,'managerSubject':None,'deleteTaskList':False,'expectedParentId':None,**kwargs}
    def test_link_receipt_survives_restart_and_preserves_id(self):
        body=self.request(managerSubject='admin');first=service.mutate(ADMIN,'link',body)
        service.init();again=service.mutate(ADMIN,'link',body)
        self.assertEqual(first['revision'],again['revision']);self.assertEqual(len(store.get('projects')),1)
        self.assertEqual(store.get('projects')[0]['manager'],'a@example.test');self.api.assert_not_called()
    def test_same_request_changed_payload_conflicts(self):
        body=self.request();service.mutate(ADMIN,'link',body)
        with self.assertRaises(HTTPException) as e:service.mutate(ADMIN,'link',{**body,'managerSubject':'admin'})
        self.assertEqual(e.exception.status_code,409)
    def task_documents(self,existing=None,lose_response=False):
        self.parent_patch.stop()
        docs={existing['id']:existing} if existing else {};created=[]
        p=patch.object(outline,'all_items',side_effect=lambda *args:list(docs.values()));p.start();self.addCleanup(p.stop)
        def api(method,body,missing_ok=False):
            if method=='documents.info':return docs.get(body['id'])
            if method=='documents.create':
                self.assertNotIn(body['id'],docs)
                docs[body['id']]={**body,'publishedAt':'now'};created.append(body['id'])
                if lose_response and len(created)==1:raise HTTPException(503,'response lost')
                return docs[body['id']]
            raise AssertionError(method)
        self.api.side_effect=api
        return docs,created
    def test_link_creates_published_root_once_before_success(self):
        docs,created=self.task_documents();body=self.request()
        result=service.mutate(ADMIN,'link',body)
        self.assertTrue(result['linked']);self.assertEqual(len(created),1)
        parent=docs[created[0]]
        self.assertEqual(parent['title'],'업무 목록');self.assertEqual(parent['collectionId'],'c')
        self.assertTrue(parent['publishedAt']);self.assertFalse(parent.get('parentDocumentId'))
        service.mutate(ADMIN,'link',body);self.assertEqual(len(created),1)
    def test_link_adopts_existing_root_and_relink_keeps_document(self):
        existing={'id':'existing','title':'업무 목록','collectionId':'c','text':'기존 안내 보존','publishedAt':'now'}
        docs,created=self.task_documents(existing)
        service.mutate(ADMIN,'link',self.request());service.mutate(ADMIN,'unlink',self.request(1))
        service.mutate(ADMIN,'link',self.request(2))
        self.assertEqual(created,[]);self.assertEqual(docs['existing'],existing)
        self.assertEqual(store.get('task-parent:c')['id'],'existing')
    def test_link_parent_response_loss_resumes_without_duplicate(self):
        docs,created=self.task_documents(lose_response=True);body=self.request()
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'link',body)
        self.assertEqual(store.get('projects'),[]);self.assertFalse(service.state('c')['linked'])
        self.assertEqual(service.operation(ADMIN,'c',body['requestId'])['operationStatus'],'pending')
        service.init();result=service.resume(ADMIN,'c',body['requestId'],None)
        self.assertTrue(result['linked']);self.assertEqual(len(created),1)
        self.assertEqual(store.get('task-parent:c')['id'],created[0])
    def test_link_without_document_write_access_leaves_no_pending_operation(self):
        self.create_access.side_effect=HTTPException(403,'read only')
        body=self.request()
        with self.assertRaises(HTTPException) as error:service.mutate(ADMIN,'link',body)
        self.assertEqual(error.exception.status_code,403);self.parent.assert_not_called()
        self.assertEqual(store.get('projects'),[])
        with store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM project_operations').fetchone()[0],0)
    def test_old_link_does_not_reconnect(self):
        link=self.request();service.mutate(ADMIN,'link',link);service.mutate(ADMIN,'unlink',self.request(1))
        service.mutate(ADMIN,'link',link);self.assertFalse(service.state('c')['linked'])
    def test_old_unlink_does_not_disconnect_new_generation(self):
        service.mutate(ADMIN,'link',self.request());unlink=self.request(1)
        service.mutate(ADMIN,'unlink',unlink);service.mutate(ADMIN,'link',self.request(2))
        service.mutate(ADMIN,'unlink',unlink);self.assertTrue(service.state('c')['linked']);self.assertEqual(service.state('c')['revision'],3)
    def test_conflicting_revision(self):
        service.mutate(ADMIN,'link',self.request())
        with self.assertRaises(HTTPException) as e:service.mutate(ADMIN,'manager',self.request(0))
        self.assertEqual(e.exception.status_code,409)
    def test_default_unlink_preserves_original_and_clears_cache(self):
        service.mutate(ADMIN,'link',self.request());store.put('task-parent:c',{'id':'p','ready':True})
        with store.db() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,1)',('t',json.dumps({'collectionId':'c'}),'1'))
        service.mutate(ADMIN,'unlink',self.request(1))
        self.api.assert_not_called();self.assertEqual(store.get('task-parent:c')['id'],'p');self.assertEqual(store.get('projects'),[])
        with store.db() as c:self.assertEqual(c.execute('SELECT active FROM tasks').fetchone()[0],0)
    def test_non_admin_rejected(self):
        with self.assertRaises(HTTPException) as e:service.mutate({**ADMIN,'admin':False},'link',self.request())
        self.assertEqual(e.exception.status_code,403)
    def test_collection_manager_can_link_preview_unlink_and_relink(self):
        docs,created=self.task_documents()
        link=self.request();result=service.mutate(USER,'link',link,can_manage=True)
        docs[created[0]]['url']='/doc/task-parent'
        self.assertTrue(result['linked']);self.assertFalse(USER['admin'])
        permissions=service.info(USER,'c',True,can_manage=True)['permissions']
        self.assertEqual(permissions,{'manage':True,'updateManager':False,'deleteTaskList':False})
        with patch.object(outline.permissions,'project',return_value={'id':'c','name':'Project'}):
            self.assertTrue(service.preview(USER,'c',can_manage=True)['linked'])
        self.assertEqual(service.operation(USER,'c',link['requestId'],can_manage=True)['operationStatus'],'completed')
        service.mutate(USER,'unlink',self.request(1),can_manage=True)
        with store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM tasks WHERE active=1').fetchone()[0],0)
        self.assertTrue(service.mutate(USER,'link',self.request(2),can_manage=True)['linked'])
    def test_reconnect_by_collection_manager_preserves_responsibility(self):
        service.mutate(ADMIN,'link',self.request(managerSubject='admin'))
        service.mutate(USER,'unlink',self.request(1),can_manage=True)
        service.mutate(USER,'link',self.request(2),can_manage=True)
        self.assertEqual(store.get('projects')[0]['manager'],ADMIN['email'])
    def test_readonly_user_cannot_manage_or_see_recovery_details(self):
        self.assertFalse(service.info(USER,'c')['permissions']['manage'])
        for action in ('link','unlink','manager'):
            with self.subTest(action=action),self.assertRaises(HTTPException) as error:
                service.mutate(USER,action,self.request())
            self.assertEqual(error.exception.status_code,403)
        self.parent.assert_not_called();self.assertEqual(store.get('projects'),[])
    def test_collection_management_does_not_bypass_read_access(self):
        self.access.require.side_effect=HTTPException(403,'no access')
        with self.assertRaises(HTTPException) as error:service.mutate(USER,'link',self.request(),can_manage=True)
        self.assertEqual(error.exception.status_code,403);self.parent.assert_not_called()
    def test_collection_manager_cannot_change_manager_or_delete_documents(self):
        service.mutate(USER,'link',self.request(),can_manage=True)
        for action,body in [('manager',self.request(1)),('link',self.request(1,managerSubject='admin')),
                            ('unlink',self.request(1,deleteTaskList=True,expectedParentId='p'))]:
            with self.subTest(action=action),self.assertRaises(HTTPException) as error:
                service.mutate(USER,action,body,True,can_manage=True)
            self.assertEqual(error.exception.status_code,403)
        self.api.assert_not_called();self.assertTrue(service.state('c')['linked'])
    def test_collection_manager_can_resume_response_loss_after_restart(self):
        docs,created=self.task_documents(lose_response=True);body=self.request()
        with self.assertRaises(HTTPException):service.mutate(USER,'link',body,can_manage=True)
        self.assertEqual(service.info(USER,'c',can_manage=True)['pendingOperation']['requestId'],body['requestId'])
        service.init()
        self.assertTrue(service.resume(USER,'c',body['requestId'],None,can_manage=True)['linked'])
        self.assertEqual(len(created),1)
    def test_revoked_management_blocks_retry_lookup_preview_and_resume(self):
        self.task_documents(lose_response=True);body=self.request()
        with self.assertRaises(HTTPException):service.mutate(USER,'link',body,can_manage=True)
        for operation in [lambda:service.mutate(USER,'link',body),lambda:service.operation(USER,'c',body['requestId']),
                          lambda:service.preview(USER,'c'),lambda:service.resume(USER,'c',body['requestId'],None)]:
            with self.assertRaises(HTTPException) as error:operation()
            self.assertEqual(error.exception.status_code,403)
        self.assertIsNone(service.info(USER,'c')['pendingOperation'])
    def test_collection_manager_cannot_resume_pending_admin_delete(self):
        service.mutate(ADMIN,'link',self.request());store.put('task-parent:c',{'id':'p','ready':True})
        self.api.side_effect=[{'id':'p','collectionId':'c','text':'intro'},HTTPException(503,'lost')]
        body=self.request(1,deleteTaskList=True,expectedParentId='p')
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'unlink',body,True)
        self.assertIsNone(service.info(USER,'c',can_manage=True)['pendingOperation'])
        with self.assertRaises(HTTPException) as error:service.resume(USER,'c',body['requestId'],'p',True,can_manage=True)
        self.assertEqual(error.exception.status_code,403)
    def test_ineligible_manager_rejected(self):
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'link',self.request(managerSubject='outsider'))
        self.assertEqual(store.get('projects'),[])
    def test_delete_requires_explicit_policy(self):
        service.mutate(ADMIN,'link',self.request())
        with self.assertRaises(HTTPException) as e:service.mutate(ADMIN,'unlink',self.request(1,deleteTaskList=True,expectedParentId='p'))
        self.assertEqual(e.exception.status_code,403);self.assertTrue(service.state('c')['linked'])
    def test_delete_lost_response_recovers_after_restart(self):
        service.mutate(ADMIN,'link',self.request());store.put('task-parent:c',{'id':'p','ready':True})
        parent={'id':'p','title':'업무 목록','collectionId':'c','text':'intro'}
        self.api.side_effect=[parent,HTTPException(503,'lost')]
        body=self.request(1,deleteTaskList=True,expectedParentId='p')
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'unlink',body,True)
        self.assertTrue(service.state('c')['linked'])
        with self.assertRaises(HTTPException):service.ensure_writable('c')
        service.init();self.api.side_effect=[None]
        result=service.mutate(ADMIN,'unlink',body,True)
        self.assertFalse(result['linked']);self.assertIsNone(store.get('task-parent:c'))
        self.assertEqual(sum(call.args[0]=='documents.delete' for call in self.api.call_args_list),1)
    def test_moved_parent_never_deleted(self):
        service.mutate(ADMIN,'link',self.request());store.put('task-parent:c',{'id':'p'})
        self.api.return_value={'id':'p','collectionId':'other','text':''}
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'unlink',self.request(1,deleteTaskList=True,expectedParentId='p'),True)
        self.assertEqual(self.api.call_count,1)
    def test_other_current_admin_can_resume_durable_pending_delete(self):
        service.mutate(ADMIN,'link',self.request());store.put('task-parent:c',{'id':'p','ready':True})
        self.api.side_effect=[{'id':'p','collectionId':'c','text':'intro'},HTTPException(503,'lost')]
        body=self.request(1,deleteTaskList=True,expectedParentId='p')
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'unlink',body,True)
        service.init();self.api.side_effect=[None]
        other={**ADMIN,'sub':'another-admin'}
        result=service.resume(other,'c',body['requestId'],'p',True)
        self.assertFalse(result['linked']);self.assertEqual(result['appliedBy'],'another-admin')
    def test_resume_rechecks_document_and_admin(self):
        with self.assertRaises(HTTPException):service.resume({**ADMIN,'admin':False},'c','no','p',True)
    def test_sync_completion_does_not_acknowledge_later_generation(self):
        service.mutate(ADMIN,'link',self.request());jobs=service.sync_snapshot()
        service.mutate(ADMIN,'unlink',self.request(1));service.sync_complete(jobs)
        self.assertEqual(service.info(ADMIN,'c')['syncStatus'],'pending')
    def test_parallel_distinct_request_does_not_overwrite(self):
        service.mutate(ADMIN,'link',self.request())
        with self.assertRaises(HTTPException):service.mutate(ADMIN,'link',self.request())
        self.assertEqual(len(store.get('projects')),1)
    def signed(self,raw=b'{}',stamp=None,nonce=None):
        stamp=str(stamp or int(time.time()));nonce=nonce or str(uuid.uuid4());path='/internal/outline-projects/info'
        message='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(raw).hexdigest()])
        return {'x-workhub-time':stamp,'x-workhub-nonce':nonce,'x-workhub-signature':hmac.new(b'test-secret',message.encode(),hashlib.sha256).hexdigest()}
    @patch.dict(os.environ,{'OUTLINE_PROJECT_MANAGEMENT_ENABLED':'true','OUTLINE_WORKHUB_BRIDGE_SECRET':'test-secret'})
    def test_signature_replay_and_tamper_rejected(self):
        headers=self.signed();bridge.verify(b'{}','/internal/outline-projects/info',headers)
        with self.assertRaises(HTTPException):bridge.verify(b'{}','/internal/outline-projects/info',headers)
        with self.assertRaises(HTTPException):bridge.verify(b'{"actor":"other"}','/internal/outline-projects/info',self.signed())
        with self.assertRaises(HTTPException):bridge.verify(b'{}','/internal/outline-projects/info',self.signed(stamp=int(time.time())-120))
    @patch.dict(os.environ,{'OUTLINE_WORKHUB_TEAM_ID':'ours'})
    def test_foreign_team_rejected(self):
        with self.assertRaises(HTTPException) as e:bridge.actor({'outlineTeamId':'other','outlineUserId':'u'})
        self.assertEqual(e.exception.status_code,403)

class ProjectManagementBridgeTests(unittest.TestCase):
    request=ProjectManagementTests.request
    def setUp(self):
        ProjectManagementTests.setUp(self)
        for p in [patch.object(bridge,'actor',return_value=USER),
                  patch.dict(os.environ,{'OUTLINE_PROJECT_MANAGEMENT_ENABLED':'true','OUTLINE_WORKHUB_BRIDGE_SECRET':'test-secret'})]:
            p.start();self.addCleanup(p.stop)
        self.client=TestClient(app)
    def post(self,action,body=None,actor=None,signature=True):
        payload={'collectionId':'c',**(body or {}),'actor':{'outlineUserId':'u','outlineTeamId':'t',**(actor or {})}}
        raw=json.dumps(payload).encode();path='/internal/outline-projects/'+action
        stamp=str(int(time.time()));nonce=str(uuid.uuid4())
        message='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(raw).hexdigest()])
        headers={'Content-Type':'application/json','x-workhub-time':stamp,'x-workhub-nonce':nonce,
                 'x-workhub-signature':hmac.new(b'test-secret',message.encode(),hashlib.sha256).hexdigest() if signature else 'invalid'}
        return self.client.post(path,content=raw,headers=headers)
    def test_signed_collection_policy_allows_link_and_unlink(self):
        linked=self.post('link',self.request(),{'canManageProject':True})
        self.assertEqual(linked.status_code,200);self.assertTrue(linked.json()['linked'])
        self.assertEqual(self.post('unlink',self.request(1),{'canManageProject':True}).status_code,200)
    def test_service_access_failure_rejects_link_even_for_admin(self):
        self.access.require.return_value['permission']=None
        self.link_access.side_effect=HTTPException(403,outline.permissions.PROJECT_LINK_ACCESS_ERROR)
        for user in (USER,ADMIN):
            with patch.object(bridge,'actor',return_value=user):
                response=self.post('link',self.request(),{'canManageProject':True})
            self.assertEqual(response.status_code,403)
            self.assertEqual(response.json()['detail'],outline.permissions.PROJECT_LINK_ACCESS_ERROR)
        self.parent.assert_not_called();self.assertEqual(store.get('projects'),[])
        with store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM project_operations').fetchone()[0],0)
    def test_missing_policy_and_create_capability_do_not_allow_link(self):
        for actor in ({},{'canCreateCollection':True},{'canManageProject':False}):
            self.assertEqual(self.post('link',self.request(),actor).status_code,403)
        self.parent.assert_not_called()
    def test_tampering_and_extra_browser_privileges_are_denied(self):
        self.assertEqual(self.post('link',self.request(),{'canManageProject':True},signature=False).status_code,401)
        self.assertEqual(self.post('link',{**self.request(),'canManageProject':True}).status_code,422)
        self.assertEqual(self.post('link',self.request(),{'admin':True}).status_code,422)
        self.parent.assert_not_called()
    def test_info_and_new_collection_capability(self):
        info=self.post('info',actor={'canManageProject':True})
        self.assertEqual(info.status_code,200);self.assertTrue(info.json()['permissions']['manage'])
        self.assertEqual(info.headers['cache-control'],'no-store')
        self.assertTrue(self.post('capabilities',actor={'canCreateCollection':True}).json()['manage'])
        self.assertFalse(self.post('capabilities').json()['manage'])

    def test_connection_group_requires_signed_collection_creation_permission(self):
        with patch.object(outline.permissions,'project_connection_group',return_value={'groupId':'group','serviceUserId':'service'}) as resolve:
            self.assertEqual(self.post('connection-group',body={'collectionId':''}).status_code,403)
            self.assertEqual(self.post('connection-group',body={'collectionId':''},actor={'canCreateCollection':True},signature=False).status_code,401)
            resolve.assert_not_called()
            response=self.post('connection-group',body={'collectionId':''},actor={'canCreateCollection':True})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['groupId'],'group')

    def test_existing_collection_manager_can_prepare_group_access_without_creation_permission(self):
        with patch.object(outline.permissions,'project_connection_group',return_value={'groupId':'group','serviceUserId':'service'}):
            response=self.post('connection-group',self.request(),{'canManageProject':True})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['groupId'],'group')

    def test_completed_link_replay_does_not_restore_revoked_group_permissions(self):
        body=self.request()
        self.assertEqual(self.post('link',body,{'canManageProject':True}).status_code,200)
        self.assertEqual(self.post('unlink',self.request(1),{'canManageProject':True}).status_code,200)
        with patch.object(outline.permissions,'project_connection_group') as resolve:
            response=self.post('connection-group',body,{'canManageProject':True})
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['skipGrant'])
            resolve.assert_not_called()

    def test_stale_or_unauthorized_link_cannot_change_group_permissions(self):
        with patch.object(outline.permissions,'project_connection_group') as resolve:
            self.assertEqual(self.post('connection-group',self.request(8),{'canManageProject':True}).status_code,409)
            self.assertEqual(self.post('connection-group',self.request()).status_code,403)
            self.assertEqual(self.post('connection-group',self.request(managerSubject='admin'),{'canManageProject':True}).status_code,403)
            resolve.assert_not_called()


if __name__=='__main__':unittest.main()
