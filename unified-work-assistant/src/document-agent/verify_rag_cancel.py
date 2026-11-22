"""Live read-only cancellation, durable checkpoint and resume smoke test."""
import json
import time
import uuid
from verify_rag_live import agent,api,ROOT

scope={'tool':'research_documents','user_id':'rag-cancel','chat_id':str(uuid.uuid4()),
       'arguments':{'topic':'','mode':'all','collection_name':'로컬 AI 테스트'}}
receipt=api(agent,'/agent/submit',scope)
scoped={**scope,'arguments':{'event_id':receipt['event_id']}}
start=time.monotonic()
while time.monotonic()-start<30:
    partial=api(agent,'/agent/result',scoped)
    if partial.get('read_count',0)>=1:break
    time.sleep(.05)
assert partial.get('read_count',0)>=1,partial
api(agent,'/agent/cancel',scoped)
for _ in range(100):
    final=api(agent,'/agent/result',scoped)
    if final['status']=='cancelled':break
    time.sleep(.05)
assert final['status']=='cancelled' and final.get('read_count',0)>=1,final
assert final['pending_documents'],final
time.sleep(1)
again=api(agent,'/agent/result',scoped)
assert again['read_count']==final['read_count'],'Work continued after cancellation'
resume=api(agent,'/agent/execute',{**scope,'tool':'read_request','arguments':{'request':'조사 이어서'}})
assert resume['status'] in ('succeeded','partial') and resume['read_count']>final['read_count'],resume
assert resume['research_id']==final['research_id']
result={'event_id':receipt['event_id'],'status':final['status'],'read_at_cancel':final['read_count'],
        'remaining_at_cancel':len(final['pending_documents']),'read_after_resume':resume['read_count'],
        'remaining_after_resume':len(resume['pending_documents']),'seconds':round(time.monotonic()-start,3)}
(ROOT/'data/rag-live-cancel.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
