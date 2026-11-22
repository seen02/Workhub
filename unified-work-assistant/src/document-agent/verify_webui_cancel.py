"""Exercise the real WebUI Stop endpoint, including visible partial result persistence."""
import json,time
from test_agent_chat import chat,call,session,ROOT
from verify_rag_live import agent,api

for _ in range(150):
    try:
        if agent.get('/health',timeout=2).status_code==200:break
    except Exception:pass
    time.sleep(.2)

receipt=chat('로컬 AI 테스트 컬렉션의 문서를 모두 읽고 정리해줘.',title='[RAG 검증] 실제 중지 버튼 경로',wait=False)
cid=receipt['chat_id'];scope=session['id']+':'+cid;eid=None;start=time.monotonic()
while time.monotonic()-start<45:
    events=agent.get('/diagnostics').json()['events']
    matching=[e for e in events if e['scope']==scope]
    if matching:
        eid=matching[0]['id']
        payload={'tool':'result','user_id':session['id'],'chat_id':cid,'arguments':{'event_id':eid}}
        partial=api(agent,'/agent/result',payload)
        if partial.get('read_count',0)>=1:break
    time.sleep(.05)
assert eid and partial.get('read_count',0)>=1,partial if eid else 'No backend task'
call('POST','/api/tasks/chat/'+cid+'/stop')
for _ in range(100):
    final=api(agent,'/agent/result',payload)
    if final['status']=='cancelled':break
    time.sleep(.05)
assert final['status']=='cancelled',final['status']
time.sleep(1)
message=call('GET','/api/v1/chats/'+cid)['chat']['history']['messages'][receipt['message_id']]
(ROOT/'data/rag-webui-cancel-debug.json').write_text(json.dumps({'receipt':receipt,'final':final,'message':message},ensure_ascii=False,indent=2))
assert final['display'] in message.get('content',''),'Cancelled checkpoint was not saved in the WebUI message'
result={'chat_id':cid,'event_id':eid,'status':final['status'],'read_count':final['read_count'],
        'remaining':len(final['pending_documents']),'visible_partial_preserved':True,'seconds':round(time.monotonic()-start,3)}
(ROOT/'data/rag-webui-cancel.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
