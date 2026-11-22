import os, tempfile, unittest, copy, json, uuid, time, hashlib, hmac
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from . import kanban, outline, domain, criteria, permissions, store, project_service, outline_bridge, human_tasks, task_status
from .main import app

USER={'sub':'a','email':'a@example.com','admin':False}
ADMIN={**USER,'admin':True}
PEOPLE=[{'name':'직원 A','email':'a@example.com'},{'name':'직원 B','email':'b@example.com'}]
FIELDS={'project':'프로젝트','owner':'a@example.com','start':'2026-10-01','due':'2026-10-08','status':'미착수','progress':'0%'}

class KanbanTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        for module,name,value in [(store,'DB',self.folder.name+'/test.db')]:
            p=patch.object(module,name,value);p.start();self.addCleanup(p.stop)
        store.init();store.put('task-parent:p',{'id':'parent'})
        self.docs={'parent':{'id':'parent','collectionId':'p','publishedAt':'now'},
                   'task':{'id':'task','collectionId':'p','parentDocumentId':'parent','title':'업무',
                           'publishedAt':'now','revision':1,'updatedAt':'t1','url':'/doc/task',
                           'text':domain.render(FIELDS,'원본 메모\n\n### 보고 기록\n\n```text\n상태: 보류\n```')}}
        self.writes=[];self.loss=False;self.read_loss=False
        def api(method,body,**kwargs):
            if method=='documents.info':
                if self.read_loss and self.writes:raise TimeoutError('read lost')
                return copy.deepcopy(self.docs.get(body['id']))
            if method=='documents.update':
                self.assertEqual(body['lastRevision'],self.docs[body['id']]['revision'])
                self.writes.append(body)
                self.docs[body['id']].update(text=body['text'],revision=2,updatedAt='t2')
                if self.loss:raise TimeoutError('lost response')
                return self.docs[body['id']]
            raise AssertionError(method)
        self.mock(outline,'api',side_effect=api)
        self.mock(outline,'project',return_value={'name':'프로젝트'})
        self.mock(permissions,'project',return_value={'name':'프로젝트'})
        self.permission=self.mock(permissions,'document',return_value=None)
        self.mock(permissions,'assignees',return_value=PEOPLE)
        self.mock(project_service,'ensure_writable',return_value=None)
        self.mock(outline,'record',return_value={})
        self.body={'collectionId':'p','parentDocumentId':'parent','documentId':'task','requestId':'request',
                   'revision':1,'updatedAt':'t1','status':'진행 중','criterionId':'','criterionState':''}
    def mock(self,module,name,**kwargs):
        p=patch.object(module,name,**kwargs);m=p.start();self.addCleanup(p.stop);return m
    def deny(self,code,user=USER,can=True,**changes):
        with self.assertRaises(HTTPException) as ex:kanban.mutate(user,{**self.body,**changes},can)
        self.assertEqual(ex.exception.status_code,code);self.assertFalse(self.writes)
    def test_only_mapped_root_is_eligible(self):
        self.assertTrue(kanban.info(USER,'p','parent')['eligible'])
        self.assertFalse(kanban.info(USER,'p','other')['eligible'])
    def test_fresh_query_includes_other_owners_and_unclassified(self):
        self.docs['task']['text']=domain.render({**FIELDS,'owner':'b@example.com'})
        self.docs['unknown']={**self.docs['task'],'id':'unknown','text':'평범한 문서','url':'/doc/unknown'}
        result=kanban.query(USER,'p','parent',[{'id':'task','canUpdate':True},{'id':'unknown','canUpdate':False}])
        self.assertEqual(len(result['cards']),2)
        self.assertFalse(result['cards'][0]['canMove'])
        self.assertTrue(result['cards'][1]['unclassified'])
        self.assertFalse(self.writes)
    def test_query_only_signed_grants_are_read(self):
        self.assertEqual(kanban.query(USER,'p','parent',[])['cards'],[])
    def test_native_readonly_and_other_owner_cannot_change(self):
        self.deny(403,can=False)
        self.docs['task']['text']=domain.render({**FIELDS,'owner':'b@example.com'})
        self.deny(403)
    def test_outdated_version_prevents_overwrite(self):self.deny(409,revision=0)
    def test_moved_archived_draft_or_template_prevents_mutation(self):
        for change in [{'parentDocumentId':'elsewhere'},{'archivedAt':'now'},{'publishedAt':None},{'template':True}]:
            before=copy.deepcopy(self.docs['task']);self.docs['task'].update(change)
            self.deny(409);self.docs['task']=before
    def test_save_preserves_notes_and_history_and_deduplicates(self):
        first=kanban.mutate(USER,self.body,True)
        self.assertEqual(first['status'],'진행 중')
        self.assertIn('상태: 보류\n```',self.docs['task']['text'])
        self.assertEqual(kanban.mutate(USER,self.body,True),first)
        self.assertEqual(len(self.writes),1)
    def test_same_request_with_changed_payload_rejected(self):
        kanban.mutate(USER,self.body,True)
        with self.assertRaises(HTTPException) as ex:kanban.mutate(USER,{**self.body,'status':'보류'},True)
        self.assertEqual(ex.exception.status_code,409);self.assertEqual(len(self.writes),1)
    def test_lost_write_response_verified_without_duplicate(self):
        self.loss=True
        self.assertEqual(kanban.mutate(USER,self.body,True)['status'],'진행 중')
        self.assertEqual(len(self.writes),1)
    def test_lost_read_response_recovers_same_request(self):
        self.read_loss=True
        with self.assertRaises(HTTPException) as ex:kanban.mutate(USER,self.body,True)
        self.assertEqual(ex.exception.status_code,503)
        self.read_loss=False
        self.assertEqual(kanban.mutate(USER,self.body,True)['status'],'진행 중')
        self.assertEqual(len(self.writes),1)
    def test_no_retry_overwrites_following_edit(self):
        self.read_loss=True
        with self.assertRaises(HTTPException):kanban.mutate(USER,self.body,True)
        self.read_loss=False;self.docs['task']['text']+='\n다른 편집';self.docs['task']['revision']=3
        with self.assertRaises(HTTPException) as ex:kanban.mutate(USER,self.body,True)
        self.assertEqual(ex.exception.status_code,409);self.assertEqual(len(self.writes),1)
    def test_missing_progress_is_not_zero(self):
        self.docs['task']['text']=domain.render({**FIELDS,'progress':'미기재'})
        self.assertIsNone(kanban.query(USER,'p','parent',[{'id':'task','canUpdate':True}])['cards'][0]['progress'])
    def test_human_plain_completion_and_reopen_persist_progress(self):
        self.mock(human_tasks,'people',return_value=PEOPLE)
        self.mock(human_tasks,'eligible',return_value=True)
        self.mock(human_tasks,'validate_assignment',return_value=None)
        self.docs['task']['text']='담당자: 직원 A (a@example.com)\n\n시작일: 2026-10-01\n\n마감일: 미정\n\n상태: 미착수\n\n진행률: 0%\n\n## 업무 내용\n\n원본 메모\n\n## 완료 기준'
        completed=kanban.mutate(USER,{**self.body,'status':'완료'},True)
        self.assertEqual(completed['progress'],100)
        self.assertIn('진행률: 100%',self.docs['task']['text'])
        reopened=kanban.mutate(USER,{**self.body,'requestId':'reopen','revision':2,'updatedAt':'t2','status':'진행 중'},True)
        self.assertEqual(reopened['progress'],0)
        self.assertIn('원본 메모',self.docs['task']['text'])
    def set_criteria(self):
        self.docs['task']['text']=criteria.replace(domain.render(FIELDS),[
            {'id':'C-11111111','title':'첫 기준','owner':'a@example.com','state':'예정'},
            {'id':'C-22222222','title':'다른 기준','owner':'b@example.com','state':'예정'}])
    def test_admin_and_main_owner_can_move_criteria_tasks(self):
        self.set_criteria()
        before=criteria.parse(self.docs['task']['text'])
        for user in (ADMIN,USER):self.assertTrue(kanban.card(user,self.docs['task'],True,PEOPLE)['canMove'])
        result=kanban.mutate(ADMIN,{**self.body,'status':'보류'},True)
        self.assertEqual(result['status'],'보류')
        self.assertEqual(criteria.parse(self.docs['task']['text']),before)
    def test_noncomplete_columns_preserve_mixed_criteria(self):
        self.set_criteria()
        self.docs['task']['text']=outline.apply_changes(self.docs['task']['text'],{'criterion_states':{'C-11111111':'완료'}})
        before=criteria.parse(self.docs['task']['text'])
        for status in ('미착수','진행 중','보류','지연'):
            doc=self.docs['task']
            result=kanban.mutate(USER,{**self.body,'requestId':status,'revision':doc['revision'],'updatedAt':doc['updatedAt'],'status':status},True)
            self.assertEqual(result['status'],status);self.assertEqual(result['progress'],50)
            self.assertEqual(criteria.parse(self.docs['task']['text']),before)
    def test_main_owner_can_bulk_complete_other_owners_then_reopen_without_reset(self):
        self.set_criteria()
        result=kanban.mutate(USER,{**self.body,'status':'완료'},True)
        self.assertEqual(result['status'],'완료');self.assertEqual(result['progress'],100)
        self.assertTrue(all(i['state']=='완료' for i in result['criteria']))
        self.assertIn('칸반에서 일괄 완료',self.docs['task']['text'])
        self.assertIn('다른 기준 (예정 → 완료)',self.docs['task']['text'])
        self.assertEqual(kanban.mutate(USER,{**self.body,'status':'완료'},True),result)
        self.assertEqual(len(self.writes),1)
        result=kanban.mutate(USER,{**self.body,'requestId':'reopen','revision':2,'updatedAt':'t2','status':'진행 중'},True)
        self.assertEqual(result['status'],'진행 중');self.assertEqual(result['progress'],100)
        self.assertTrue(all(i['state']=='완료' for i in result['criteria']))
        self.assertEqual(outline.normalize(copy.deepcopy(self.docs['task']))['text'],self.docs['task']['text'])
    def test_criterion_only_participant_cannot_move_or_bulk_complete(self):
        self.set_criteria()
        other={**USER,'sub':'b','email':'b@example.com'}
        self.assertFalse(kanban.card(other,self.docs['task'],True,PEOPLE)['canMove'])
        self.deny(403,user=other,status='완료')
        self.deny(403,can=False,status='완료')
        self.permission.side_effect=HTTPException(403,'revoked')
        self.deny(403,user=ADMIN,status='완료')
    def test_completed_to_not_started_resets_all_owners_and_survives_refresh(self):
        self.set_criteria()
        kanban.mutate(USER,{**self.body,'status':'완료'},True)
        self.docs['task']['text']=self.docs['task']['text'].replace('상태 관리: 칸반','')
        result=kanban.mutate(USER,{**self.body,'requestId':'reset','revision':2,'updatedAt':'t2','status':'미착수'},True)
        self.assertEqual(result['status'],'미착수');self.assertEqual(result['progress'],0)
        self.assertTrue(all(i['state']=='예정' for i in result['criteria']))
        self.assertIn('다른 기준 (완료 → 예정)',self.docs['task']['text'])
        self.assertEqual(domain.parse(self.docs['task']['text'])['status'],'미착수')
        self.assertEqual(outline.normalize(copy.deepcopy(self.docs['task']))['text'],self.docs['task']['text'])
    def test_removed_label_report_and_normalization_preserve_selected_state(self):
        self.set_criteria()
        kanban.mutate(USER,{**self.body,'status':'완료'},True)
        self.docs['task']['text']=self.docs['task']['text'].replace('상태 관리: 칸반','')
        result=kanban.mutate(USER,{**self.body,'requestId':'held','revision':2,'updatedAt':'t2','status':'보류'},True)
        self.assertEqual(result['status'],'보류');self.assertEqual(result['progress'],100)
        text=self.docs['task']['text'].replace('상태 관리: 칸반','')
        text=outline.apply_changes(text,{'criterion_states':{'C-11111111':'진행 중'}},'task')
        self.assertEqual(domain.parse(text)['status'],'보류')
        self.assertEqual(criteria.rollup(criteria.parse(text))['progress'],'50%')
        self.docs['task']['text']=text
        self.assertEqual(outline.normalize(copy.deepcopy(self.docs['task']))['text'],text)
    def test_auto_completed_card_resets_even_before_document_normalization(self):
        self.set_criteria()
        items=criteria.parse(self.docs['task']['text'])
        for item in items:item['state']='완료'
        self.docs['task']['text']=criteria.replace(self.docs['task']['text'],items)
        self.assertEqual(domain.parse(self.docs['task']['text'])['status'],'미착수')
        self.assertEqual(kanban.card(USER,self.docs['task'],True,PEOPLE)['status'],'완료')
        result=kanban.mutate(USER,{**self.body,'status':'미착수'},True)
        self.assertEqual(result['progress'],0)
        self.assertTrue(all(i['state']=='예정' for i in result['criteria']))
        self.assertIn('이전 상태: 완료 → 미착수',self.docs['task']['text'])
    def test_participant_and_readonly_cannot_reset_completed_task(self):
        self.set_criteria()
        self.docs['task']['text']=outline.apply_changes(self.docs['task']['text'],{'kanban_status':'완료'})
        self.deny(403,user={**USER,'sub':'b','email':'b@example.com'},status='미착수')
        self.deny(403,can=False,status='미착수')
    def test_criterion_owner_only_and_rollup(self):
        self.set_criteria()
        self.deny(403,status='',criterionId='C-22222222',criterionState='완료')
        result=kanban.mutate(USER,{**self.body,'status':'','criterionId':'C-11111111','criterionState':'완료'},True)
        self.assertEqual(result['progress'],50);self.assertEqual(result['status'],'진행 중')
        self.assertTrue(result['canMove']);self.assertFalse(result['criteria'][1]['canUpdate'])
    def test_checklist_edits_roll_status_both_ways_after_manual_selection(self):
        self.set_criteria()
        kanban.mutate(USER,self.body,True)
        self.assertTrue(task_status.manual(self.docs['task']['text'],'task'))
        for number,(criterion,state,status,progress) in enumerate([
            ('C-11111111','완료','진행 중',50),
            ('C-22222222','완료','완료',100),
            ('C-22222222','진행 중','진행 중',50),
            ('C-11111111','예정','진행 중',0),
            ('C-22222222','예정','미착수',0),
        ]):
            doc=self.docs['task']
            result=kanban.mutate(ADMIN,{**self.body,'requestId':'criterion-'+str(number),
                'revision':doc['revision'],'updatedAt':doc['updatedAt'],'status':'',
                'criterionId':criterion,'criterionState':state},True)
            self.assertEqual(result['status'],status)
            self.assertEqual(result['progress'],progress)
            self.assertEqual(domain.parse(self.docs['task']['text'])['status'],status)
            self.assertEqual(outline.normalize(copy.deepcopy(self.docs['task']))['text'],self.docs['task']['text'])
    def test_checklist_rollup_survives_removed_manual_label(self):
        self.set_criteria()
        completed=kanban.mutate(USER,{**self.body,'status':'완료'},True)
        self.docs['task']['text']=self.docs['task']['text'].replace(task_status.MANUAL,'')
        result=kanban.mutate(USER,{**self.body,'requestId':'unchecked','revision':completed['revision'],
            'updatedAt':completed['updatedAt'],'status':'','criterionId':'C-11111111','criterionState':'예정'},True)
        self.assertEqual(result['status'],'진행 중')
        self.assertEqual(result['progress'],50)
    def test_human_checklist_completion_and_reopening_update_parent_status(self):
        self.mock(human_tasks,'people',return_value=PEOPLE)
        self.mock(human_tasks,'eligible',return_value=True)
        self.mock(human_tasks,'validate_assignment',return_value=None)
        self.docs['task']['text']=('담당자: 직원 A (a@example.com)\n\n시작일: 2026-10-01\n\n마감일: 미정\n\n상태: 진행 중\n\n진행률: 0%\n\n상태 관리: 칸반\n\n'
            '## 업무 내용\n\n원본 내용\n\n## 완료 기준\n\n- [ ] 화면 구현 — 담당자: 직원 A (a@example.com)\n- [ ] 검수 완료 — 담당자: 직원 B (b@example.com)')
        items=criteria.parse(self.docs['task']['text'])
        for n,(index,state,status) in enumerate([(0,'완료','진행 중'),(1,'완료','완료'),(0,'예정','진행 중'),(1,'예정','미착수')]):
            doc=self.docs['task']
            result=kanban.mutate(ADMIN,{**self.body,'requestId':'human-'+str(n),'revision':doc['revision'],
                'updatedAt':doc['updatedAt'],'status':'','criterionId':items[index]['id'],'criterionState':state},True)
            self.assertEqual(result['status'],status)
            self.assertEqual(domain.parse(self.docs['task']['text'])['status'],status)
            self.assertIn('원본 내용',self.docs['task']['text'])
    def test_permission_revoked_on_receipt_retry(self):
        kanban.mutate(USER,self.body,True)
        self.permission.side_effect=HTTPException(403,'revoked')
        with self.assertRaises(HTTPException) as ex:kanban.mutate(USER,self.body,True)
        self.assertEqual(ex.exception.status_code,403);self.assertEqual(len(self.writes),1)

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        p=patch.object(store,'DB',self.temp.name+'/db');p.start();self.addCleanup(p.stop);store.init()
        p=patch.dict(os.environ,{'OUTLINE_KANBAN_ENABLED':'true','OUTLINE_WORKHUB_BRIDGE_SECRET':'kanban-test'});p.start();self.addCleanup(p.stop)
        p=patch.object(outline_bridge,'actor',return_value=USER);p.start();self.addCleanup(p.stop)
        p=patch.object(kanban,'query',return_value={'cards':[]});self.query=p.start();self.addCleanup(p.stop)
        self.client=TestClient(app)
    def request(self,signature=True,**extra):
        body={'collectionId':str(uuid.uuid4()),'parentDocumentId':str(uuid.uuid4()),
              'actor':{'outlineUserId':'a','outlineTeamId':'t'},**extra}
        raw=json.dumps(body).encode();path='/internal/outline-kanban/query';stamp=str(int(time.time()));nonce=str(uuid.uuid4())
        message='\n'.join(['POST',path,stamp,nonce,hashlib.sha256(raw).hexdigest()])
        signed=hmac.new(b'kanban-test',message.encode(),hashlib.sha256).hexdigest()
        return self.client.post(path,content=raw,headers={'Content-Type':'application/json','X-Workhub-Time':stamp,'X-Workhub-Nonce':nonce,'X-Workhub-Signature':signed if signature else 'invalid'})
    def test_unsigned_denied(self):self.assertEqual(self.request(signature=False).status_code,401);self.query.assert_not_called()
    def test_signed_and_no_store(self):
        response=self.request(grants=[{'id':str(uuid.uuid4()),'canUpdate':False}])
        self.assertEqual(response.status_code,200);self.assertEqual(response.headers['cache-control'],'no-store')
    def test_unknown_actor_fields_rejected(self):self.assertEqual(self.request(actor={'outlineUserId':'a','outlineTeamId':'t','admin':True}).status_code,422)
