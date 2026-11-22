"""Attachment, full-document research and conversational draft integration checks."""
import json,uuid,re,time
from test_workflows import ROOT,chat,outputs,outline,execute,a,c,COL,setup
def upload():
    boundary='----localtest'+uuid.uuid4().hex
    raw=(ROOT/'data/attachment-probe.md').read_bytes()
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="attachment-probe.md"\r\nContent-Type: text/markdown\r\n\r\n').encode()+raw+f'\r\n--{boundary}--\r\n'.encode()
    r=c.post('/api/v1/files/?process_in_background=false',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary});r.raise_for_status()
    f=r.json();assert f.get('data',{}).get('status')!='failed',f
    return {'type':'file','id':f['id'],'name':f['filename'],'file':f,'status':'uploaded'}
if __name__=='__main__':
    import sys
    case=sys.argv[1] if len(sys.argv)>1 else 'attachment'
    if case=='attachment':
        f=upload();print('Upload and processing passed',flush=True)
        report=chat('첨부한 attachment-probe.md를 원문 내용 그대로 "로컬 AI 테스트" 컬렉션의 "[에이전트 검증] 문서함" 아래에 "[채팅 검증] 첨부 문서" 제목으로 넣어줘.',files=[f])
        saved=[v for v in outputs(report) if v.get('verified')];assert saved,outputs(report)
        doc=outline('documents.info',{'id':saved[-1]['id']});assert doc['parentDocumentId']==setup()['parent']['id'];assert doc['title']=='[채팅 검증] 첨부 문서'
        normalize=lambda x:re.sub(r'\s+','',re.sub(r'\\([\[\]#*_.!])',r'\1',x).replace('* ','- '))
        assert normalize(doc['text'])==normalize((ROOT/'data/attachment-probe.md').read_text(encoding='utf-8-sig'))
        result={'chat':report,'document':doc}
    elif case=='research':
        report=chat('"로컬 AI 테스트" 컬렉션에서 AgentProbe 관련 문서를 모두 찾아 읽고 핵심 결과와 진행 상태를 출처와 함께 종합해줘. 문서에 저장하지 마.')
        research=[v for v in outputs(report) if v.get('research_id')];assert research,outputs(report)
        r=research[-1];assert r['read_count']==4 and not r['failed'];assert all(s['characters']>1100 for s in r['sources'])
        assert all('ALPHA'+str(i) in r['report'] for i in range(1,5)),r['report']
        assert all(str(i)+'초' in r['report'] for i in range(11,15)),r['report']
        assert '시각화할 예정' not in r['report'] and '개선 계획 수립' not in r['report']
        assert len(re.findall(r'http://192',report['result']['content']))>=4
        result={'chat':report}
    elif case=='draft':
        first=chat('다음 메모를 읽기 좋게 정리해줘. 아직 저장하지 마.\n메모 원문: 김민수 담당. 로그인 연결 테스트 완료. 첨부 기능은 진행 중. 메모리 부족 원인은 미확인. 다음 작업은 파일 테스트.')
        ds=[v for v in outputs(first) if v.get('draft_id')];assert ds and not ds[-1].get('saved');assert '아직 저장하지 않았습니다' in first['result']['content']
        second=chat('방금 초안의 제목을 "[채팅 검증] 대화형 초안"으로 바꾸고 다음 계획을 맨 위로 옮겨줘. 아직 저장하지 마.',previous=first['chat_id'])
        ds=[v for v in outputs(second) if v.get('draft_id')];assert ds and not ds[-1].get('saved')
        assert ds[-1]['title']=='[채팅 검증] 대화형 초안'
        assert '채ating' not in ds[-1]['markdown']
        assert ds[-1]['markdown'].find('파일 테스트')<ds[-1]['markdown'].find('로그인')
        third=chat('방금 초안을 그대로 "로컬 AI 테스트" 컬렉션의 "[에이전트 검증] 문서함" 아래에 저장해줘.',previous=first['chat_id'])
        saved=[v for v in outputs(third) if v.get('verified')];assert saved,outputs(third)
        doc=outline('documents.info',{'id':saved[-1]['id']});assert re.sub(r'\s+','',doc['text'].replace('* ','- '))==re.sub(r'\s+','',ds[-1]['markdown'].replace('* ','- '))
        result={'draft':first,'edited':second,'saved':third,'document':doc}
    elif case=='revise':
        doc=json.loads((ROOT/'data/agent-draft.json').read_text(encoding='utf-8'))['document']
        report=chat(f'Outline 문서 ID "{doc["id"]}"의 내용을 먼저 읽고, 첨부 기능의 상태만 진행 중에서 완료로 수정해줘. 나머지 내용은 그대로 유지해줘.')
        revised=[v for v in outputs(report) if v.get('verified')];assert revised,outputs(report)
        current=outline('documents.info',{'id':doc['id']})
        assert re.search(r'첨부 기능[^\n]*완료',current['text']),current['text']
        assert '미확인' in current['text'] and '파일 테스트' in current['text']
        result={'chat':report,'document':current}
    (ROOT/f'data/agent-{case}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS '+case,flush=True)
