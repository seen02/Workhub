"""Regression for observed false 'saved' model response. No services needed."""
import asyncio,json,unittest
from webui_receipt import Filter
class ReceiptTest(unittest.TestCase):
    def test_research_dispatch_does_not_feed_catalog_or_history_to_router(self):
        from unittest.mock import patch
        calls=[]
        class Bridge:
            class Valves:
                def __init__(self,**kwargs):pass
            async def _run(self,tool,args,*_):
                calls.append((tool,args))
                return json.dumps({'status':'succeeded','event_id':'e','research_id':'r','fetch_result':True})
        prompt='‘로컬 AI 테스트’ 컬렉션에서 간단검토0916 관련 문서를 찾아 현재 상태와 다음 할 일을 짧게 정리해줘. 읽은 문서 수와 출처도 알려줘.'
        f=Filter()
        async def context(*args):return {}
        f.backend=context
        b={'model':'outline-assistant','tool_ids':['outline_read','outline_write'], 'messages':[
            {'role':'system','content':'old rules '*2000},{'role':'assistant','content':'목록 '*10000}, {'role':'user','content':prompt}]}
        meta={'chat_id':'c','message_id':'m'}
        with patch('webui_receipt.Tools',Bridge,create=True):
            out=asyncio.run(f.inlet(b,__user__={'id':'u'},__metadata__=meta))
        self.assertEqual(calls,[('read_request',{'request':prompt})])
        self.assertEqual(out['tool_ids'],[])
        self.assertLess(len(json.dumps(out['messages'],ensure_ascii=False)),300)
        self.assertEqual(meta['outline_workflow_result']['event_id'],'e')

    def test_catalog_display_restored_from_scoped_receipt(self):
        f=Filter();display='### 문서함\n\n'+'- 긴 목록\n'*2000
        async def result(*args):return {'status':'succeeded','display':display,'collections':[]}
        f.backend=result
        b={'model':'outline-assistant','messages':[{'role':'assistant','content':'임시'}]}
        out=asyncio.run(f.outlet(b,__metadata__={'outline_workflow_result':{'fetch_result':True,'event_id':'e'}}))
        self.assertEqual(out['messages'][-1]['content'],display)

    def test_write_request_dispatches_once_without_router_tools(self):
        from unittest.mock import patch
        calls=[]
        class Bridge:
            class Valves:
                def __init__(self,**kwargs):pass
            async def manage_outline_document(self,**kwargs):
                calls.append(kwargs)
                return json.dumps({'status':'succeeded','event_id':'e','workflow_id':'w','fetch_result':True})
        f=Filter()
        async def context(*args):return {}
        f.backend=context
        meta={'chat_id':'c','message_id':'m'}
        b={'model':'outline-assistant','tool_ids':['outline_read','outline_write'], 'files':[{'id':'f'}],
           'messages':[{'role':'user','content':'첨부한 회의록을 미리보기로 보여줘. 저장하지 마.'}]}
        with patch('webui_receipt.Tools',Bridge,create=True):
            out=asyncio.run(f.inlet(b,__user__={'id':'u'},__metadata__=meta))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['__files__'],[{'id':'f'}])
        self.assertEqual(out['tool_ids'],[]);self.assertEqual(meta['outline_workflow_result']['event_id'],'e')

    def test_direct_workflow_receipt_restores_failed_draft(self):
        f=Filter()
        async def result(*args):return {'status':'failed','workflow_id':'w','display':'검증 실패 초안\n99시 발표'}
        f.backend=result
        receipt={'status':'failed','event_id':'e','fetch_result':True}
        b={'model':'outline-assistant','messages':[{'role':'assistant','content':'임시 완료 답변'}]}
        out=asyncio.run(f.outlet(b,__metadata__={'outline_workflow_result':receipt}))
        self.assertIn('99시 발표',out['messages'][-1]['content'])
        self.assertEqual(out['messages'][-1]['outline_workflow_result'],receipt)

    def render(self,result):
        text='저장 완료! 잘못된 링크'
        body={'model':'outline-assistant','messages':[{'role':'assistant','content':text,'output':[
          {'type':'function_call_output','output':[{'type':'input_text','text':json.dumps({'event_id':'test',**result})}]},
          {'type':'message','content':[{'type':'output_text','text':text}]}]}]}
        return asyncio.run(Filter().outlet(body))['messages'][-1]
    def test_unsaved_draft_overrides_claim(self):
        m=self.render({'status':'succeeded','draft_id':'draft','title':'초안','markdown':'원문 기반 본문','saved':False})
        self.assertIn('아직 저장하지 않았습니다',m['content']);self.assertNotIn('잘못된 링크',str(m));self.assertIn('원문 기반 본문',m['content'])
    def test_only_verified_save_shows_link(self):
        m=self.render({'status':'succeeded','verified':True,'url':'http://localhost/doc/test','title':'저장본'})
        self.assertIn('저장·읽기 검증 완료',m['content']);self.assertIn('http://localhost/doc/test',m['content'])
    def test_failure_is_not_completion(self):
        m=self.render({'status':'failed','error':'상위 문서 중복'})
        self.assertIn('완료하지 못했습니다',m['content']);self.assertNotIn('잘못된 링크',str(m))

    def test_validation_failure_keeps_candidate_and_issues(self):
        candidate='13시 로컬 모델 생성 완료.\n15시 모델 테스트 진행 중.\n17시 발표 예정.'
        m=self.render({'status':'failed','error':{'message':'검증 실패','candidate':candidate,'issues':['오타 교정 재확인'],'missing_numbers':['15'],'extra_numbers':['16']}})
        self.assertIn(candidate,m['content']);self.assertIn('저장하지 않았습니다',m['content'])
        self.assertIn('오타 교정 재확인',m['content']);self.assertIn('누락된 숫자: 15',m['content'])
        self.assertIn('추가된 숫자: 16',m['content']);self.assertNotIn('잘못된 링크',str(m))
        self.assertEqual(m['output'][-1]['content'][0]['text'],m['content'])

    def test_partial_candidate_discloses_unprocessed_parts(self):
        m=self.render({'status':'failed','error':{'candidate':'첫 부분\n둘째 부분','partial':True,'processed_parts':2,'total_parts':3}})
        self.assertIn('첫 부분',m['content']);self.assertIn('전체 3부분 중 2부분',m['content'])

    def test_failed_revision_is_not_hidden_by_earlier_successful_draft(self):
        results=[{'status':'succeeded','draft_id':'old','title':'이전 초안','markdown':'이전 본문'},
                 {'status':'failed','error':{'candidate':'수정한 새 본문','issues':['수치 확인 필요']}}]
        b={'model':'outline-assistant','messages':[{'role':'assistant','content':'임시 답변','output':[
            {'type':'function_call_output','output':[{'text':json.dumps(r)}]} for r in results]}]}
        content=asyncio.run(Filter().outlet(b))['messages'][-1]['content']
        self.assertIn('수정한 새 본문',content);self.assertIn('수치 확인 필요',content)
    def test_document_revision_does_not_select_attachment_reader(self):
        b={'model':'outline-assistant','tool_ids':['outline_read','outline_write','outline_files','outline_edit'],
           'messages':[{'role':'user','content':'Outline 문서 ID "test-id"를 읽고 첨부 기능 상태만 완료로 수정해줘.'}]}
        result=asyncio.run(Filter().inlet(b))
        self.assertEqual(result['tool_ids'],['outline_edit'])
if __name__=='__main__':unittest.main()
