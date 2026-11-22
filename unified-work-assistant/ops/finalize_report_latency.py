"""Record only a completed, verified local latency repair."""
import json,statistics
from pathlib import Path

root=Path(__file__).resolve().parents[1]
before=json.loads((root/'reports/report-latency-before-20261007.json').read_text(encoding='utf-8'))
after=json.loads((root/'reports/report-latency-final-20261007.json').read_text(encoding='utf-8'))
deployed=json.loads((root/'reports/report-latency-deployment-20261007.json').read_text(encoding='utf-8'))
assert after['passed'] and after['documents_unchanged'] and deployed['passed'] and deployed['other_services_unchanged']
prior=[e['seconds'] for e in before['cases']]
colloquial=[e['seconds'] for e in after['cases'] if e['case']=='ai']
whole=[e['seconds'] for e in after['cases'] if e['case']=='whole']
assert len(prior)==len(colloquial)==len(whole)==2 and statistics.mean(colloquial)<statistics.mean(prior)
comparison={'decision':'keep','passed':True,'before_colloquial_seconds':prior,'before_results':'both failed',
    'after_colloquial_seconds':colloquial,'after_whole_seconds':whole,'after_results':'all correct',
    'after_model_calls':0,'read_only':True,'documents_unchanged':True,
    'scope':'report_parser.plan, not chat display or report submission','deployed':True}
