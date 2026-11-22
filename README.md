# Workhub · 업무 보고 데모

메신저에 쓴 한 줄 보고를 업무 항목에 연결합니다. 사용자가 초안을 확인하고 확정하면 문서의 업무 상태가 바뀌고 채널에 정해진 양식으로 보고가 남습니다.

현장실습에서 Rocket.Chat과 Outline을 연결하는 보고 흐름을 맡았습니다. Qwen으로 보고 문장을 정리하고, 서버에서 실제 업무와 완료 기준을 연결했습니다. 업무가 명확한 경우에는 모델 호출을 생략했고, 최종 제출 시점에는 권한과 문서 버전을 다시 확인하도록 구현했습니다.

이 저장소는 그중 **보고 해석과 확정 흐름**을 합성 데이터로 재구성한 공개 데모입니다. FastAPI를 사용하며, 문서와 채팅 채널은 로컬 SQLite로 모의 구현했습니다. 사용자 구분에는 데모용 HTTP 헤더를 사용합니다. 실습 프로젝트의 Rocket.Chat·Qwen 연동은 별도 테스트 환경에서 검증했습니다.

## 빠른 실행

Python 3.12에서 저장소를 내려받은 뒤 실행합니다.

```sh
python -m pip install -r requirements.txt
python -m workhub_demo.demo
```

```text
초안 · DEMO-101 · fixture
문서 · 버전 1 in_progress → 버전 2 done
채널 · [DEMO-101] 완료 · 목록 화면 검토를 마쳤습니다.
같은 초안을 다시 확정한 뒤 게시 수 · 1
```

기본 실행은 미리 정한 예제 문장을 처리하므로 모델 설치 없이 같은 결과를 확인할 수 있습니다. API에 직접 요청하려면 아래 명령으로 서버를 띄우고 [Swagger UI](http://127.0.0.1:8000/docs)를 엽니다.

```sh
python -m uvicorn workhub_demo.api:app --host 127.0.0.1
```

1. `POST /reports`에서 `X-Demo-User`에 `demo-editor`를 넣고 `{"text":"목록 화면 검토를 마쳤습니다."}`를 보냅니다.
2. 반환된 `id`로 `POST /reports/{draft_id}/confirm`을 호출합니다.
3. 같은 사용자로 `GET /tasks`와 `GET /channel`을 호출해 변경된 업무 상태와 게시된 보고를 확인합니다.

로컬 Ollama에서 Qwen으로 해석하려면 `WORKHUB_OLLAMA_MODEL`에 설치된 모델 태그를 지정한 뒤 서버를 실행합니다. 업무 ID와 상태가 명확한 입력(예: `DEMO-101 완료 | 목록 화면 검토를 마쳤습니다.`)은 Ollama를 호출하지 않습니다. [Ollama 구조화 응답 문서](https://docs.ollama.com/capabilities/structured-outputs)

## 구현에서 확인할 점

| 확인할 상황 | 구현과 검증 |
| --- | --- |
| 문장을 업무와 연결할 때 | 수정 권한이 있는 업무만 모델에 후보로 주고, 모델 응답이 후보 범위를 벗어나면 초안을 생성하지 않습니다. [해석 코드](workhub_demo/interpreters.py) |
| 업무 ID와 상태가 분명할 때 | 규칙으로 바로 해석합니다. 테스트에서는 모델로 요청이 전달되면 실패합니다. [테스트](tests/test_workflow.py) |
| 초안을 만든 뒤 권한이나 문서가 바뀌었을 때 | 확정 직전에 권한과 문서 버전을 다시 확인합니다. 확인에 실패하면 문서와 채널 모두 갱신하지 않습니다. [확정 처리](workhub_demo/workflow.py) |
| 같은 초안을 동시에 확정하거나 서버를 재시작한 뒤 다시 보낼 때 | 로컬 문서 변경과 채널 게시 기록을 한 트랜잭션에 저장하고, 같은 초안에는 기존 결과를 반환합니다. [테스트](tests/test_workflow.py) |

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

테스트에서는 Ollama의 HTTP 요청과 응답을 모의 처리합니다. 잘못된 모델 출력, 수정 권한 회수, 이전 문서 버전, 동시 확정·재시작 후 재요청, 게시 기록 저장 실패 뒤 재시도를 실제 SQLite 상태까지 확인합니다.
