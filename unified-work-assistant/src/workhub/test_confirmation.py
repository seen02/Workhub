import os,tempfile,unittest
from unittest.mock import patch
import httpx
from fastapi import HTTPException
from . import store,domain,outline,criteria,chat_ui

USER={'sub':'confirmation-user','email':'worker@example.com','admin':False}

class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        from .testing_acl import allow_fixture
        allow_fixture(self)
        self.folder=tempfile.TemporaryDirectory()
        self.db=patch.object(store,'DB',os.path.join(self.folder.name,'test.db'));self.db.start();store.init()
        text=domain.render({'project':'P','owner':USER['email'],'status':'미착수','progress':'0%'})
        text=criteria.replace(text,[{'id':'C-12345678','title':'화면 검증','owner':USER['email'],'state':'예정'}])
        text+='\n\n### 보고 기록\n\n```text\n이전 보고\n```\n\n\n### 보고 기록\n\n```text\n추가 보고\n```'
        self.doc={'id':'doc','title':'업무','collectionId':'project','url':'/doc/doc','text':text,'revision':1,'updatedAt':'before'}
        with patch.object(outline,'document',return_value=self.doc):
            self.p=outline.propose(USER,'doc',{'criterion_states':{'C-12345678':'완료'}},'report','완료했습니다.')
    def tearDown(self):self.db.stop();self.folder.cleanup()
    def source(self):return dict(self.doc)
    def save(self,name,body):
        self.doc.update(text=domain.saved_text_key(body['text']),revision=2,updatedAt='after')
    def test_blank_separator_normalization_is_success_with_receipt_and_no_second_write(self):
        with patch.object(outline,'document',side_effect=lambda _:self.source()),patch.object(outline,'api',side_effect=self.save) as api,patch.object(outline,'record'):
            result=outline.confirm(USER,self.p['id'])
            self.assertEqual(result['state'],'APPLIED');self.assertEqual(result['result']['progress'],'100%')
            self.assertEqual(result['result']['criteria_done'],1)
            self.assertEqual(outline.confirm(USER,self.p['id']),result);self.assertEqual(api.call_count,1)
    def test_response_lost_after_committing_recovers_without_rewriting(self):
        def save_timeout(name,body):self.save(name,body);raise httpx.ReadTimeout('timeout')
        with patch.object(outline,'document',side_effect=lambda _:self.source()),patch.object(outline,'api',side_effect=save_timeout) as api,patch.object(outline,'record'):
            self.assertEqual(outline.confirm(USER,self.p['id'])['state'],'APPLIED');self.assertEqual(api.call_count,1)
    def test_retry_of_attempted_normalized_write_recovers(self):
        with store.db() as c:c.execute('UPDATE proposals SET state=? WHERE id=?',('APPLYING',self.p['id']))
        self.save('documents.update',{'text':self.p['after']})
        with patch.object(outline,'document',side_effect=lambda _:self.source()),patch.object(outline,'api') as api,patch.object(outline,'record'):
            self.assertEqual(outline.confirm(USER,self.p['id'])['state'],'APPLIED');api.assert_not_called()
    def test_real_edit_before_confirmation_remains_conflict(self):
        self.doc.update(text=self.doc['text']+'\n새 메모',revision=2)
        with patch.object(outline,'document',side_effect=lambda _:self.source()),patch.object(outline,'api') as api:
            with self.assertRaises(HTTPException):outline.confirm(USER,self.p['id'])
            api.assert_not_called()
        self.assertEqual(outline.proposal(USER,self.p['id'])['state'],'CONFLICT')
    def test_changed_content_after_attempt_is_not_overwritten_or_cancelled(self):
        def different(name,body):self.save(name,body);self.doc['text']+='\n누군가 추가한 메모'
        with patch.object(outline,'document',side_effect=lambda _:self.source()),patch.object(outline,'api',side_effect=different) as api:
            for _ in range(2):
                with self.assertRaises(HTTPException):outline.confirm(USER,self.p['id'])
            self.assertEqual(api.call_count,1)
        self.assertEqual(outline.proposal(USER,self.p['id'])['state'],'APPLYING')
        with self.assertRaises(HTTPException):outline.cancel(USER,self.p['id'])
    def test_pending_equal_text_is_not_recovered_as_our_write(self):
        self.save('documents.update',{'text':self.p['after']})
        with patch.object(outline,'document',side_effect=lambda _:self.source()),patch.object(outline,'api') as api:
            with self.assertRaises(HTTPException):outline.confirm(USER,self.p['id'])
            api.assert_not_called()
    def test_fenced_evidence_and_task_notes_are_not_normalized(self):
        a='```text\n원문\n\n\n### 보고 기록\n```'
        self.assertFalse(domain.same_saved_text(a,a.replace('\n\n\n','\n\n')))
        a='업무 메모\n\n\n둘째 문단'
        self.assertFalse(domain.same_saved_text(a,a.replace('\n\n\n','\n\n')))
        self.assertFalse(domain.same_saved_text(self.p['after'],self.p['after'].replace('완료했습니다.','예정입니다.')))
    def test_template_paragraph_export_normalization(self):
        a='상태: 진행 중\n\n\n## 업무 내용\n\n업무\n\n\n## 완료 기준\n\n- [x] 구현 — 담당자: 홍길동\n\n## 진행 기록\n\n* **도움이 필요한 사항**: \n\n\n## 결과물 및 참고 링크'
        b=a.replace('\n\n\n','\n\n').replace('사항**: \n','사항**:\n')
        self.assertTrue(domain.same_saved_text(a,b))
        for old,new in [('[x]','[ ]'),('홍길동','김철수'),('업무\n','다른 업무\n')]:
            self.assertFalse(domain.same_saved_text(a,b.replace(old,new)))
        evidence='\n\n### 보고 기록\n\n```text\n보고\n\n\n원문 \n```'
        self.assertFalse(domain.same_saved_text(a+evidence,b+evidence.replace('\n\n\n','\n\n')))
        self.assertFalse(domain.same_saved_text(a+'\n강제 줄바꿈  \n다음',b+'\n강제 줄바꿈\n다음'))
    def test_outline_empty_hard_break_is_only_ignored_before_report_heading(self):
        self.assertTrue(domain.same_saved_text('```\n기록\n```\n\n\\\n\n### 보고 기록','```\n기록\n```\n\n### 보고 기록'))
        self.assertFalse(domain.same_saved_text('```text\n\\\n\n### 보고 기록\n```','```text\n\n### 보고 기록\n```'))
    def test_uncertain_report_has_recheck_not_cancel_button(self):
        actions=[a for row in chat_ui.confirmation('room',{**self.p,'state':'APPLYING'}) for a in row['actions']]
        self.assertEqual(actions[0]['text'],'반영 결과 다시 확인')
        self.assertNotIn('이 초안 취소',[a['text'] for a in actions])

if __name__=='__main__':unittest.main()