(root/'reports/report-latency-comparison-20261007.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf-8')
image=deployed['runtime']['workhub']['image_id']
heading='### 1분 이상 보고 지연 수정 기록 — 2026-10-07'
text=f'''

{heading}

#### 실제 원인과 최종 수정

- 사용자 입력 `위성 영상 생성 프로젝트의 자료 정리 다 완료했어.`는 이전 직접 해석 문법에 없었다. 실제 업무 목록 조회 약 4초·RAG 약 7초 이후 AI로 넘어갔다. 첫 요청은 모델 적재 약 46.25초를 포함해 68.337초 후 취소됐고, 다음 요청은 43.072초 후 기준 상태의 원문 근거 검증에서 실패했다. 큐 대기는 약 0.0001초로 병목이 아니었다.
- `whole_task_items`는 명시된 업무의 `다/모두/전부/전체 완료` 주장만 완전히 해석할 수 있을 때 그 업무의 현재 완료 기준 전체를 연결한다. 다른 프로젝트의 같은 업무명이나 보고하지 않은 다른 업무는 포함하지 않는다.
- 기준별 `마무리했어/마무리했고`와 `작업 중이야`도 좁은 직접 해석 문법에 추가했다. 부정·미래·명령·추가 조건·알 수 없는 문장이 남으면 전체 보고를 기존 경로로 보낸다.
- `ai_runtime.DraftProvider`는 보고 모델 요청에 기본 `keep_alive=30m`를 지정한다. 명시한 호출자의 유지 시간은 보존하고, 기존 취소 처리도 유지한다. 적용 후 설정된 모델을 빈 요청으로 미리 불러 두었다. 보고 후 30분 이상 유휴 상태이거나 서버·모델이 재시작되면 다시 적재할 수 있으며, 모든 AI 보고의 1분 이내 응답을 보장하는 변경은 아니다.
- 기존 모델·AI 출력 스키마·프롬프트는 유지했다. 출력 번호 변환 및 한 업무 생성 제약 시도는 더 느려지거나 준비된 초안을 반환하지 못해 제외했다. 측정 중 외부 문서 변경이 관측된 시도도 최종 비교에 쓰지 않았다.

#### 두 차례씩 측정한 결과

동일 PC·계정·문장으로 측정했다. 아래 반복 측정은 `report_parser.plan`의 초안 해석·업무 연결 시간이다. 실제 버튼 클릭부터 화면 표시까지나 채널 게시·업무 저장 시간은 포함하지 않는다. 측정 사이 35초 간격을 두었다.

| 입력 | 개선 전 1회 | 개선 전 2회 | 최종 개선 후 1회 | 최종 개선 후 2회 |
|---|---:|---:|---:|---:|
| 이미지 정리를 마무리했고 PPT 정리는 작업 중이야 | {prior[0]:.3f}초, 실패 | {prior[1]:.3f}초, 실패 | {colloquial[0]:.3f}초, 정상 | {colloquial[1]:.3f}초, 정상 |
| 자료 정리 다 완료했어 | 별도 운영 로그: 68.337초 후 취소 | 별도 운영 로그: 43.072초 후 실패 | {whole[0]:.3f}초, 정상 | {whole[1]:.3f}초, 정상 |

- 첫 행 전체 입력: `위성 영상 생성 프로젝트 자료 정리는 이미지 정리를 마무리했고 PPT 정리는 작업 중이야.` 개선 전에는 실제 모델 호출이 각 2회였고 최종 개선 후에는 0회였다. 이미지 정리만 완료, PPT 정리만 진행 중으로 연결했고 서류 정리는 보고 항목에 추가하지 않았다.
- 둘째 행의 개선 전은 실제 사용자 테스트의 전체 처리 로그이며, 개선 후 반복 측정과 측정 범위·모델 적재 조건이 다르다. 성공한 동일 결과의 전후 속도 비교나 단축률로 해석하지 않는다.
- 최종 네 번은 모두 최신 실제 업무·기준 ID·상태가 맞았다. 측정 중 대상 문서의 본문·revision·수정 시각이 변하지 않았고, 원본 쓰기·초안 저장·채팅 전송을 하지 않았다. 두 표본의 시간 변동을 모든 입력·동시 부하에 일반화하지 않는다.

#### 검증·실행 적용·복구

- 최종 소스의 자동 테스트 **442개 통과**. 전체 완료 범위, 담당자 권한, 기준 삭제, 자연스러운 상태 표현과 부정·추가 조건, 모델 유지 시간과 취소 처리 등을 검증했다.
- 현재 적용 이미지: `unified-work-assistant/workhub:report-latency-20261007`, 실행 이미지 ID `{image}`.
- Workhub만 재생성했다. 실행 파일 두 개의 SHA-256이 검증한 소스와 일치하고, 실제 두 입력의 업무·상태 연결, `/health` 200과 봇 연결을 다시 확인했다. 16개 서비스가 실행 중이며 건강 검사 대상은 모두 healthy다. 다른 서비스의 컨테이너 ID·이미지 태그·데이터 마운트가 동일하고 Compose는 Workhub 이미지 값만 바뀌었다.
- 첫 적용은 보고 기능·소스 검증 이후 부가 Docker 메타데이터 전체 비교에서 중단돼 이전 이미지로 자동 복구됐다. 검증을 컨테이너·이미지 태그·정렬된 데이터 마운트 보존과 현재 건강 상태 검사로 나눠 재적용했다. 전후 메타데이터는 별도 JSON으로 기록한다.
- 이전 이미지 `unified-work-assistant/workhub:report-fastpath-20261007`와 보존 태그 `unified-work-assistant/workhub:report-latency-before-20261007`, 변경 전 두 소스·Compose 설정·명세는 `backups/report-latency-20261007/`에 있다. 인증 설정이 든 `compose.private.json`은 공유하지 않는다.
- `python ops/configure_report_latency.py rollback` 다음 `docker compose -f .local/compose.json up -d --no-deps --no-build workhub`로 이전 이미지에 복구한다. 다른 설정이나 데이터는 되돌리지 않는다. 소스 복구 시 이후 변경을 확인한 뒤 이번 두 파일만 비교한다.
- 고정 개발 ZIP·배포 묶음 **20261007-1**은 이번 수정 전 기준으로 보존한다. 추가 수정은 현재 개발 소스와 로컬 실행에 적용했으며, 고정 배포 아카이브를 재생성하지 않았다.

검증 자료: [개선 전](reports/report-latency-before-20261007.json), [최종 개선 후](reports/report-latency-final-20261007.json), [비교와 유지 판단](reports/report-latency-comparison-20261007.json), [자동 테스트](reports/report-latency-tests-20261007.txt), [실행 적용 검증](reports/report-latency-deployment-20261007.json), [적용 로그](reports/report-latency-apply-20261007.txt). 재현·적용 도구는 `ops/verify_report_latency.py`, `ops/apply_report_latency.py`다.
'''
path=root.parent/'docs/local/보고_성능_및_신뢰성_개선_명세.md'
existing=path.read_text(encoding='utf-8')
if heading in existing:existing=existing[:existing.index(heading)].rstrip()
path.write_text(existing.rstrip()+text,encoding='utf-8')
print(json.dumps(comparison,ensure_ascii=False))
