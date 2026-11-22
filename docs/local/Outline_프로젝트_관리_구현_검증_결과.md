# Outline 프로젝트 관리 구현·검증 결과

- 완료일: 2026-09-30
- 적용 범위: 현재 PC의 `unified-work-assistant` 소스와 로컬 실행 서비스
- 기준 명세: [프로젝트 등록·연결 해제 구현 명세](Outline_프로젝트_등록_연결해제_구현_명세.md)
- 결과: Outline에서 프로젝트 등록·책임자 변경·연결 해제·재연결 가능. 검증한 기존 업무 흐름에서 회귀를 발견하지 않았다.

## 사용 방법

1. Outline의 **새 컬렉션**에서 **프로젝트로 연결 및 관리**을 선택한다. 기본값은 선택하지 않은 상태다.
2. 컬렉션 생성 후 열리는 설정창에서 책임자를 선택하고 **프로젝트 등록**을 누른다. 연결 완료 시 `업무 목록` 문서가 자동으로 준비된다. 여기서 취소하면 일반 컬렉션으로 남는다.
3. 기존 컬렉션은 메뉴의 **프로젝트 관리 설정**에서 등록·책임자 변경·연결 해제·재연결한다.
4. 연결 해제 기본값은 문서 보존이다. 고급 삭제 옵션을 직접 선택하면 확인한 업무 목록 문서와 하위 업무만 Outline 휴지통으로 이동한다. 컬렉션과 다른 문서는 보존한다.
5. Workhub 업무 보드의 **Outline에서 프로젝트 관리 ↗** 버튼도 같은 설정으로 이동한다.

Outline 로그인만으로 관리할 수 있으며, Workhub에 먼저 로그인할 필요가 없다. 관리 작업에는 현재 활성 업무 관리자 자격과 대상 컬렉션 접근 권한이 모두 필요하다.

## 주요 변경

### 후속 변경: 업무 목록 자동 생성 (2026-09-30)

- 책임자를 지정하는 기존 흐름은 유지했다. 프로젝트 연결을 확정할 때 최상위 `업무 목록`을 게시된 문서로 자동 생성한다.
- 이미 업무 목록이 있으면 내용·revision·문서 ID를 보존하여 재사용한다. 일반 컬렉션 생성만으로는 문서를 생성하지 않는다.
- 기본 해제 후 재연결은 같은 업무 목록을 사용한다. 고급 삭제로 업무 목록이 휴지통에 이동한 뒤의 재연결에서는 새 업무 목록을 준비한다.
- 연결 시 문서 작성 권한을 확인한다. 생성 결과가 불확실하면 연결 성공으로 표시하지 않으며, 저장된 요청과 문서 ID로 재시도한다.
- 기존에 연결 완료된 모든 프로젝트를 일괄 수정하지는 않는다. 이후 새 연결·재연결에 적용한다.
- 실제 검증에서 새 컬렉션에 대한 Outline의 10초 권한 목록 캐시가 문서 목록을 비우는 경우를 발견했다. 특정 컬렉션 조회는 최신 권한 목록을 사용하도록 수정하여 즉시 생성·재사용 경로를 검증했다. 관리 패치는 현재 12개 원본 파일을 포함한다.
- 단위·회귀 테스트 165개 통과 (`reports/outline-auto-task-list-tests.txt`; 로컬 자료). 자동 생성, 재연결·요청 재전송 중복 방지, 응답 유실 후 재시작 복구, 문서 작성 권한 거부를 포함한다.
- 실제 브라우저·API 확인 4개 항목 통과 (`reports/outline-auto-task-list-live.json`; 로컬 자료): 일반 컬렉션 문서 미생성, 연결 시 문서 자동 생성, 재연결·재전송 시 동일 ID, 기존 문서 내용·revision 보존. 이번 실행이 만든 검증 컬렉션만 연결 해제 후 제거했다.
- 로컬 Outline·Workhub 이미지를 다시 빌드하고 적용했다. 아래 최초 적용 이미지 ID와 11개 파일 검증 기록은 최초 구현 당시 기록이다. 후속 빌드 기록은 Outline (`reports/outline-auto-task-list-outline-build.txt`; 로컬 자료), Workhub (`reports/outline-auto-task-list-build.txt`; 로컬 자료)에 있다.

|영역|구현|
|---|---|
|Outline 화면|기존 생성창 체크박스, 생성 후 설정 모달, 컬렉션 메뉴, 직접 접근 페이지, 해제 확인·고급 삭제 옵션|
|인증|Outline 서버가 현재 로그인 사용자를 확인하고 Workhub 내부 API에 서명 요청. 별도 공유 키·시각·nonce·계정 매핑·현재 자격 검사|
|상태 관리|기존 컬렉션 ID 유지, revision 충돌 검사, 영속 요청 영수증, 미완료 작업 재개, 동기화 상태|
|생성 중복 방지|컬렉션 생성 요청 ID를 서버에서 처리하여 같은 요청을 동시에 보내도 같은 컬렉션 반환|
|해제 보호|기본 해제는 문서 유지, 업무 캐시·봇 프로젝트 문맥 정리, 이전 보고 확정 차단|
|선택 삭제|저장된 업무 목록 ID·현재 위치·삭제 정책 재검사, 응답 유실 후 재시도와 다른 현재 관리자의 복구 지원|
|Workhub 전환|프로젝트 관리 버튼을 Outline 링크로 전환, 활성화 중 구형 변경 API는 409 전환 안내|
|빌드·운영|설치 버전 고정, 원본 대비 11개 파일 패치, 이미지 빌드 절차, 백업과 복구 안내|

