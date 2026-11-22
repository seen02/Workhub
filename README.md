# Workhub

Rocket.Chat에 쓴 진행 보고를 Outline의 업무로 연결하는 사내 업무 비서입니다. 서버가 Qwen으로 문장을 해석하고, 직원이 확인한 보고를 문서와 채팅방에 반영합니다. 개인 채팅으로 마감 업무도 알려줍니다.

현장실습 프로젝트의 실제 소스, 테스트, 설계 문서를 원본 경로에 맞춰 담았습니다.

| 폴더 | 내용 |
| --- | --- |
| [로컬 연동 구성](unified-work-assistant/) | [Workhub 업무 API·웹 화면](unified-work-assistant/src/workhub/), [보고 에이전트](unified-work-assistant/src/report-agent/), [문서 검색 에이전트](unified-work-assistant/src/document-agent/), [Outline 연동 패치](unified-work-assistant/integrations/outline/) |
| [운영용 소스](production/) | Outline·Authentik 로그인과 업무 관리에 사용한 [백엔드](production/workhub/), [Outline 변경 파일](production/outline/), [빌드·설치 설정 예시](production/) |
| [설계와 검증 문서](docs/README.md) | 채팅 보고, 문서 검색, 권한, 마감 알림, 배포의 구조와 검증 결과 |

## 먼저 볼 코드

- [보고 해석](unified-work-assistant/src/workhub/report_parser.py)과 [모델 호출을 건너뛰는 경우의 테스트](unified-work-assistant/src/workhub/test_report_fastpath.py)
- [보고 확정·문서 반영](unified-work-assistant/src/workhub/reports.py)과 [확정·재시도 테스트](unified-work-assistant/src/workhub/test_reports.py)
- [마감 알림](unified-work-assistant/src/workhub/deadline_alerts.py)과 [발송 권한·중복 방지 테스트](unified-work-assistant/src/workhub/test_deadline_alerts.py)
- [문서 검색·권한 설계](docs/local/src/document-agent/RAG-IMPLEMENTATION.md)와 [보고 성능 개선 기록](docs/local/보고_성능_및_신뢰성_개선_명세.md)

## Challenges & Solutions

### 1. 업무가 분명한 보고의 처리 지연

보고에 업무명과 완료 기준이 정확히 들어 있어도 관련 업무를 다시 검색하고 모델을 사용할 수 있는지 확인하느라 시간이 걸렸습니다. 최신 업무 목록에서 대상 업무와 완료 기준을 하나로 정할 수 있으면 바로 연결하도록 바꿨습니다. 이름이 겹치거나 문장이 모호하면 기존 후보 탐색 절차를 거칩니다.

같은 PC와 입력에서 보고를 해석해 업무에 연결하는 시간을 전후 각 2회 측정했습니다. 한 프로젝트의 업무 두 건은 평균 **11.510초 → 4.629초**, 두 프로젝트의 업무 두 건은 **10.766초 → 4.472초**로 줄었습니다. 두 입력 모두 변경 전후 모델 호출은 0회였습니다. [처리 경로 테스트](unified-work-assistant/src/workhub/test_report_fastpath.py)

### 2. 보고 확정 중 문서 변경과 일부 저장 실패

직원이 초안을 보는 사이 담당자가 바뀌거나 동료가 문서를 수정할 수 있습니다. 확정 직전에 최신 문서와 수정 권한을 다시 확인하고, 초안을 만들 때와 문서가 달라지면 저장을 멈춰 다시 확인하도록 안내했습니다.

채팅 게시 결과와 문서별 저장 결과는 SQLite에 각각 기록했습니다. 게시 응답이 끊기면 초안에 배정한 메시지 ID로 게시 여부를 확인하고, 문서 일부만 저장된 경우에는 이미 반영된 내용을 확인한 뒤 남은 문서만 다시 처리합니다. 테스트용 SQLite와 외부 서비스의 모의 응답으로 문서 변경, 권한 회수, 응답 끊김, 중복 제출을 재현했습니다. [보고 확정·재시도 테스트](unified-work-assistant/src/workhub/test_reports.py)

### 3. 서비스 재시작과 응답 끊김으로 인한 마감 알림 중복

오전 9시 마감 알림을 발송하던 중 서비스가 재시작되거나 채팅 서버의 응답이 끊기면, 같은 알림을 다시 보낼 수 있었습니다. 발송 직전에 업무 상태, 열람 권한, 알림 설정을 다시 확인하고 발송 기록과 메시지 ID를 저장했습니다. 재시작 뒤에는 당일 기록을 확인하고, 응답이 끊겼을 때는 메시지 ID로 이미 발송됐는지 확인합니다.

로컬 시험 발송에서 대상 3명의 개인 채팅에 알림이 도착하는 것을 확인했습니다. 서비스 재시작, 권한 변경, 발송 직전 알림 끄기, 발송 응답 끊김도 테스트했습니다. [마감 알림 테스트](unified-work-assistant/src/workhub/test_deadline_alerts.py)

## 실행 범위와 라이선스

Rocket.Chat·Ollama·Qwen 연동은 로컬 테스트 구성에서 검증했습니다. 운영용은 Outline·Authentik과 업무 관리 API를 중심으로 구성했습니다. 전체 서비스를 실행하려면 외부 구성 요소, 실행 환경 변수와 [고정된 버전의 Outline 원본](unified-work-assistant/integrations/outline/upstream.lock.json)이 필요합니다. 공개본의 운영용 Outline 폴더에는 이 프로젝트에서 수정하거나 추가한 파일을 담았습니다.

업무 데이터, 실제 계정·접속 설정, 사내 운영 절차와 환경별 검증 기록을 정리해 공개했습니다. Outline 원본과 파생 부분에는 기존 Business Source License 1.1이 적용됩니다. [라이선스](LICENSE) · [제3자 소프트웨어 및 출처](docs/THIRD_PARTY_NOTICES.md)
