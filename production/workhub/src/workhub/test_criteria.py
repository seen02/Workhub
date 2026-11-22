import os, tempfile, unittest
from datetime import datetime, timezone
from unittest.mock import patch
from fastapi import HTTPException
from . import criteria, domain, outline, store

ADMIN={'sub':'admin','email':'admin@example.com','admin':True}
ALICE={'sub':'alice','email':'alice@example.com','admin':False}
BOB={'sub':'bob','email':'bob@example.com','admin':False}

class CriteriaTests(unittest.TestCase):
    def setUp(self):
        from . import permissions
        for item in [patch.object(permissions,'document'),patch.object(permissions,'validate_owners')]:
            item.start();self.addCleanup(item.stop)
        self.items=criteria.validate([
            dict(id='C-11111111',title='요구사항 승인',owner=ALICE['email'],state='예정'),
            dict(id='C-22222222',title='화면 검증',owner=BOB['email'],state='진행 중'),
            dict(id='C-33333333',title='배포 확인',owner=BOB['email'],state='예정')])
        self.text=criteria.replace(domain.render(dict(project='P',owner=ALICE['email'],status='미착수',progress='0%'),'기존 메모 보존'),self.items)
        self.doc={'text':self.text,'title':'시연 업무','id':'doc','revision':1,'updatedAt':'now','collectionId':'p','url':'/doc/test','publishedAt':'now'}

    def test_rollup_counts_only_done(self):
        self.assertEqual(criteria.rollup(self.items),{'status':'진행 중','progress':'0%'})
        self.items[0]['state']='완료';self.assertEqual(criteria.rollup(self.items)['progress'],'33.3%')
        self.items[1]['state']='완료';self.assertEqual(criteria.rollup(self.items)['progress'],'66.7%')
        self.items[2]['state']='완료';self.assertEqual(criteria.rollup(self.items),{'status':'완료','progress':'100%'})

    def test_outline_native_check_and_uncheck(self):
        checked=self.text.replace('- [ ] C-11111111','- [x] C-11111111')
        self.assertEqual(criteria.parse(checked)[0]['state'],'완료')
        rewritten=criteria.replace(checked,criteria.parse(checked))
        unchecked=rewritten.replace('- [x] C-11111111','- [ ] C-11111111')
        self.assertEqual(criteria.parse(unchecked)[0]['state'],'예정')

    def test_report_preserves_unmentioned_items_and_notes(self):
        after=outline.apply_changes(self.text,{'criterion_states':{'C-11111111':'완료'}})
        self.assertEqual(criteria.parse(after)[1:],self.items[1:])
        self.assertIn('기존 메모 보존',after)
        self.assertEqual(domain.parse(after)['progress'],'33.3%')

    def test_historical_report_never_becomes_live_fields(self):
        history='\n\n### 보고 기록\n\n```text\n상태: 완료\n진행률: 100%\n## 완료 기준\n\n가짜 체크리스트\n```'
        text=self.text+history
        self.assertEqual(len(criteria.parse(text)),3)
        self.assertEqual(domain.parse(text)['progress'],'0%')
        after=outline.apply_changes(text,{'criterion_states':{'C-11111111':'완료'}})
        self.assertTrue(after.endswith(history))
        self.assertEqual(domain.parse(after)['progress'],'33.3%')

    def test_assignee_can_change_only_own_item(self):
        outline.authorize_changes(ALICE,self.doc,{'criterion_states':{'C-11111111':'완료'}})
        with self.assertRaises(HTTPException) as e:
            outline.authorize_changes(ALICE,self.doc,{'criterion_states':{'C-22222222':'완료'}})
        self.assertEqual(e.exception.status_code,403)

    def test_even_task_owner_cannot_reassign(self):
        with self.assertRaises(HTTPException):outline.authorize_changes(ALICE,self.doc,{'criteria':self.items})
        outline.authorize_changes(ADMIN,self.doc,{'criteria':self.items})

    def test_manual_percentage_cannot_bypass_checklist(self):
        with self.assertRaises(ValueError):outline.authorize_changes(ADMIN,self.doc,{'progress':'100%'})
        with self.assertRaises(ValueError):outline.authorize_changes(ADMIN,self.doc,{'status':'완료'})
        with self.assertRaises(ValueError):outline.authorize_changes(ALICE,self.doc,{'criterion_states':{'C-11111111':'완료'},'owner':ALICE['email']})

    def test_kanban_authorization_cannot_mix_bulk_completion_with_reassignment(self):
        outline.authorize_changes(ALICE,self.doc,{'kanban_status':'완료'})
        with self.assertRaises(ValueError):outline.authorize_changes(ALICE,self.doc,{'kanban_status':'완료','owner':BOB['email']})
        with self.assertRaises(HTTPException):outline.authorize_changes(BOB,self.doc,{'kanban_status':'완료'})
        with self.assertRaises(HTTPException):outline.authorize_changes(ALICE,self.doc,{'criterion_states':{'C-22222222':'완료'}})

    def test_plain_reports_update_progress_but_preserve_manual_state(self):
        text=domain.render(dict(project='P',owner=ALICE['email'],status='미착수',progress='20%'))
        held=outline.apply_changes(text,{'kanban_status':'보류'})
        after=outline.apply_changes(held,{'status':'진행 중','progress':'60%'})
        self.assertEqual(domain.parse(after)['status'],'보류')
        self.assertEqual(domain.parse(after)['progress'],'60%')

    def test_manual_legacy_summary_is_consistent_after_report_and_normalize(self):
        held=outline.apply_changes(self.text,{'kanban_status':'미착수'})
        after=outline.apply_changes(held,{'criterion_states':{i['id']:'완료' for i in self.items}})
        d={**self.doc,'text':after}
        with patch.object(outline,'api') as api,patch.object(outline,'project',return_value={'name':'P'}):
            self.assertEqual(outline.normalize(d),d);api.assert_not_called()
            self.assertEqual(outline.projected(d)['fields']['status'],'미착수')
        self.assertEqual(domain.parse(after)['progress'],'100%')

    def test_unknown_duplicate_and_malformed_items_fail(self):
        with self.assertRaises(ValueError):criteria.select(self.items,'C-00000000')
        with self.assertRaises(ValueError):criteria.validate([self.items[0],self.items[0]])
        with self.assertRaises(ValueError):criteria.parse(self.text.replace('담당자: alice@example.com','담당자 삭제'))
        with self.assertRaises(ValueError):criteria.parse(self.text+'\n\n## 완료 기준\n\ninvalid')



    def test_collection_scope_denies_other_document(self):
        with patch.object(outline,'api',return_value=self.doc),patch.object(outline,'projects',return_value=[{'id':'different'}]):
            with self.assertRaises(HTTPException) as e:outline.document('doc')
        self.assertEqual(e.exception.status_code,404)



if __name__=='__main__':unittest.main()
