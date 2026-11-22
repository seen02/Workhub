"""Check persisted WebUI content against its backend result and save identity."""
import json,sqlite3
from pathlib import Path

root=Path(__file__).parent
user=json.loads((root/'data/webui-session.json').read_text())['id']
with sqlite3.connect('file:'+str(root/'data/agent.sqlite3')+'?mode=ro',uri=True) as db:
    verified=[];saved_ids=[]
    for filename in ('rag-live-webui.json','rag-live-webui-read.json'):
        for record in json.loads((root/'data'/filename).read_text()):
            rows=db.execute('SELECT id,args,result,status FROM events WHERE scope=? ORDER BY started DESC',(user+':'+record['chat_id'],)).fetchall()
            matching=[row for row in rows if json.loads(row[1]).get('request')==record['prompt']]
            assert matching,'No scoped backend event'
            row=matching[0];result=json.loads(row[2])
            assert record['result']['content']==result['display'],'Server result was changed or lost in WebUI'
            if result.get('verified'):saved_ids.append(result['id'])
            verified.append({'file':filename,'event_id':row[0],'status':row[3]})
    assert len(saved_ids)==2 and len(set(saved_ids))==1,'Save retry changed the document identity'
report={'server_webui_exact_matches':len(verified),'same_saved_document_on_retry':True,'events':verified}
(root/'data/rag-result-contract.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
