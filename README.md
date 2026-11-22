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

## 실행 범위와 라이선스

Rocket.Chat·Ollama·Qwen 연동은 로컬 테스트 구성에서 검증했습니다. 운영용은 Outline·Authentik과 업무 관리 API를 중심으로 구성했습니다. 전체 서비스를 실행하려면 외부 구성 요소, 실행 환경 변수와 [고정된 버전의 Outline 원본](unified-work-assistant/integrations/outline/upstream.lock.json)이 필요합니다. 공개본의 운영용 Outline 폴더에는 이 프로젝트에서 수정하거나 추가한 파일을 담았습니다.

업무 데이터, 실제 계정·접속 설정, 사내 운영 절차와 환경별 검증 기록을 정리해 공개했습니다. Outline 원본과 파생 부분에는 기존 Business Source License 1.1이 적용됩니다. [라이선스](LICENSE) · [제3자 소프트웨어 및 출처](docs/THIRD_PARTY_NOTICES.md)
