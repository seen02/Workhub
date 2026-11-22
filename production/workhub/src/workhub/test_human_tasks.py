import os,tempfile,unittest
from unittest.mock import patch
from fastapi import HTTPException
from . import human_tasks as h,domain,criteria,outline,store,permissions

TEXT='''담당자: 홍길동

시작일: 2026-09-29

마감일: 2026-10-08

상태: 미착수

## 업무 내용

원본 메모와 [자료](https://example.test)는 보존합니다.

## 완료 기준

- [ ] 로그인 구현 — 담당자: 홍길동
- [ ] 오류 검수 — 담당자: 김철수

## 진행 기록

### 2026-09-29

- 진행한 내용: 시작

## 결과물 및 참고 자료

- 문서 링크
'''
PEOPLE=[{'id':'u1','email':'hong@example.com','name':'홍길동','label':'홍길동'}, {'id':'u2','email':'kim@example.com','name':'김철수','label':'김철수'}]

class HumanTaskTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        p=patch.object(store,'DB',os.path.join(self.folder.name,'test.db'));p.start();self.addCleanup(p.stop);store.init()
        p=patch.object(h,'people',return_value=PEOPLE);p.start();self.addCleanup(p.stop)
    def test_template_fields_and_names(self):
        self.assertEqual(domain.parse(TEXT)['owner'],'hong@example.com');self.assertEqual(len(criteria.parse(TEXT)),2)
    def test_bold_header(self):self.assertEqual(domain.parse(TEXT.replace('담당자: 홍길동','**담당자:** 홍길동'))['owner'],'hong@example.com')
    def test_bad_placeholder_date(self):
        with self.assertRaisesRegex(ValueError,'실제 날짜'):domain.parse(TEXT.replace('2026-09-29','YYYY-MM-DD'))
    def test_unknown_and_ambiguous_names(self):
        with self.assertRaises(ValueError):h.resolve('홍길동 진행 기록')
        with patch.object(h,'people',return_value=PEOPLE+[{'email':'another@example.com','name':'홍길동','label':'홍길동'}]):
            with self.assertRaises(ValueError):h.resolve('홍길동')
            self.assertEqual(h.resolve('홍길동 (hong@example.com)'),'hong@example.com')
    def test_ids_survive_check_and_order(self):
        before=criteria.parse(TEXT);after=criteria.parse(TEXT.replace('- [ ] 로그인 구현','- [x] 로그인 구현'))
        self.assertEqual(before[0]['id'],after[0]['id']);self.assertEqual(after[0]['state'],'완료')
        self.assertEqual({i['id'] for i in before},{i['id'] for i in criteria.parse(criteria.replace(TEXT,list(reversed(before))))})
    def test_rename_is_new_identity(self):self.assertNotEqual(criteria.parse(TEXT)[0]['id'],criteria.parse(TEXT.replace('로그인 구현','로그인 검증'))[0]['id'])
    def test_report_writes_human_format_and_preserves_notes(self):
        item=criteria.parse(TEXT)[0];after=outline.apply_changes(TEXT,{'criterion_states':{item['id']:'완료'}})
        self.assertIn('마감일: 2026-10-08\n\n상태:',after);self.assertNotIn('C-',after);self.assertIn('## 진행 기록',after);self.assertIn('원본 메모와 [자료]',after)
        self.assertEqual(criteria.rollup(criteria.parse(after))['progress'],'50%')
    def test_in_progress_and_uncheck(self):
        item=criteria.parse(TEXT)[0];after=outline.apply_changes(TEXT,{'criterion_states':{item['id']:'진행 중'}})
        self.assertIn('상태: 진행 중',after);self.assertEqual(criteria.parse(after)[0]['state'],'진행 중')
        after=after.replace('[ ] 로그인','[x] 로그인');self.assertEqual(criteria.parse(after)[0]['state'],'완료')
        after=after.replace('[x] 로그인','[ ] 로그인');self.assertEqual(criteria.parse(after)[0]['state'],'진행 중')
    def test_existing_projection_migrates_mode_after_label_is_deleted(self):
        from . import task_status
        text=outline.apply_changes(TEXT,{'kanban_status':'진행 중'})
        with store.db() as connection:
            connection.execute('INSERT INTO tasks VALUES(?,?,?,1)',('d',store.dump({'text':text}),'old'))
        deleted=text.replace('상태 관리: 칸반','')
        self.assertTrue(task_status.manual(deleted,'d'))
        task_status.remember('d',deleted)
        with store.db() as connection:connection.execute('DELETE FROM tasks WHERE id=?',('d',))
        self.assertTrue(task_status.manual(deleted,'d'))
        self.assertFalse(task_status.manual(deleted,'other'))
    def test_manual_checkbox_edit_recalculates_progress_without_changing_status(self):
        held=outline.apply_changes(TEXT,{'kanban_status':'지연'}).replace('- [ ] 로그인','- [x] 로그인')
        d={'id':'d','text':held,'collectionId':'p','revision':1}
        with patch.object(h,'eligible',return_value=True),patch.object(h,'validate_assignment'),patch.object(outline,'api',return_value=d) as api:
            outline.normalize(d)
            written=api.call_args_list[0].args[1]['text']
            self.assertEqual(domain.parse(written)['status'],'지연')
            self.assertEqual(domain.parse(written)['progress'],'50%')
    def test_history_cannot_enable_manual_state(self):
        from . import task_status
        self.assertFalse(task_status.manual(TEXT+'\n\n### 보고 기록\n\n상태 관리: 칸반'))
        self.assertFalse(task_status.manual(TEXT.replace('원본 메모와','상태 관리: 칸반\n원본 메모와')))
    def test_duplicate_titles_rejected(self):
        with self.assertRaises(ValueError):criteria.parse(TEXT.replace('오류 검수','로그인 구현'))
    def test_reports_do_not_become_live_fields(self):
        text=TEXT+'\n\n### 보고 기록\n담당자: 다른 사람\n## 완료 기준\n이전 기록'
        self.assertEqual(len(criteria.parse(text)),2);self.assertEqual(domain.parse(text)['owner'],'hong@example.com')
        self.assertTrue(domain.patch_text(text,{'due':'2026-10-10'}).endswith('이전 기록'))
    def test_template_source_is_not_mutated_on_read(self):
        d={'text':TEXT,'collectionId':'p'}
        with patch.object(h,'eligible',return_value=True),patch.object(h,'validate_assignment'),patch.object(outline,'api') as api:
            self.assertEqual(outline.normalize(d),d);api.assert_not_called()
    def test_folder_and_publication_required(self):
        d={'id':'d','collectionId':'p','parentDocumentId':'parent','publishedAt':'now'}
        parent={'id':'parent','collectionId':'p','title':'업무 목록','publishedAt':'now'}
        with patch.object(outline,'api',return_value=parent):
            self.assertTrue(h.eligible(d));self.assertFalse(h.eligible({**d,'publishedAt':None}));self.assertFalse(h.eligible({**d,'parentDocumentId':None}))
            self.assertFalse(h.eligible({**d,'collectionId':'other'}))
    def test_direct_completion_updates_only_visible_status(self):
        text=TEXT.replace('- [ ]','- [x]');d={'id':'d','text':text,'collectionId':'p','revision':1}
        with patch.object(h,'eligible',return_value=True),patch.object(h,'validate_assignment'),patch.object(outline,'api',return_value=d) as api:
            outline.normalize(d)
            written=api.call_args_list[0].args[1]['text']
            self.assertIn('상태: 완료',written);self.assertNotIn('C-',written)
            self.assertEqual(written,text.replace('상태: 미착수','상태: 완료'))
    def test_nonmember_is_rejected(self):
        with patch.object(permissions,'collection_people',return_value=PEOPLE[:1]):
            with self.assertRaises(ValueError):h.validate_assignment({'collectionId':'p'},domain.parse(TEXT),criteria.parse(TEXT))
    def test_error_is_visible_instead_of_silent_drop(self):
        d={'id':'d','collectionId':'p','title':'업무','url':'/doc/d','updatedAt':'now','text':TEXT.replace('홍길동','없는사람')}
        with patch.object(h,'eligible',return_value=True),patch.object(outline,'project',return_value={'name':'프로젝트'}):
            self.assertIn('담당자',outline.projected(d)['error'])
    def test_no_project_change_or_arbitrary_template_capture(self):
        self.assertFalse(h.is_human('회의록\n## 완료 기준\n- [ ] 메모'))
        with patch.object(h,'eligible',return_value=False):self.assertIsNone(outline.projected({'text':TEXT}))
