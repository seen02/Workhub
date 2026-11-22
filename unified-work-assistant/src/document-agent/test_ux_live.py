"""Bounded live Qwen/UI checks; writes only under the existing demo results folder."""
import contextlib,io,json
from test_agent_chat import chat,ROOT
from test_workflows import outputs,outline

reports=[]
def run(prompt,previous=None):
    print('START:',prompt[:90],flush=True)
    with contextlib.redirect_stdout(io.StringIO()):
        report=chat(prompt,title='[사용감 검증] 쉬운 문서 요청',previous=previous)
    reports.append(report)
    (ROOT/'data/ux-live.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'chat':report['chat_id'],'seconds':report['seconds'],'error':report['result'].get('error'),'content_start':report['result'].get('content','')[:150],'tools':[v.get('status') for v in outputs(report)]},ensure_ascii=False),flush=True)
    assert not report['result'].get('error'), report['result'].get('error')
    return report

if __name__=='__main__':
    r=run('도시시설 3D 검토 PoC 자료 찾아서 지금 어디까지 됐고 뭐가 남았는지 알려줘.')
    research=[x for x in outputs(r) if x.get('research_id')]
    assert research and research[-1]['read_count']>=6 and research[-1]['read_count']==research[-1]['matched_count'], outputs(r)
    content=r['result']['content']
    assert all(x in content for x in ['## 개요','## 핵심 내용','## 진행 상태','## 문제점','## 다음 계획','### 출처','### 조사 범위'])
    assert '11.8' in content and '43.0' in content and '미확정' in content, content
    follow=run('그 내용으로 내일 팀장님께 보고할 내용을 정리해줘.',r['chat_id'])
    assert '재사용' in follow['result']['content'],follow['result']['content']
    draft=run('아래 메모를 팀장님께 보고할 말로 다듬어줘. 아직 저장하지 마.\n메모: 업로드 화면 구현 완료. 서버 연동은 진행 중. 내일 실패 응답 처리 확인 예정.')
    assert any(x.get('draft_id') and not x.get('saved') for x in outputs(draft)),outputs(draft)
    saved=run('시연 결과 아래에 방금 초안을 저장해줘.',draft['chat_id'])
    verified=[x for x in outputs(saved) if x.get('verified')];assert verified,outputs(saved)
    assert '[회사시연 20260916] 시연 결과' in saved['result']['content']
    doc=outline('documents.info',{'id':verified[-1].get('id') or verified[-1]['url'].split('/')[-1]})
    assert '진행 중' in doc['text'] and '확인' in doc['text']
    again=run('같은 위치에 다시 저장해줘.',draft['chat_id'])
    assert any(x.get('duplicate') for x in outputs(again)),outputs(again)
    print('PASS: collection-free research, full report, follow-up, draft, partial destination, duplicate save',flush=True)
