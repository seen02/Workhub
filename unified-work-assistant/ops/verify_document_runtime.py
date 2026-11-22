"""Read-only functional checks inside the migrated document-agent container."""
import json
import os
import time
import urllib.request
from pathlib import Path

def request(url,body=None,token=None,timeout=180):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    data=json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=headers),timeout=timeout) as r:
        return json.load(r)
base='http://127.0.0.1:8000'
agent=os.environ['AGENT_TOKEN'];outline=os.environ['OUTLINE_API_KEY']
cols=request(os.environ['OUTLINE_URL']+'/collections.list',{'limit':100},outline)
status=request(base+'/rag/status',token=agent)
model=request('http://ollama:11434/api/tags')
result={'outline_api':cols.get('ok',False),'collections_visible':len(cols['data']),
        'models':[m['name'] for m in model.get('models',[])],'rag_status':status}
start=time.monotonic()
answer=request(base+'/agent/execute',{'tool':'research_documents',
    'arguments':{'topic':'RAGProof0916','instruction':'RAGProof0916 고객 측 답변이 도착했나요?'},
    'user_id':'migration-check','chat_id':'migration-read-only','message_id':'migration-read-only-1'},agent,240)
result['research']={'status':answer.get('status'),'elapsed_seconds':round(time.monotonic()-start,2),
  'grounded_answer':('미확정' in answer.get('display','')),'has_citations':any(word in answer.get('display','') for word in ['출처','근거','인용'])}
Path('/app/data/migration-read-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
assert result['outline_api'] and result['research']['status']=='succeeded',result['research']
print(json.dumps({'outline_api':result['outline_api'],'collections_visible':result['collections_visible'],
 'models':result['models'],'research':result['research']},ensure_ascii=False))
