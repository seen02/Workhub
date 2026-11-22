"""Real multi-turn selection and retry; writes only to the test collection."""
from test_workflow_live import run, outputs, ROOT
import json

r=run('아래 메모를 원문 그대로 ‘로컬 AI 테스트’ 컬렉션의 ‘검증’ 아래에 저장해줘.\n메모: 15시 서버 연결 확인 중. 17시 결과 공유 예정.')
assert any(x.get('needs_input') for x in outputs(r)),outputs(r)
s=run('1번이야',r['chat_id'])
assert any(x.get('verified') for x in outputs(s)),outputs(s)
v=run('방금 초안 다시 보여줘',r['chat_id'])
assert '15시' in v['result']['content'] and '17시' in v['result']['content']
(ROOT/'data/workflow-choices-live.json').write_text(json.dumps([r,s,v],ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS numbered destination, resume same draft, show saved result',flush=True)
