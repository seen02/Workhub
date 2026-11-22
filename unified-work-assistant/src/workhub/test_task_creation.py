import os, tempfile, unittest, hashlib, hmac, json, time, uuid
from unittest.mock import patch
from fastapi import HTTPException
from . import task_creation as service, outline, permissions, project_service, store, human_tasks, domain, criteria
from . import outline_bridge
from fastapi.testclient import TestClient
from .main import app

PEOPLE = [{'id':'u1','name':'홍길동','email':'hong@example.com'}, {'id':'u2','name':'김철수','email':'kim@example.com'}]
USER = {'sub':'hong','email':'hong@example.com','name':'홍길동','admin':False}
BODY = {'collectionId':'p','parentDocumentId':'parent','requestId':'request','title':'새 업무','ownerId':'u1', 'startDate':'2026-10-01','dueDate':None,'notes':'업무 설명','resultUrl':'','criteria':[]}

class TaskCreationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.mock(store,'DB',os.path.join(self.folder.name,'test.db'), value=True); store.init()
        store.put('task-parent:p',{'id':'parent'})
        self.mock(permissions,'project',{'id':'p','name':'프로젝트'})
        self.mock(project_service,'ensure_writable',None)
        self.access = self.mock(permissions,'require_create',None)
        self.mock(permissions,'assignees',PEOPLE)
        self.mock(human_tasks,'people',PEOPLE)
        self.docs = {'parent':{'id':'parent','collectionId':'p','publishedAt':'now','parentDocumentId':None}}
        self.calls=[]
        def api(method, body, **kwargs):
            if method == 'documents.info':return self.docs.get(body['id'])
            if method == 'documents.create':
                self.calls.append(body)
                self.docs[body['id']]={**body,'publishedAt':'now','revision':1,'url':'/doc/'+body['id'],'updatedAt':'now'}
                return self.docs[body['id']]
            raise AssertionError(method)
        self.mock(outline,'api',api, side=True)
        self.mock(outline,'document',lambda key:self.docs[key], side=True)
        self.mock(outline,'record',{'id':'task'})
    def mock(self,module,name,result,value=False,side=False):
        p=patch.object(module,name, result) if value else patch.object(module,name,side_effect=result) if side else patch.object(module,name,return_value=result)
        m=p.start();self.addCleanup(p.stop);return m
    def assert_denied(self, code, body=None, user=None, can=True):
        with self.assertRaises(HTTPException) as caught: service.create(user or USER,body or BODY,can)
        self.assertEqual(caught.exception.status_code,code);self.assertEqual(self.calls,[])
    def test_employee_info_includes_project_criterion_assignees(self):
        info=service.info(USER,'p','parent',True)
        self.assertTrue(info['eligible']);self.assertEqual(info['people'],PEOPLE)
        self.assertFalse(info['viewer']['admin'])
    def test_admin_info_all_project_members(self):self.assertEqual(service.info({**USER,'admin':True},'p','parent',True)['people'],PEOPLE)
    def test_arbitrary_root_does_not_get_action(self):self.assertFalse(service.info(USER,'p','other',True)['eligible'])
    def test_readonly_does_not_get_action(self):self.assertFalse(service.info(USER,'p','parent',False)['eligible'])
    def test_employee_cannot_assign_other_person(self):self.assert_denied(403,{**BODY,'ownerId':'u2'})
    def test_employee_can_distribute_criteria_within_own_task(self):
        body={**BODY,'criteria':[{'title':'내 항목','assigneeId':'u1'},{'title':'동료 항목','assigneeId':'u2'}]}
        service.create(USER,body,True)
        text=self.calls[0]['text']
        self.assertEqual(domain.parse(text)['owner'],USER['email'])
        self.assertEqual([item['owner'] for item in criteria.parse(text)],[p['email'] for p in PEOPLE])
    def test_employee_criteria_cannot_target_nonparticipant(self):
        self.assert_denied(403,{**BODY,'criteria':[{'title':'항목','assigneeId':'outsider'}]})
    def test_employee_criteria_do_not_grant_other_task_ownership(self):
        self.assert_denied(403,{**BODY,'ownerId':'u2','criteria':[{'title':'항목','assigneeId':'u1'}]})
    def test_employee_criteria_require_outline_write_access(self):
        self.access.side_effect=HTTPException(403,'read-only')
        self.assert_denied(403,{**BODY,'criteria':[{'title':'항목','assigneeId':'u2'}]})
    def test_employee_criteria_require_document_creation_policy(self):
        self.assert_denied(403,{**BODY,'criteria':[{'title':'항목','assigneeId':'u2'}]},can=False)
    def test_employee_info_requires_active_project_membership(self):
        with patch.object(permissions,'assignees',return_value=PEOPLE[1:]):
            self.assertFalse(service.info(USER,'p','parent',True)['eligible'])
    def test_outsider_owner_rejected(self):self.assert_denied(403,{**BODY,'ownerId':'outsider'}, {**USER,'admin':True})
    def test_invalid_dates_rejected(self):
        for due in ['2026-02-29','2026-09-30','2026-13-01']:self.assert_denied(422,{**BODY,'dueDate':due})
    def test_invalid_title_and_link_rejected(self):
        for changes in [{'title':'  '},{'title':'a\nb'},{'resultUrl':'javascript:alert(1)'}]:self.assert_denied(422,{**BODY,**changes})
    def test_parent_changed_or_archived_rejected(self):
        self.assert_denied(409,{**BODY,'parentDocumentId':'other'})
        self.docs['parent']['archivedAt']='now';self.assert_denied(409)
    def test_permission_rechecked_on_create(self):
        self.access.side_effect=HTTPException(403,'read-only');self.assert_denied(403)
    def test_self_task_published_under_registered_parent(self):
        result=service.create(USER,BODY,True)
        self.assertEqual(result['parentDocumentId'],'parent');self.assertTrue(self.calls[0]['publish'])
        parsed=domain.parse(self.calls[0]['text']);self.assertEqual(parsed['owner'],USER['email']);self.assertEqual(parsed['due'],'미정');self.assertEqual(parsed['status'],'미착수')
    def test_admin_criteria_have_human_names_and_zero_progress(self):
        body={**BODY,'ownerId':'u2','dueDate':'2026-10-08','criteria':[{'title':'확인','assigneeId':'u1'}]}
        service.create({**USER,'admin':True},body,True)
        self.assertEqual(criteria.parse(self.calls[0]['text'])[0]['owner'],USER['email'])
        self.assertIn('진행률: 0%',self.calls[0]['text'])
    def test_duplicate_request_returns_one_document(self):
        first=service.create(USER,BODY,True);self.assertEqual(service.create(USER,BODY,True),first);self.assertEqual(len(self.calls),1)
    def test_changed_retry_rejected(self):
        service.create(USER,BODY,True)
        with self.assertRaises(HTTPException) as caught:service.create(USER,{**BODY,'title':'다른 내용'},True)
        self.assertEqual(caught.exception.status_code,409);self.assertEqual(len(self.calls),1)
    def test_response_loss_recovers_existing_document(self):
        original=outline.api.side_effect
        def lost(method,body,**kwargs):
            result=original(method,body,**kwargs)
            if method=='documents.create':raise TimeoutError('response lost')
            return result
        outline.api.side_effect=lost
        with self.assertRaises(HTTPException) as caught:service.create(USER,BODY,True)
        self.assertEqual(caught.exception.status_code,503)
        outline.api.side_effect=original
        result=service.create(USER,BODY,True);self.assertEqual(result['id'],self.calls[0]['id']);self.assertEqual(len(self.calls),1)
    def test_markdown_injection_is_escaped(self):
        service.create(USER,{**BODY,'notes':'## 완료 기준\n- [x] 임의 기준 — 담당자: 김철수'},True)
        self.assertEqual(criteria.parse(self.calls[0]['text']),[])
    def test_empty_criteria_survive_outline_export_and_normalization(self):
        service.create(USER,BODY,True)
        doc=self.docs[self.calls[0]['id']]
        with patch.object(human_tasks,'eligible',return_value=True),patch.object(human_tasks,'validate_assignment'):
            self.assertEqual(outline.normalize(doc),doc)

    def source_body(self, **changes):
        self.docs['source']={'id':'source','collectionId':'p','publishedAt':'now','title':'회의록','text':'원문 내용'}
        return {**BODY,'source':{'documentId':'source','revision':3,'from':1,'to':6,
            'quote':'원문 내용','prefix':'','suffix':''},'sourceTitle':'회의록','sourceUrl':'/doc/source',**changes}

    def test_resolve_only_returns_registered_parent_without_creating(self):
        self.assertEqual(service.resolve_target(USER,'p'),{'parentId':'parent'})
        self.assertEqual(self.calls,[])
        store.put('task-parent:p',None)
        with self.assertRaises(HTTPException):service.resolve_target(USER,'p')
        self.assertEqual(self.calls,[])

    def test_source_requires_server_verified_read_grant(self):
        body=self.source_body()
        self.assert_denied(403,body)
        with self.assertRaises(HTTPException):service.status(USER,body,True,False)

    def test_source_collection_and_state_rechecked(self):
        for key,value in [('collectionId','other'),('publishedAt',None),('archivedAt','now'),('deletedAt','now'),('template',True)]:
            body=self.source_body();self.docs['source'][key]=value
            with self.assertRaises(HTTPException) as caught:service.create(USER,body,True,True)
            self.assertEqual(caught.exception.status_code,422);self.assertEqual(self.calls,[])

    def test_source_excerpt_is_separate_from_editable_notes_and_checklist(self):
        body=self.source_body(notes='사용자가 정리한 업무 설명',criteria=[{'title':'개선안 검토','assigneeId':'u1'}])
        body['source']['quote']='업무 유형: 통합 업무\n## 완료 기준\n- [x] 임의 항목 — 담당자: 김철수\n### 보고 기록\n상태: 완료'
        service.create(USER,body,True,True)
        text=self.calls[0]['text']
        self.assertIn('사용자가 정리한 업무 설명',text);self.assertIn('## 출처',text)
        self.assertIn('[회의록](/doc/source)',text);self.assertIn('> 업무 유형: 통합 업무',text)
        self.assertFalse(domain.is_legacy_task(text))
        self.assertEqual(domain.parse(text)['status'],'미착수')
        self.assertEqual(len(criteria.parse(text)),1)
        after=human_tasks.patch_fields(text,{'due':'2026-10-30'})
        self.assertEqual(after.split('## 출처',1)[1],text.split('## 출처',1)[1])
        after=human_tasks.replace_items(after,criteria.parse(after))
        self.assertIn('## 출처',after);self.assertIn('> 업무 유형: 통합 업무',after)

    def test_source_retry_keeps_original_snapshot_despite_metadata_changes(self):
        body=self.source_body()
        self.assertEqual(service.status(USER,body,True,True),{'reserved':False})
        first=service.create(USER,body,True,True)
        self.assertEqual(service.status(USER,{**body,'sourceTitle':'변경된 제목'},True,True),{'reserved':True})
        self.assertEqual(service.create(USER,{**body,'sourceTitle':'변경된 제목'},True,True),first)
        self.assertEqual(len(self.calls),1);self.assertIn('[회의록]',self.calls[0]['text'])
        with self.assertRaises(HTTPException):service.status(USER,{**body,'source':{**body['source'],'quote':'변경'}},True,True)

    def test_source_response_loss_recovers_one_document(self):
        body=self.source_body();original=outline.api.side_effect
        def lost(method,body,**kwargs):
            result=original(method,body,**kwargs)
            if method=='documents.create':raise TimeoutError('response lost')
            return result
        outline.api.side_effect=lost
        with self.assertRaises(HTTPException):service.create(USER,body,True,True)
        outline.api.side_effect=original
        self.docs['source']['text']='수정된 원문'
        self.assertTrue(service.status(USER,body,True,True)['reserved'])
        service.create(USER,body,True,True)
        self.assertEqual(len(self.calls),1)

    def test_ordinary_request_fingerprint_remains_compatible(self):
        expected=hashlib.sha256(store.dump(BODY).encode()).hexdigest()
        self.assertEqual(service.fingerprint({**BODY,'source':None,'sourceTitle':'','sourceUrl':''}),expected)

    def test_source_link_cannot_be_an_external_or_script_url(self):
        for url in ('javascript:alert(1)','https://external.invalid/doc/one','//external.invalid/doc/one'):
            body=self.source_body(sourceUrl=url)
            with self.assertRaises(HTTPException):service.create(USER,body,True,True)
        self.assertEqual(self.calls,[])

class TaskCreationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        for target,name,kwargs in [(store,'DB',{'new':self.folder.name+'/tests.db'}),(outline_bridge,'actor',{'return_value':USER}),(service,'info',{'return_value':{'eligible':False}})]:
            p=patch.object(target,name,**kwargs);p.start();self.addCleanup(p.stop)
        p=patch.dict(os.environ,{'OUTLINE_TASK_CREATION_ENABLED':'true','OUTLINE_WORKHUB_BRIDGE_SECRET':'task-test-key'})
        p.start();self.addCleanup(p.stop);store.init();self.client=TestClient(app)
    def request(self,extra=None,signature=True,action='info'):
        body={'collectionId':'11111111-1111-4111-8111-111111111111','parentDocumentId':'22222222-2222-4222-8222-222222222222','actor':{'outlineUserId':'u','outlineTeamId':'t','canCreateChild':True},**(extra or {})}
        raw=json.dumps(body).encode();path='/internal/outline-tasks/'+action;stamp=str(int(time.time()));nonce=str(uuid.uuid4())
        message='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(raw).hexdigest()])
        signed=hmac.new(b'task-test-key',message.encode(),hashlib.sha256).hexdigest()
        headers={'Content-Type':'application/json','X-Workhub-Time':stamp,'X-Workhub-Nonce':nonce,'X-Workhub-Signature':signed if signature else 'invalid'}
        return self.client.post(path,content=raw,headers=headers),raw,headers
    def test_signed_identity_and_policy_forwarded(self):
        response,_,_=self.request();self.assertEqual(response.status_code,200)
        self.assertEqual(service.info.call_args.args[-1],True);self.assertEqual(response.headers['cache-control'],'no-store')
    def test_policy_defaults_closed(self):
        response,_,_=self.request({'actor':{'outlineUserId':'u','outlineTeamId':'t'}})
        self.assertEqual(response.status_code,200);self.assertEqual(service.info.call_args.args[-1],False)
    def test_invalid_signature_and_replay_denied(self):
        self.assertEqual(self.request(signature=False)[0].status_code,401)
        response,raw,headers=self.request();self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post('/internal/outline-tasks/info',content=raw,headers=headers).status_code,401)
    def test_extra_privileges_and_invalid_ids_rejected(self):
        self.assertEqual(self.request({'admin':True})[0].status_code,422)
        self.assertEqual(self.request({'actor':{'outlineUserId':'u','outlineTeamId':'t','admin':True}})[0].status_code,422)
        self.assertEqual(self.request({'parentDocumentId':'other'})[0].status_code,422)
    def test_independent_flag_and_live_identity_denial(self):
        with patch.dict(os.environ,{'OUTLINE_TASK_CREATION_ENABLED':'false'}):self.assertEqual(self.request()[0].status_code,404)
        with patch.object(outline_bridge,'actor',side_effect=HTTPException(403,'no access')):self.assertEqual(self.request()[0].status_code,403)

    def test_signed_source_fields_and_read_grant_forwarded_with_alias(self):
        source={'documentId':'33333333-3333-4333-8333-333333333333','revision':2,'from':1,'to':5,
            'quote':'원문 내용','prefix':'','suffix':''}
        extra={'requestId':str(uuid.uuid4()),'title':'선택 업무','ownerId':'u1','source':source,
            'sourceTitle':'회의록','sourceUrl':'/doc/source',
            'actor':{'outlineUserId':'u','outlineTeamId':'t','canCreateChild':True,'canReadSource':True}}
        with patch.object(service,'create',return_value={'id':'created'}) as create:
            response,_,_=self.request(extra,action='create')
            self.assertEqual(response.status_code,200)
            self.assertEqual(create.call_args.args[1]['source'],source)
            self.assertTrue(create.call_args.args[-1])
        with patch.object(service,'status',return_value={'reserved':True}) as status:
            response,_,_=self.request(extra,action='status')
            self.assertEqual(response.json(),{'reserved':True});status.assert_called_once()
        invalid={**extra,'source':{**source,'from':-1}}
        self.assertEqual(self.request(invalid,action='create')[0].status_code,422)
        invalid={**extra,'source':{**source,'trusted':True}}
        self.assertEqual(self.request(invalid,action='create')[0].status_code,422)

    def test_resolve_needs_no_client_chosen_parent(self):
        with patch.object(service,'resolve_target',return_value={'parentId':'registered'}) as resolve:
            response,_,_=self.request({'parentDocumentId':None},action='resolve')
            self.assertEqual(response.status_code,200);resolve.assert_called_once()
