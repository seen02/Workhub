# Workhub · 업무 비서 백엔드

사내 메신저 Rocket.Chat에 올라온 진행 보고를 Outline의 업무 항목에 연결하는 프로젝트입니다. 사용자가 보고 초안을 확인해 확정하면 문서의 업무 상태가 바뀌고, 선택한 채팅방에 정해진 양식으로 보고가 올라갑니다.

현장실습에서 채팅 보고를 해석해 실제 업무와 완료 기준을 연결하는 흐름을 구현했습니다. 정해진 시각에 마감 업무를 알리는 기능, 보고 확정 시점의 권한 확인, 실패한 요청을 재시도할 때 중복을 피하는 처리도 맡았습니다.

## 코드와 테스트

| 기능 | 구현 | 확인할 테스트 |
| --- | --- | --- |
| 진행 보고 해석 | [보고 파서](src/workhub/report_parser.py)가 입력을 업무·완료 기준에 연결합니다. 업무가 분명하면 바로 해석하고, 판단이 필요한 경우 [모델 호출](src/workhub/ai_runtime.py)을 사용합니다. | [명확한 보고와 예외](src/workhub/test_report_fastpath.py) |
| 보고 확정과 문서 반영 | [확정 처리](src/workhub/reports.py)와 [권한 검사](src/workhub/permissions.py)에서 담당자와 문서 상태를 다시 확인합니다. [채팅 연동](src/workhub/report_transport.py)은 같은 보고를 다시 게시하지 않도록 발송 결과를 확인합니다. | [보고 저장과 실패 복구](src/workhub/test_reports.py), [제출 흐름](src/workhub/test_report_submit_integration.py) |
| 마감 알림 | [알림 처리](src/workhub/deadline_alerts.py)는 기한이 지났거나 곧 끝나는 업무를 모아 개인 채팅으로 보냅니다. 발송 전에 열람 가능 여부를 확인하고 발송 이력을 기록합니다. | [알림 대상과 중복 방지](src/workhub/test_deadline_alerts.py) |
| 웹 포털 | [FastAPI 엔드포인트](src/workhub/main.py)와 [화면 코드](src/workhub/static/)에서 업무 목록, 칸반, 진행 통계를 다룹니다. | [칸반](src/workhub/test_kanban.py), [진행 통계](src/workhub/test_outline_analytics.py) |

## 검토용 테스트 실행

Python 3.12에서 아래 명령을 실행하면 업무 상태 계산, 문서 검색, 프로젝트 그룹 연결을 다루는 원래 테스트를 실행할 수 있습니다.

```sh
python -m pip install -r requirements-review.txt
python -m pytest -q
```

공개본에는 Workhub의 백엔드, 화면 코드, 원래 테스트를 담았습니다. 화면 도움말의 시연 계정 식별 정보를 지우고 테스트 이메일은 예약된 예시 도메인으로 바꿨습니다. 전체 서비스와 보고·알림 통합 테스트를 실행하려면 현장실습 당시의 보고 엔진과 연동 환경이 필요합니다.

코드는 [공개 범위 및 권리 안내](LICENSE)에 따라 열람할 수 있습니다. Rocket.Chat은 메시징과 채팅방을, Outline은 문서 편집과 공유를 제공하며, Workhub는 두 서비스의 API에 업무 보고와 관리 흐름을 연결합니다.
