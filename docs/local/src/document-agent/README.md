# Outline 문서 비서

Outline 문서 작성·수정·검색과 로컬 LLM/RAG 처리를 담당하는 구성 요소다. 현재 통합 실행 및 계정·권한의 기준은 [프로젝트 README](../../OVERVIEW.md)를 따른다.

- `app.py`, `agent_tools.py`: 문서 비서 API와 도구 처리.
- `rag_service.py`, `rag_search.py`, `rag_sync.py`, `rag_store.py`: 검색·색인 동기화·저장.
- `user_acl.py`: 사용자별 문서 접근 검사.
- `task_runtime.py`, `webui_bridge.py`, `webui_receipt.py`: 작업 실행·상태 및 Open WebUI 연동.

[RAG 구현 기록](RAG-IMPLEMENTATION.md)과 [RAG 운영 참고](RAG-OPERATIONS.md)는 초기 구성의 기술 자료다. 과거 단독 실행 환경의 경로·명령·검색 대상은 현재 통합 환경과 다를 수 있다. 현재 권한 정책은 권한 구현 결과, 후속 검색 개편 범위는 [기능 구현 명세](../../기능_개편_구현_명세_1-4.md)를 확인한다.
