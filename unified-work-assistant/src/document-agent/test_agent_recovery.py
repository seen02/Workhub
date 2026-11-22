"""Real Outline fault recovery for the new agent; run in container via stdin."""
import asyncio,json,os,uuid
from unittest.mock import patch
os.environ['DATA_DIR']='/app/data/agent-recovery-tests'
import app as core
from agent_tools import ToolRequest

execute=next(r.endpoint for r in core.app.routes if r.path=='/agent/execute')
real=core.outline

async def main():
    report=[]
    for mode in ('before_send','lost_response'):
        run=uuid.uuid4().hex[:8]
        calls=0
        async def fault(method,payload,read=False):
            nonlocal calls
            if method=='documents.create':
                calls+=1
                if calls==1:
                    if mode=='lost_response': await real(method,payload,read)
                    raise core.HTTPException(503,'시험용 응답 손실')
            return await real(method,payload,read)
        request=ToolRequest(tool='prepare_document',user_id='recovery-test',chat_id=run,message_id='1',arguments={
            'text':'네트워크 복구 시험. 검토 3건 진행 중.','preserve_original':True,
            'title':f'[에이전트 복구 {run}] {mode}','collection_name':'로컬 AI 테스트','parent_title':'[에이전트 검증] 문서함'})
        with patch.object(core,'outline',fault):
            first=await execute(request)
            assert first['status']=='succeeded' and first['verified'],first
            again=await execute(ToolRequest(tool='save_document',user_id='recovery-test',chat_id=run,message_id='2',arguments={'draft_id':'latest','reuse_last_destination':True}))
            assert again['duplicate'] and again['id']==first['id'],again
            assert calls==(2 if mode=='before_send' else 1),calls
        report.append({'case':mode,'passed':True,'create_calls':calls,'document_id':first['id']})
    (core.DATA/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

asyncio.run(main())
