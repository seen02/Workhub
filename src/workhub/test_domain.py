import unittest
from .domain import render,parse,patch_text,statistics
class DomainTests(unittest.TestCase):
 def test_old_documents_accept_missing_start_and_patch_preserves_report(self):
  text=render(self.fields(),'기존 메모').replace('시작일: 미정\n\n','')+'\n\n### 보고 기록\n기존 보고 내용'
  self.assertEqual(parse(text)['start'],'미정')
  updated=patch_text(text,{'start':'2026-09-20','due':'2026-10-02'})
  self.assertEqual(parse(updated)['start'],'2026-09-20')
  self.assertIn('기존 메모',updated)
  self.assertTrue(updated.endswith('### 보고 기록\n기존 보고 내용'))
  self.assertEqual(updated.count('시작일:'),1)
 def test_period_validation_and_clear(self):
  with self.assertRaises(ValueError):render({**self.fields(),'start':'2026-10-01'})
  with self.assertRaises(ValueError):render({**self.fields(),'start':'2026-02-30'})
  text=render({**self.fields(),'start':'2026-09-30'})
  self.assertEqual(parse(patch_text(text,{'start':''}))['start'],'미정')
 def test_report_progress_preserves_planned_start(self):
  text=render({**self.fields(),'start':'2026-09-20'})
  self.assertEqual(parse(patch_text(text,{'progress':'50%'}))['start'],'2026-09-20')
 def fields(self):return dict(project='P',owner='user@example.com',due='2026-09-30',status='진행 중',progress='미기재',blocker='없음',next='검증',result='없음')
 def test_unknown_progress_is_not_inferred(self):
  f=self.fields();f['status']='완료';self.assertEqual(parse(render(f))['progress'],'미기재')
 def test_patch_preserves_notes(self):
  text=render(self.fields(),'기존 메모\n다음 줄');changed=patch_text(text,{'progress':'40%'})
  self.assertTrue(changed.endswith('기존 메모\n다음 줄'));self.assertEqual(parse(changed)['progress'],'40%')
 def test_duplicate_fields_rejected(self):
  with self.assertRaises(ValueError):parse(render(self.fields())+'\n상태: 완료')
 def test_progress_out_of_range(self):
  with self.assertRaises(ValueError):render({**self.fields(),'progress':'100.5%'})
 def test_completion_is_task_count(self):
  ts=[{'fields':self.fields()},{'fields':{**self.fields(),'status':'완료','progress':'미기재'}},{'fields':{},'error':'bad'}]
  s=statistics(ts,'2026-10-01');self.assertEqual(s['completion_rate'],50);self.assertEqual(s['overdue'],1);self.assertEqual(s['invalid'],1)
if __name__=='__main__':unittest.main()
