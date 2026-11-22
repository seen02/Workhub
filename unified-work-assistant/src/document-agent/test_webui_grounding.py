"""Regression for observed router omissions; no running model needed."""
import asyncio
import unittest
from pathlib import Path

namespace={}
exec('class Tools:\n'+Path(__file__).with_name('webui_write.py').read_text(encoding='utf-8'),namespace)

class GroundingTest(unittest.TestCase):
    def run_tool(self,method,request,**kwargs):
        tool=namespace['Tools']()
        async def capture(name,args,*_): return name,args
        tool._run=capture
        return asyncio.run(getattr(tool,method)(__messages__=[{'role':'user','content':request}],**kwargs))

    def test_original_source_and_no_save_override_router(self):
        name,a=self.run_tool('prepare_outline_draft','아직 저장하지 마.\n메모 원문: 김민수 담당. 13시 테스트 진행 중.',text='테스트 완료',preserve_original=True,collection_name='잘못된 위치',template_name='가짜')
        self.assertIn('김민수',a['text'])
        self.assertIn('진행 중',a['text'])
        self.assertFalse(a['preserve_original'])
        self.assertEqual(a['collection_name'],'')
        self.assertEqual(a['template_name'],'')

    def test_edit_reads_persisted_draft(self):
        name,a=self.run_tool('prepare_outline_draft','방금 초안의 제목을 "업무 보고"로 바꾸고 다음 계획을 맨 위로 옮겨줘. 아직 저장하지 마.',text='모델이 줄여서 전달한 내용')
        self.assertEqual(a['text'],'')
        self.assertEqual(a['title'],'업무 보고')
        self.assertIn('다음 계획',a['instruction'])

    def test_same_location_uses_persisted_destination(self):
        name,a=self.run_tool('save_outline_draft','방금 초안을 같은 위치에 다시 저장해줘.',parent_title='모델이 잘못 추정한 위치',draft_id='가짜')
        self.assertTrue(a['reuse_last_destination'])
        self.assertEqual(a['draft_id'],'latest')

    def test_unquoted_parent_is_preserved_when_model_omits_it(self):
        name,a=self.run_tool('save_outline_draft','시연 결과 아래에 방금 초안을 저장해줘.')
        self.assertEqual(a['parent_title'],'시연 결과')

    def test_template_name_not_shortened_by_router(self):
        name,a=self.run_tool('prepare_outline_draft','이 메모를 주간업무 보고 양식에 맞춰 정리해줘. 아직 저장하지 마.\n메모: 진행 중.',template_name='주간업무보고')
        self.assertEqual(a['template_name'],'주간업무 보고 양식')

    def test_original_content_modifier_is_not_part_of_destination(self):
        name,a=self.run_tool('prepare_outline_draft','첨부한 회의록을 원문 내용 그대로 시연 결과 아래에 넣어줘.',file_id='file')
        self.assertEqual(a['parent_title'],'시연 결과')
        self.assertTrue(a['preserve_original'])
        name,a=self.run_tool('save_outline_draft','방금 초안을 시연 결과 아래에 넣어줘.')
        self.assertEqual(a['parent_title'],'시연 결과')

if __name__=='__main__': unittest.main()
