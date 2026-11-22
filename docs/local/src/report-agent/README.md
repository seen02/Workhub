# 기존 보고 에이전트 구성 요소

초기 업무 보고 PoC 소스다. 현재 통합 보고 봇은 `src/workhub`에 구현되어 있으며, 이 폴더의 보고 양식·LLM 처리·Rocket.Chat 연결 코드 일부를 재사용한다.

- `backend/app/rocketchat/realtime.py`: Rocket.Chat 실시간 구독·재연결.
- `backend/app/rocketchat/draft.py`: 보고 구조화 처리.
- `backend/app/logic.py`: 명시된 진행률 계산.
- `backend/evals`: 합성 보고 평가 도구·자료.

기존 보고 DB와 검토 화면 서비스는 `legacy-report` 선택 프로필에 남아 있다. 현재 기본 보고 흐름·실행 기준은 [프로젝트 README](../../OVERVIEW.md), 개발 범위는 [기능 개편 명세](../../기능_개편_구현_명세_1-4.md)를 따른다. 초기 팀 공유 및 단계별 시연 가이드는 정리했다.