주요 Workhub 파일은 `src/workhub/project_service.py`, `outline_bridge.py`, `main.py`, `store.py`, `outline.py`, `permissions.py`, `static/projects.js`다. Outline 변경은 [통합 소스·빌드 안내](integrations/outline/README.md)와 `integrations/outline/patches/0001-workhub-project-management.patch`에서 관리한다.

## 검증 결과

|검증|결과|기록|
|---|---|---|
|Python 단위·회귀 테스트|161개 통과|로그 (`reports/outline-project-unit-tests.txt`; 로컬 자료)|
|실제 SSO·브라우저·API 통합 검증|86개 assertion 통과, 브라우저 오류 없음|결과 (`reports/outline-project-live-results.json`; 로컬 자료)|
|추가 경계 상황 검증|14개 assertion 통과|결과 (`reports/outline-project-edge-results.json`; 로컬 자료)|
|최종 Outline 전체 TypeScript 검사|`yarn tsc --noEmit` 종료 코드 0|기록 (`reports/outline-project-final-types.txt`; 로컬 자료)|
|수정 핵심 TS 파일 lint|경고 0, 오류 0|로그 (`reports/outline-project-final-lint.txt`; 로컬 자료)|
|Outline·Workhub 이미지|소스 빌드 및 현재 로컬 서비스 적용 완료|Outline 빌드 (`reports/outline-project-build.txt`; 로컬 자료), Workhub 빌드 (`reports/outline-project-workhub-build.txt`; 로컬 자료)|
|패치 재현성|원본 archive SHA-256 확인, 깨끗한 원본에 패치 적용, 11개 파일 텍스트 일치|로그 (`reports/outline-project-patch-verification.txt`; 로컬 자료)|
|서비스|16개 실행 중, healthcheck가 있는 15개 모두 healthy|상태 (`reports/outline-project-services.json`; 로컬 자료)|

161개 테스트에는 기존 연결 해제·책임자·권한·보안·문서 계층·통계·보고·보고 복구·보고 대상·보고 확정 관련 회귀 테스트가 포함된다. 새 서비스는 요청 재전송, 변경된 요청 본문, revision 충돌, 기본 해제 보존, 선택 삭제 응답 유실, 재시작 후 영수증 복구, 다른 관리자의 재개, 이동한 문서 삭제 차단, 서명 위변조·재사용, 다른 팀 거부 등을 검증했다.

실제 환경에서는 다음 흐름을 검증했다.

- Outline만 로그인한 관리자 → 컬렉션 생성 → 설정 모달 → 프로젝트 등록.
- 실제 업무 생성 → 보고 변경 제안 → 확정 → 통계 조회.
- 기본 해제 → 원문 보존 → 재연결 → 기존 ID 유지.
- 고급 옵션 해제 → 업무 목록과 하위 업무 휴지통 이동 → 일반 문서 보존.
- 일반 직원의 관리 요청 및 브라우저의 사용자 정보 위조 거부, 공개 내부 API 차단.
- 동시 컬렉션 생성 중복 방지, 등록 응답을 브라우저에서 유실시킨 후 결과 복구.
- 책임자 미지정·변경, 동시 변경 충돌, 해제 취소, 좁은 화면의 설정 영역 넘침 방지.
- 해제 전 생성한 보고의 후속 확정 차단, Workhub 관리 버튼의 Outline 이동.

86개와 14개는 개별 assertion 수이며 100개의 서로 독립된 사용자 시나리오를 뜻하지 않는다. 시험 중 나타난 Workhub 진입 테스트 실패는 초기 비동기 로딩이 끝나기 전에 탭을 클릭한 자동화 순서 문제였으며, 초기 조회 완료를 기다리도록 수정한 뒤 통과했다.

### 기존 데이터와 연결 상태

최종 대조 결과 (`reports/outline-project-final-health.json`; 로컬 자료):

- 기존 등록 프로젝트 **10개**: ID 목록 동일.
- 기존 문서 **49개**: 내용 SHA-256 모두 동일.
- 기존 활성 업무 **23개**: 업무 ID와 컬렉션 ID 동일.
- 통계 API 정상, Workhub 문서 동기화 정상.
- 검색 확인 대상 프로젝트: 색인 `ready`, 문서 8개, 실패 0개.
- Rocket.Chat 봇: 연결 상태 정상, 연결된 방 3개.

