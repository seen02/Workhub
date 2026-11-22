"""Generate a reviewable Markdown report from recorded results, without inference."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT/'results/comparison.json').read_text(encoding='utf-8'))
rows, summary = data['rows'], data['summary']
lines = ['# Qwen3 / Gemma 업무보고 비교 결과', '',
         f"평가 시작(UTC): {data['metadata']['started_at']}", '',
         '합성 한국어 업무보고 50건 × 모델 2종. 모델 원본과 앱 후처리를 분리 평가. '
         '기본 모델 설정 변경 및 업무보고 저장 없음.', '',
         '## 자동 채점 결과', '',
         '| 항목 | Qwen3 4B | Gemma 3 4B |', '|---|---:|---:|']
models = list(summary)
def compare(label, fn):
    lines.append('| '+label+' | '+' | '.join(str(fn(summary[m])) for m in models)+' |')
compare('평가 완료 건수', lambda s:s['cases'])
compare('Schema 통과', lambda s:s['successes'])
compare('최종 호출 오류', lambda s:s['errors'])
compare('평균 응답시간(초, 로딩·재시도 포함)', lambda s:s['latency_seconds'].get('mean','-'))
compare('P95 응답시간(초)', lambda s:s['latency_seconds'].get('p95','-'))
for stage, label in [('raw','모델 원본'),('normalized','앱 후처리')]:
    for field, title in [('progress','진행률'),('status','상태'),('task','업무명 키워드'),('issue','이슈 키워드/없음'),('next_action','다음 작업 키워드/없음'),('start_time','시작 시각'),('end_time','종료 시각'),('duration_hours','소요시간')]:
        compare(label+' '+title, lambda s:s[stage][field]['passed'].__str__()+'/'+str(s[stage][field]['total']))
    compare(label+' 모든 채점 항목 통과', lambda s:s[stage]['all_fields_passed'])
lines += ['', '## 진행률 오류와 후처리 회귀', '',
          '| 모델 | 사례 | 기대값 | 모델 원본 | 앱 후처리 |', '|---|---|---|---|---|']
for r in rows:
    if not r.get('raw_checks',{}).get('progress') or not r.get('normalized_checks',{}).get('progress'):
        lines.append(f"| {r['model']} | {r['id']} | {r['expected']['progress']} | {r.get('raw',{}).get('progress')} | {r.get('normalized',{}).get('progress')} |")
lines += ['', '## 전체 사례 검토', '', '오류 목록은 자동 판정이다. 키워드 누락은 의미 오류와 동일하지 않으므로 원문 JSON과 함께 검토한다.', '']
for r in rows:
    failed = ', '.join(k for k,v in r.get('normalized_checks',{}).items() if not v)
    lines += [f"### {r['model']} / {r['id']} ({r['category']})", '',r['input'], '',
              f"- 응답시간: {r['elapsed_seconds']}초 / 호출 시도: {len(r['calls'])}",
              f"- 후처리 채점 실패: {failed or r.get('error','없음')}",
              f"- 결과: {json.dumps(r.get('normalized',{}),ensure_ascii=False)}", '']
lines += ['## 해석 범위', '',
          '- 단일 실행, 고정 순서, 같은 Prompt/Schema/temperature. 모델별 기본 샘플링·양자화 설정은 완전히 같지 않다.',
          '- Gemma는 think 옵션만 제외. 양 모델 모두 실제 LocalProvider 호출 및 앱 후처리 사용. Mock 미사용.',
          '- 업무명·이슈·다음 작업 점수는 키워드 기준이며, 실제 의미 정확도나 직원 수정률을 나타내지 않는다.',
          '- 진행률 미상과 복수 업무에는 정답 null을 요구했다. 시간 채점은 명시한 5건에만 적용했다.',
          '- 95% confidence 등의 모델 자기 보고는 정답률로 해석하지 않는다.',
          '- 로딩·캐시·실행 순서·하드웨어의 영향을 받는 지연시간으로 서비스 SLA를 보장하지 않는다.',
          '- 전체 원본·정답·필드별 판정·Ollama 실행 통계는 comparison.json에 보존한다.', '']
(ROOT/'results/comparison.md').write_text('\n'.join(lines),encoding='utf-8')
print(ROOT/'results/comparison.md')
