"""Common completion reports retain scope and live authorization."""
import asyncio,unittest
from unittest.mock import AsyncMock,patch
from fastapi import HTTPException
from . import report_parser as parser,ai_runtime

PROJECTS=[{'id':'sat','name':'위성영상 생성'},{'id':'other','name':'의사소통 도구 선정'}]
TASKS=[{'id':'sat-doc','project_id':'sat','collectionId':'sat','collectionName':'위성영상 생성','title':'자료 정리','text':'',
        'criteria':[{'id':'C-1','title':'서류 정리'},{'id':'C-2','title':'이미지 정리'},{'id':'C-3','title':'PPT 정리'}]},
       {'id':'other-doc','project_id':'other','collectionId':'other','collectionName':'의사소통 도구 선정','title':'자료 정리','text':'',
        'criteria':[{'id':'C-1','title':'서류 정리'}]}]
RAW='위성 영상 생성 프로젝트의 자료 정리 다 완료했어.'

class ReportLatencyTests(unittest.TestCase):
    def test_actual_whole_task_report_keeps_project_and_all_live_criteria(self):
        with patch.object(parser,'inventory',return_value=(PROJECTS,TASKS)),patch.object(parser,'resolve_items') as resolve, \
             patch.object(parser.search,'agent') as rag,patch.object(parser,'extract_scoped',AsyncMock()) as ai:
            groups,mode=parser.plan({},RAW)
        self.assertEqual(mode,'literal');self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['task_id'],'sat-doc')
        self.assertEqual([(i['criterion_id'],i['state']) for i in groups[0]['items']],[('C-1','완료'),('C-2','완료'),('C-3','완료')])
        resolve.assert_called_once();rag.assert_not_called();ai.assert_not_awaited()
    def test_whole_assertion_variants_and_invalid_claims(self):
        for body in ['다 완료했어','전부 끝냈어','모두 마쳤습니다','완료 기준은 모두 완료','다 했어']:
            self.assertEqual(len(parser.literal_task_items(body,TASKS[0])),3,body)
        for body in ['완료','다 완료할 예정','다 완료 안 했어','전부 완료로 해줘','모두 끝났는지 확인해줘',
                     '다 완료했어 담당자는 김철수','다 완료했어 PPT 정리는 진행 중','일부 완료했어']:
            self.assertIsNone(parser.literal_task_items(body,TASKS[0]),body)
        self.assertIsNone(parser.whole_task_items('다 완료',dict(TASKS[0],criteria=[])))
        self.assertIsNone(parser.whole_task_items('다 완료',dict(TASKS[0],criteria=[TASKS[0]['criteria'][0]]*2)))
    def test_whole_completion_checks_every_item_owner_and_document_again(self):
        doc={'text':'live','revision':2,'updatedAt':'now','url':'/doc'}
        authorize=iter([None,HTTPException(403,'다른 담당자의 기준입니다.')])
        def check(*a,**kw):
            value=next(authorize)
            if value:raise value
        with patch.object(parser,'inventory',return_value=(PROJECTS,TASKS)),patch.object(parser.outline,'document',return_value=doc) as read, \
             patch.object(parser.outline,'can_report'),patch.object(parser.criteria,'parse',return_value=TASKS[0]['criteria']), \
             patch.object(parser.outline,'authorize_changes',side_effect=check) as auth:
            groups,_=parser.plan({},RAW)
        read.assert_called_once_with('sat-doc',{},normalize_fields=False)
        self.assertEqual(auth.call_count,2);self.assertEqual(groups[0]['kind'],'unresolved')
        self.assertIn('담당자',groups[0]['issue'])
    def test_whole_completion_does_not_accept_removed_criterion(self):
        with patch.object(parser,'inventory',return_value=(PROJECTS,TASKS)), \
             patch.object(parser.outline,'document',return_value={'text':'live'}),patch.object(parser.outline,'can_report'), \
             patch.object(parser.criteria,'parse',return_value=TASKS[0]['criteria'][1:]):
            groups,_=parser.plan({},RAW)
        self.assertEqual(groups[0]['kind'],'unresolved')
    def test_colloquial_completion_and_ongoing_status_consume_the_entire_report(self):
        raw='위성 영상 생성 프로젝트 자료 정리는 이미지 정리를 마무리했고 PPT 정리는 작업 중이야.'
        result=parser.extract_literal(raw,PROJECTS,TASKS)
        self.assertEqual([(i.criterion_id,i.state) for i in result.groups[0].items],[('C-2','완료'),('C-3','진행 중')])
        self.assertEqual(result.groups[0].task_id,'sat-doc')
        for body in ['이미지 정리는 마무리할 예정','이미지 정리는 마무리 안 했어',
                     '이미지 정리를 마무리했고 담당자는 김철수','PPT 정리는 작업 중인지 모르겠어']:
            self.assertIsNone(parser.literal_task_items(body,TASKS[0]),body)
    def test_report_model_stays_warm_and_explicit_keepalive_wins(self):
        async def run():
            with patch.object(ai_runtime.BaseProvider,'_post',AsyncMock(return_value='ok')) as post:
                body={'model':'test'}
                provider=ai_runtime.DraftProvider()
                self.assertEqual(await provider._post('/api/chat',body),'ok')
                self.assertEqual(post.call_args.args[1]['keep_alive'],'30m')
                self.assertNotIn('keep_alive',body)
                await provider._post('/api/generate',dict(body,keep_alive=0))
                self.assertEqual(post.call_args.args[1]['keep_alive'],0)
        asyncio.run(run())

if __name__=='__main__':unittest.main()
