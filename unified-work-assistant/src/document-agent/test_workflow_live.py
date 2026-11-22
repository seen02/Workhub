"""Real UI/Qwen checks; only writes into 로컬 AI 테스트."""
import contextlib, io, json
from test_agent_chat import chat, ROOT
from test_workflows import outputs, outline

reports=[]
def run(text,previous=None):
    print('START '+text[:80],flush=True)
    with contextlib.redirect_stdout(io.StringIO()):r=chat(text,title='[작업흐름 검증] 메모부터 저장까지',previous=previous)
    reports.append(r)
    (ROOT/'data/workflow-live.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'chat':r['chat_id'],'seconds':r['seconds'],'content':r['result'].get('content'),'tools':outputs(r)},ensure_ascii=False),flush=True)
    return r

if __name__=='__main__':
    first=run('이 메모의 오타를 고치고 업무 보고 템플릿에 맞춰서\n‘로컬 AI 테스트’ 컬렉션의 ‘작업흐름 검증 0916’ 문서(없다면 만들어서) 아래에 저장해줘.\n메모 원문:\n13시 로컬 모댈 생성 완료.\n15시 모델 테스트 진행중.\n17시 발표 예쩡.')
    assert any(x.get('verified') for x in outputs(first)),outputs(first)
    body=first['result']['content'];assert all(x in body for x in ['13시','15시','17시','예정','진행'])
    again=run('저장만 다시 시도해줘',first['chat_id'])
    assert any(x.get('duplicate') for x in outputs(again)),outputs(again)
    preview=run('17시를 18시로 바꿔서 초안만 다시 보여줘. 저장하지 마.',first['chat_id'])
    assert any(x.get('draft_id') and not x.get('saved') for x in outputs(preview)),outputs(preview)
    assert '18시 발표' in preview['result']['content'],preview['result']['content']
    (ROOT/'data/workflow-main-live.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS create-if-missing, template, typo correction, read-back, duplicate, scoped fact edit',flush=True)
