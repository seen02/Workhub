"""Real Qwen -> FastAPI -> Outline end-to-end smoke test."""
import json
from benchmark import ROOT, COLLECTION, api

request = {'text': '9월 16일 Sat2City 기술 조사 진행 중\nPPT 3장 수정 진행 중\n9월 17일 Outline 자료 작성 예정',
           'title': '[AI 통합시험] Qwen 문서 작성·검색·수정', 'context': '2026-09-16 최종 통합 검증',
           'collection_id': COLLECTION, 'request_id': 'integration-20260916-final', 'save': True}
create = api('organize_note', request)
assert create.get('verified'), create
duplicate = api('organize_note', request)
assert duplicate.get('duplicate') and duplicate['id'] == create['id'], duplicate
new_id = api('organize_note', {**request, 'request_id': request['request_id']+'-duplicate'})
assert new_id.get('duplicate') and new_id['id'] == create['id'], new_id
revise = api('revise_document', {'document_id': create['id'], 'instruction': '정리된 메모의 PPT 3장 수정 진행 중을 PPT 3장 수정 완료로 바꿔줘.', 'request_id': 'integration-20260916-revise'})
assert revise.get('verified'), revise
current, original = revise['text'].split('## 입력 원문', 1)
assert 'PPT 3장 수정 완료' in current and 'PPT 3장 수정 진행 중' in original, revise
search = api('search_documents', {'question': 'PPT 수정은 완료됐어? 앞으로 예정된 업무도 알려줘.', 'keyword': 'Sat2City', 'collection_id': COLLECTION})
assert search.get('sources') and '완료' in search.get('answer',''), search
assert any(s['id'] == create['id'] for s in search['sources']), search
report = {'create': create, 'duplicate_same_request': duplicate['id'], 'duplicate_new_request': new_id['id'], 'revise': revise, 'search': search}
(ROOT/'data/integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
