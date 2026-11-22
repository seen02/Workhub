# RAG 운영 참고

> 초기 단독 실행 환경의 기술 자료다. 아래 작업 위치·실행 명령·컬렉션 목록은 작성 당시 기준이며 현재 통합 환경의 설정을 의미하지 않는다. 현재 실행·복구는 통합 운영 문서를 기준으로 한다.

작업 위치: `Outline/local-ai`. 현재 설치에서는 RAG가 켜져 있으며 **로컬 AI 테스트**, **개인 업무 보고** 컬렉션을 색인한다. 원본은 Outline API로 읽고, `rag-postgres`는 다시 만들 수 있는 별도 검색 사본이다. 기존 `../compose.yml` 및 Outline PostgreSQL 볼륨을 수정하지 않는다.

## 현재 설치에서 사용

```powershell
docker compose --profile rag up -d --wait
docker compose exec -T document-agent python rag_admin.py status
docker compose exec -T document-agent python rag_admin.py sync
```

- 자동 동기화: 기본 300초. 동기화 실패 시 30초 뒤 재시도한다. 에이전트를 통한 문서 저장·수정은 동기화 이벤트도 발생시킨다.
- 재색인: `docker compose exec -T document-agent python rag_admin.py reindex`
- 현재 문서의 임베딩을 전부 준비한 뒤 한 트랜잭션으로 활성 버전을 바꾼다. 성공 시 이전 버전의 조각은 삭제한다. 임베딩 준비·트랜잭션 실패 시 이전 완성 버전이 남는다.
- 완전한 목록에서 빠진 문서만 비활성화한다. 403/404·보관·이동은 제외하고 일시적인 네트워크 오류는 삭제로 간주하지 않는다.
- 선택 근거와 보관 결과는 답변·재사용·완료 결과 조회 때 원문 상태와 버전을 확인한다. 원문이 바뀌었으면 오래된 내용을 표시하지 않는다. 새 색인은 다음 동기화에서 반영한다.
- 개발 화면 [localhost:3002](http://localhost:3002)에서 색인 상태, 동기화, 작업 진행, 중지와 결과를 확인할 수 있다.

## 작업 중지와 복구

사용자 화면은 [Open WebUI](http://localhost:3001/?model=outline-assistant)이다. 중지 버튼은 작업 ID로 실제 백엔드 취소를 전달한다. “조사 이어서”는 같은 대화의 남은 문서와 재시도 가능한 읽기 실패를 처리한다. “방금 결과 다시 보여줘”는 보관된 실행 결과를 표시한다.

API는 모두 기존 로컬 인증을 사용한다.

| 경로 | 용도 |
|---|---|
| `POST /agent/submit` | 먼저 작업을 등록하고 `event_id`, `queued` 반환 |
| `POST /agent/execute` | 기존 호환 경로; 완료까지 대기 |
| `POST /agent/progress` | 작업 ID 또는 대화 범위의 단계·경과 시간 |
| `POST /agent/result` | 동일 사용자·대화의 전체 결과 |
| `POST /agent/cancel` | 동일 사용자·대화의 해당 작업 취소 |
| `GET /rag/status` | 색인 수·마지막 동기화·실패 |
| `POST /rag/sync`, `/rag/reindex` | 변경 동기화 / 강제 재색인 |

작업 요청 공통 형태:

```json
{"tool":"research_documents","arguments":{"topic":"RAGProof0916","mode":"quick"},"user_id":"사용자 ID","chat_id":"대화 ID"}
```

결과·취소 요청은 `arguments`를 `{"event_id":"실제 작업 ID"}`로 바꾸고 같은 사용자·대화 ID를 사용한다. 개발 CLI에서도 다음처럼 조회·취소할 수 있다.

```powershell
docker compose exec -T document-agent python rag_admin.py result --event-id ID --user-id USER --chat-id CHAT
docker compose exec -T document-agent python rag_admin.py cancel --event-id ID --user-id USER --chat-id CHAT
```

서비스는 **uvicorn worker 1개**로 운영한다. 재시작 시 이전 `queued/running` 이벤트와 문서 작성 작업을 `interrupted`로 바꾼다. 저장 도중 응답이 끊겨도 기존 `jobs.sqlite3`의 UUID를 확인한 뒤 재시도하므로 새 UUID로 중복 생성하지 않는다.

## 처음 설치하는 환경

1. 기존 `.env`의 Outline 키와 에이전트 토큰을 유지한다. `.env.example`을 참고해 별도 `RAG_DB_PASSWORD`에 새 무작위 값을 추가한다. 이 단계에서는 `RAG_ENABLED=false`로 둔다.
2. CPU 전용 이미지와 에이전트를 빌드한다.

```powershell
docker compose --profile rag build document-agent embedding-worker
docker compose --profile rag create embedding-worker
docker run --rm -e HF_HUB_OFFLINE=0 -e TRANSFORMERS_OFFLINE=0 --mount type=volume,source=outline-ai_rag-models,target=/models outline-ai-embedding-worker python install_rag_models.py
docker compose --profile rag up -d --wait rag-postgres embedding-worker
```

3. `.env`를 `RAG_ENABLED=true`로 바꾸고 `docker compose --profile rag up -d --wait document-agent`를 실행한다.
4. `rag_admin.py sync`와 `status`로 성공 여부를 확인한다.
5. 호스트 Python에서 `register_webui.py`를 실행하거나 컨테이너에서 다음 명령으로 기존 도구·필터 ID를 갱신한다.

```powershell
docker compose run --rm --no-deps -e WEBUI_URL=http://open-webui:8080 --volume './:/app' document-agent python register_webui.py
```

설치 때만 모델을 다운로드한다. 실행 중에는 고정 revision의 로컬 파일을 읽고 `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `local_files_only=True`를 적용한다. 파일이 없으면 서비스를 시작하지 않는다.

## 주요 설정

| 변수 | 기본값·효과 |
|---|---|
| `RAG_ENABLED` | `false`; 현재 설치는 `true` |
| `RAG_COLLECTION_NAME` | `로컬 AI 테스트`; 다른 범위로 변경하기 전 별도 평가 필요 |
| `RAG_COLLECTION_NAMES` | 쉼표로 구분한 색인 범위. 현재 `로컬 AI 테스트,개인 업무 보고`; 설정하면 단일 `RAG_COLLECTION_NAME`보다 우선 |
| `RAG_DB_PASSWORD` | 새 검색 DB 전용 비밀번호 |
| `RAG_SYNC_INTERVAL_SECONDS` | `300` |
| `RESEARCH_MAX_DOCUMENTS` | `10`; 한 번의 전체 조사·이어 하기에서 읽는 문서 수 |
| `RESEARCH_TIMEOUT_SECONDS` | `120`; 읽기 작업 전체 시간 상한 |
| `QWEN_TOKENIZER_PATH` | `/models/qwen/tokenizer.json` |
| `RAG_SOURCE_NAMESPACE` | `outline-local`; 서버 설정 + API 키 hash로 접근 주체 분리 |
| `RAG_EMBEDDING_PROFILE` | Compose에 고정된 E5 revision + `chunks-v1` |
| `RAG_DATABASE_URL` | 필요 시 별도 PostgreSQL 연결 문자열; 로그에 출력 금지 |
| `RAG_MIN_SIMILARITY`, `RAG_SCORE_WINDOW` | 코드 기본 `0.80`, `0.025`; 작은 고정 평가 세트용 초기 선별 기준 |

Qwen 입력은 최대 2,800, RAG 출력 800, 여유 496토큰이다. 기존 문서 작성 출력은 최대 1,600을 유지하되 그만큼 입력 예산을 줄인다. 토크나이저 파일이 없으면 UTF-8 바이트 수로 보수적으로 제한한다. 원문·JSON을 중간에서 조용히 잘라 보내지 않는다.

## RAG 끄기·되돌리기

`.env`에서 `RAG_ENABLED=false`로 바꾼 뒤:

```powershell
docker compose up -d --wait document-agent
docker compose --profile rag stop embedding-worker rag-postgres
```

기존 문자열 검색·전체 조사, 문서 작성·첨부·템플릿·저장 기능을 계속 사용할 수 있다. Qwen과 WebUI는 유지한다. `down -v`, 원본 DB 초기화, 사용자 문서 삭제는 복구 절차에 포함하지 않는다.

## 재검증

```powershell
docker run --rm --network none --mount "type=bind,source=$((Get-Location).Path),target=/app,readonly" outline-ai-document-agent python -m unittest test_template_layout test_document_workflow test_ux_backend test_receipt test_webui_grounding test_ux test_context_budget test_rag
```

실제 임베딩·DB 시험은 **전용 `rag_test` DB**에서만 실행한다. 처음 한 번 `docker compose exec -T rag-postgres createdb -U rag rag_test`로 만들고 다음 명령을 실행한다. 이 시험은 가상 Outline API를 쓰며 실제 문서를 수정하지 않는다.

```powershell
docker compose run --rm --no-deps -e RAG_DATABASE_NAME=rag_test -e DATA_DIR=/tmp/rag-tests --volume './:/app' document-agent python test_rag_integration.py
```

`verify_rag_live.py`는 명확히 표시한 가상 문서를 실제 시험 컬렉션에 생성한다. `webui` 인자는 3줄 메모 저장 시험도 수행한다. 읽기만 다시 확인하려면 `webui-read`를 사용한다. `verify_rag_cancel.py`, `verify_webui_cancel.py`는 시험 컬렉션 읽기·중지 경로를 검증한다.
