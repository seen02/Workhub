"""Explicit live verification; creates only clearly labeled fixtures in the test collection."""
import json
import os
import sys
import time
import uuid
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parent
agent=httpx.Client(base_url='http://document-agent:8000',timeout=240,headers={'Authorization':'Bearer '+os.environ['AGENT_TOKEN']})
outline=httpx.Client(base_url=os.environ['OUTLINE_URL']+'/',timeout=60,headers={'Authorization':'Bearer '+os.environ['OUTLINE_API_KEY']})

def api(client,path,payload):
    r=client.post(path,json=payload);r.raise_for_status();return r.json()

def seed():
    path=ROOT/'data/rag-live-fixtures.json'
    if path.exists():return json.loads(path.read_text())
    cols=api(outline,'collections.list',{'limit':100})['data']
    cid=next(c['id'] for c in cols if c['name']=='로컬 AI 테스트')
    fixtures=json.loads((ROOT/'tests/fixtures/rag/documents.json').read_text())[:3]
    result=[]
    for f in fixtures:
        payload={'id':str(uuid.uuid4()),'collectionId':cid,'title':'[RAG 검증] RAGProof0916 '+f['title'],
            'text':f['text'],'publish':True}
        doc=api(outline,'documents.create',payload)['data']
        assert doc['id']==payload['id']
        result.append({'id':doc['id'],'title':doc['title'],'kind':f['id']})
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def execute(tool,args,chat):
    start=time.monotonic()
    result=api(agent,'/agent/execute',{'tool':tool,'arguments':args,'user_id':'rag-live','chat_id':chat,'message_id':str(uuid.uuid4())})
    result['wall_seconds']=round(time.monotonic()-start,3)
    assert result['status']=='succeeded',result
    return result

def backend():
    fixtures=seed();sync=api(agent,'/rag/sync',{})
    assert sync['status']=='succeeded',sync
    chat='rag-live-'+str(uuid.uuid4());records=[]
    r=execute('research_documents',{'topic':'RAGProof0916','instruction':'RAGProof0916 고객 측 답변이 도착했나요?'},chat)
    assert '미확정' in r['display'] and r['read_count']==0,r
    records.append(r)
    r=execute('read_request',{'request':'그 내용에서 다음 할 일만 알려줘'},chat)
    assert r['reused'],r
    records.append(r)
    r=execute('research_documents',{'topic':'RAGProof0916','instruction':'RAGProof0916 PPT 수정 상태 알려줘'},chat)
    assert '완료' in r['display'] and '인용' in r['display'],r
    records.append(r)
    result={'sync':sync,'fixtures':fixtures,'records':records}
    (ROOT/'data/rag-live-backend.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps([{'seconds':r['wall_seconds'],'display':r['display'],'timings':r.get('timings'),'metrics':r.get('metrics',r.get('answer_metrics'))} for r in records],ensure_ascii=False,indent=2),flush=True)

def webui(read_only=False):
    from test_agent_chat import chat
    first=chat('RAGProof0916 고객 측 답변이 도착했나요? 출처도 알려줘.',title='[RAG 검증] 검색·후속·저장')
    assert first['result'].get('done') and '미확정' in first['result']['content'],first
    follow=chat('그 내용에서 다음 할 일만 알려줘.',previous=first['chat_id'])
    assert follow['result'].get('done') and '선택 근거' in follow['result']['content'],follow
    if read_only:
        (ROOT/'data/rag-live-webui-read.json').write_text(json.dumps([first,follow],ensure_ascii=False,indent=2))
        return
    note=chat('아래 메모의 오타를 고치고 업무 보고 템플릿에 맞춰 [RAG 검증] 0916 메모라는 제목으로 로컬 AI 테스트 컬렉션에 저장해줘.\n메모 원문:\n13시 로컬 모댈 생성 완료.\n15시 모델 테스트 진행중.\n17시 발표 예쩡.',title='[RAG 검증] 템플릿 메모 저장')
    assert note['result'].get('done') and '저장' in note['result']['content'],note
    retry=chat('저장만 다시 시도해줘.',previous=note['chat_id'])
    (ROOT/'data/rag-live-webui.json').write_text(json.dumps([first,follow,note,retry],ensure_ascii=False,indent=2))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='webui-read':webui(True)
    else:(webui if len(sys.argv)>1 and sys.argv[1]=='webui' else backend)()