실제 쓰기·삭제 검증은 `[검증]` 이름의 컬렉션에서 수행했다. 검증용 컬렉션과 문서는 확인용으로 남아 있으며 최종 Workhub 연결 레지스트리에는 포함되지 않는다. 원래 사용자 프로젝트를 해제하거나 원문을 변경하지 않았다.

## 적용 버전과 복구

- Outline: **1.10.0**, upstream commit `65be53c3eb093a535ce260eb2f2da897bb07a29e`.
- Outline 이미지: `unified-work-assistant/outline:project-management-20260930`.
  - 로컬 image ID: `sha256:e83c26a3cc24180a25f84e41081f3a7d2fa9f40cc7a877085ea49c327a87ad8e`.
- Workhub 이미지: `unified-work-assistant/workhub:project-management-20260930`.
  - 로컬 image ID: `sha256:614ed54b15b48d113eb7ceca746873c2e7fc3240d1c52f63a7067de018702aef`.
- 두 서비스의 `OUTLINE_PROJECT_MANAGEMENT_ENABLED=true` 적용.
- 실제 비밀 설정은 `.local/compose.json`에만 보관하며 보고서에 기재하지 않는다.
- 변경 전 DB·실행 설정 백업: `backups/pre-outline-project-management-20260930/`.
- 이전 Outline·Workhub 이미지 보존. 복구 시 [통합 안내의 복구 절차](integrations/outline/README.md)를 따른다. 새 데이터가 있는 DB에 백업을 무조건 덮어쓰지 않는다.

빌드와 전체 타입 검사를 함께 진행하던 중 Docker Desktop이 응답하지 않아 엔진을 재시작했다. 데이터 초기화 없이 서비스를 복구했으며 이후 최종 데이터 대조·서비스 상태 확인을 통과했다. 전체 타입 검사에 1.8GB Node heap을 지정한 시도는 메모리 부족으로 실패했지만, 빌드와 분리하고 heap 2.8GB·컨테이너 메모리 3.2GB 한도를 적용한 최종 검사는 통과했다.

## 명세 대비 결정과 확인 범위

- 생성·컬렉션 메뉴는 Outline 기본 모달을 사용한다. 직접 URL `/workhub/projects/:collectionId`와 Workhub 링크는 독립 설정 페이지로 열어 새로고침·직접 접근이 가능하게 했다.
- 활성화 상태의 변경은 새 공통 서비스가 처리한다. 이전 Workhub 구현은 기능 플래그를 끈 경우의 복귀 경로로 남겼으며, 활성화 중 구형 변경 API는 새 서비스에 자동 위임하지 않고 전환 안내를 반환한다.
- UI의 동기화 완료는 프로젝트 등록 정보 전달 상태다. 전체 벡터 색인 완료 상태와 구분하며, 최종 검사에서 별도로 검색 색인 상태를 확인했다.
- 실제 SSO 테스트는 관리자와 일반 직원으로 수행했다. 퇴사 처리·중간 권한 철회·모든 삭제 정책 조합·실제 이미지 롤백을 각각 운영 데이터로 재현한 것은 아니다. 일부 실패·재시작 경로는 격리된 단위 테스트로 검증했다.
- Rocket.Chat에 새 메시지를 보내는 종단 간 시험은 이번에 수행하지 않았다. 봇 연결 상태와 관련 보고 회귀 테스트를 확인했다.
- 검색은 프로젝트 등록 동기화와 대표 프로젝트의 색인 상태를 확인했으며, 모든 프로젝트에 대한 LLM 답변 품질·부하 시험은 범위에 포함하지 않았다.
- `deployment/` 배포 묶음과 다른 PC·서버는 이번 변경 대상이 아니다. 현재 로컬 소스·이미지·실행본에 적용되었다.

## 검증 재실행

프로젝트 폴더에서 실행한다. Docker 명령에는 로컬 Docker 접근 권한이 필요하다.

```powershell
docker run --rm --entrypoint python -e PYTHONPATH=/app -e PYTHONDONTWRITEBYTECODE=1 -v "${PWD}/src/workhub:/app/workhub:ro" -v "${PWD}/ops:/tests:ro" unified-work-assistant/workhub:1.0 /tests/test_outline_project_management.py

# Playwright가 설치된 모듈 경로를 사용한다.
$env:PLAYWRIGHT_MODULE='<workspace>'
node ops/verify_outline_project_edges.mjs
node ops/verify_outline_project_final.mjs
python ops/verify_outline_source_patch.py
```

브라우저 스크립트는 기존 비공개 테스트 계정 설정을 사용하고 검증 데이터를 변경한다. `verify_outline_project_management.mjs`는 최초 생성부터 고급 삭제까지 수행하는 전체 흐름용이며, 이미 삭제된 이전 fixture를 그대로 사용해 반복하지 않는다. 일상 재점검은 경계 검증과 최종 읽기 검증을 사용한다.
