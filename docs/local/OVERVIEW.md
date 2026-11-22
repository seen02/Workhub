> 아래 실행 명령은 저장소의 `unified-work-assistant/` 폴더를 기준으로 합니다.

# Workhub 통합 AI 업무 비서

Rocket.Chat의 채팅과 Outline의 문서를 연결하는 업무 지원 시스템입니다. Workhub 연동 코드와 Outline 수정 패치를 함께 보관합니다.

## GitHub 소스 사본 안내

이 저장소는 기술 검토용 공개 소스 사본입니다. 업로드에는 현재 작업 소스·설정 예시·개발 문서·Outline 변경 패치를 포함하며, 실제 자격증명·DB·문서·채팅·첨부·백업·컨테이너 이미지·모델·로컬 화면 캡처는 제외합니다. 기존 사내 Git 저장소의 이력과 원격 설정은 이 사본에 포함하지 않습니다.

현재 `compose.yml`은 업로드하지 않는 `.local/compose.json`을 참조합니다. 따라서 이 사본만 복제해 `start.ps1`을 실행할 수 있는 완성된 설치 패키지는 아닙니다. `deployment/`의 도구와 문서는 과거의 별도 배포 묶음을 전제로 하며, 그 묶음의 비공개 설정·이미지·복원 데이터는 포함하지 않습니다. 아래 기존 개발 기록의 `reports/`, `output/`, 백업 및 로컬 경로도 업로드 대상에서 제외했습니다.

## 라이선스와 출처

저장소 전체에 단일 MIT 또는 Apache 라이선스를 적용하지 않습니다. 프로젝트별 작성물에는 이번 업로드로 새로운 이용 허락을 부여하지 않고 기존 권리 관계를 유지합니다. Outline 1.10.0 원본·수정·파생 부분에는 원래 **Business Source License 1.1**이 적용됩니다. Rocket.Chat은 Community 영역의 MIT 조건과 Enterprise의 별도 조건을 구분합니다.

- [전체 적용 범위](../../LICENSE)
- [제3자 소프트웨어 및 출처 고지](../THIRD_PARTY_NOTICES.md)
- [라이선스 안내](../LICENSING.md)
- [Outline 원문 라이선스](../../unified-work-assistant/integrations/outline/LICENSE) · [변경 내용과 복원 방법](integrations/outline/MODIFICATIONS.md)

Rocket.Chat의 메시징, Outline의 문서 편집·실시간 협업 등은 기존 플랫폼의 기능입니다. 이 프로젝트는 서비스 연동과 업무 등록·보고 반영·칸반·진행 통계 등의 확장을 구현했습니다. 기존 보고·문서 비서의 출처도 아래 소스 표와 제3자 고지에 명시합니다.

---

2026-10-26 일일 업무보고 편의 기능을 로컬에 적용했습니다. 날짜별 접기·펼치기, 날짜 전체의 하위 문서 이동, 오늘 보고 생성·중복 방지, 미완료 항목 선택 이월, 작업자 필터를 제공합니다. Outline과 Workhub를 `daily-reports-20261026` 이미지로 다시 빌드·교체했고 데이터 볼륨은 유지했습니다. `[체험] 일일 업무보고` 컬렉션에 제공된 2일치 예시와 오늘 보고 생성용 별도 문서를 만들었습니다. 사용 링크, 검증 결과, 재빌드·복구 명령은 반영 기록 (`reports/daily-reports-20261026.txt`; 로컬 자료)에 있습니다. `deployment/`의 배포 묶음은 이번 로컬 적용과 별개입니다.

2026-10-23 후속 수정: 선택 도구 모음에 등록 동작을 전달하는 연결을 문서 범위 컨텍스트로 변경하고, 읽기 화면과 늦은 초기화에 대한 실제 에디터 회귀 테스트를 추가했습니다. 이번 후속 수정은 Outline만 재빌드하면 됩니다. 이미지 빌드와 Compose 실행은 수행하지 않았습니다. 상세 기록은 `reports/selection-task-display-fix-20261023.txt`에 있습니다.

2026-10-23 선택 내용 업무 등록(소스 반영): 게시된 문서의 텍스트를 선택한 뒤 도구 모음의 `업무로 추가`를 누르면 같은 프로젝트의 업무 목록에 새 업무를 등록할 수 있습니다. 업무명·내용을 미리 채우고 출처 링크·발췌를 함께 저장합니다. 원문 조회·대상 생성 권한과 저장된 선택 내용을 서버에서 검사하며, 원문 문서는 수정하지 않습니다. 로컬·VM 배포용 소스를 함께 반영하고 재현 패치를 갱신했습니다. 이미지 빌드·전송·Compose 실행은 수행하지 않았습니다. 적용 명령과 검증 범위는 반영 기록 (`reports/selection-task-20261023.txt`; 로컬 자료)을 확인하세요.

2026-10-20 본문 목차 블록 소스 반영: 로컬 테스트 기준은 이 `unified-work-assistant` 폴더입니다. 문서에서 `/목차` 또는 `/toc`로 자동 갱신되는 목차를 삽입합니다. `integrations/outline`의 실제 소스와 재현 패치를 갱신했으며 Docker 이미지 생성·컨테이너 재실행은 수행하지 않았습니다. 명령과 검증 결과는 목차 블록 반영 보고서 (`reports/toc-block-20261020/report.txt`; 로컬 자료)를 참고하세요. 배포용 `output/outline-authentik`과 목차 코드 15개가 일치합니다.


2026-10-19 로컬 반영: `output/outline-authentik`의 프로젝트 관리 권한·직원 완료 기준 작성 변경을 병합하고 Outline·Workhub 컨테이너를 `outline-authentik-20261019` 이미지로 교체했습니다. 기존 Rocket.Chat·Ollama·문서 비서·검색·포털과 데이터는 유지합니다. 접속·테스트 순서·검증 결과·복구 방법은 로컬 테스트 안내 (`reports/outline-authentik-local-20261019.md`; 로컬 자료)에 있습니다.

2026-10-12 인증 업데이트: Rocket.Chat 봇·Outline 연동·문서비서는 별도 포털 로그인 기록 대신, 요청한 서비스의 인증된 계정과 Authentik의 현재 계정 상태·그룹을 확인합니다. 사용자별 Outline 권한과 포털 자체의 로그인·CSRF 검증은 유지합니다. Authentik 디렉터리 연결과 직원 동기화가 필요하며, 미연결·중복·변경 계정은 거절합니다. 각 서비스의 유효한 로그인 상태가 기준이고, 전체 서비스 로그아웃은 별도의 OIDC 로그아웃 연동 설정에 따릅니다.

이 변경은 소스 코드에 반영한 것입니다. 실행 중인 개인용 컨테이너와 DB는 자동 변경하지 않습니다. 로컬 반영 시 `ops/Dockerfile.service-sso`로 새 Workhub 이미지를 빌드하고 기존 Compose의 Workhub 이미지 참조를 변경해야 합니다. Open WebUI 도구는 DB에 저장되므로 `src/document-agent/webui_bridge.py`와 `ops/update_service_sso_webui.py`를 Open WebUI 컨테이너에 복사한 뒤, 기존 관리자 이메일을 지정하여 갱신합니다. 도구의 인증 함수와 오류 안내만 갱신하며 기존 설정·권한·대화는 유지합니다. `--apply`를 생략하면 변경 대상만 확인합니다.

```sh
# 프로젝트 루트에서 새 개인용 이미지를 빌드합니다.
docker build --network none -f ops/Dockerfile.service-sso -t unified-work-assistant/workhub:service-sso-20261012 .
# 두 파일을 Open WebUI 컨테이너 /tmp에 복사한 뒤 해당 컨테이너 안에서 실행합니다.
python /tmp/update_service_sso_webui.py --bridge /tmp/webui_bridge.py --admin-email admin@example.com --apply
```

`admin@example.com`은 기존 초기 관리자 예시입니다. 실제 WebUI 관리자 이메일이 다르면 바꿉니다. Workhub 이미지와 WebUI 도구 코드는 함께 갱신해야 하며, 코드만 바꾸거나 document-agent 컨테이너만 재시작해서는 저장된 도구가 갱신되지 않습니다. Open WebUI에 비밀번호로만 가입한 계정은 Authentik 로그인으로 연결해야 합니다. Authentik의 OIDC 사용자 식별 설정은 기존 `user_uuid`를 유지합니다.

현재 개발·로컬 실행의 기준 폴더입니다. 배포 준비본은 [deployment](deployment/README.md), 전체 작업 폴더 안내는 [상위 README](../../README.md)를 확인하세요. **20261007-1**은 개발 ZIP·실행 이미지·데이터를 함께 고정한 배포 기준입니다. 그 이후 보고 지연 수정은 현재 소스와 로컬 Workhub에 추가 적용했습니다. 적용 내용과 검증·복구는 [보고 성능 기록](보고_성능_및_신뢰성_개선_명세.md)을 확인하세요. 고정 배포 묶음에는 이 추가 수정이 포함되지 않습니다.

## 남겨둔 문서

사용·시연 가이드, 초기 PoC 단계별 안내, 중복된 과거 개선 기록은 정리했다. 현재 작업 기준과 운영·복구 자료, 재발 방지에 필요한 오류 수정 기록을 유지한다.

| 목적 | 문서 |
|---|---|
| Outline 진행 통계 화면의 기능 및 검증 | [구현 명세](Outline_진행_통계_대시보드_구현_명세.md) · [구현 및 검증 결과](Outline_진행_통계_구현_검증_결과.md) |
| Outline에서 프로젝트 등록·책임자 변경·연결 해제·재연결 구현 계획 | [Outline 프로젝트 관리 구현 명세](Outline_프로젝트_등록_연결해제_구현_명세.md) |
| Outline 프로젝트 관리 로컬 적용·사용 방법·검증 결과 | [구현·검증 결과](Outline_프로젝트_관리_구현_검증_결과.md) · [소스·빌드·복구](integrations/outline/README.md) |
| 1~4번 기능 개편 범위와 진행 상태 | [기능 개편 구현 명세](기능_개편_구현_명세_1-4.md) |
| 보고 속도·중복 조회·AI 호출·처리 상태 개선 순서 | [보고 성능 및 신뢰성 개선 명세](보고_성능_및_신뢰성_개선_명세.md) |
| 채팅에서 전체 개인 업무·기한 초과·완료 기준 조회 | [구현·검증 기록](내_업무_조회_구현_계획.md) · [상세 시연 가이드](내_업무_시연_가이드.md) |
| 매일 오전 9시 개인 마감 알림·받기/끄기 | [마감 알림 구현·검증 결과](마감_알림_구현_검증_결과.md) |
| 최근 보고 업무 오인식 수정·검증 | 업무 인식 복구 기록 (`reports/report-task-scope-repair-20260930.md`; 로컬 자료) |
| 보고 전송·문서 반영 통합 검증 | 통합 검증 기록 (`reports/report-combined-validation-20260929.md`; 로컬 자료) |
| 계정 동기화·입퇴사·인수인계 | 계정 관리 구현 결과 |
| 프로젝트·담당자·검색 접근 권한 | 권한 구현 결과 |
| 업무 문서 구조·연결 해제·통계 계산 | [문서 구조](HIERARCHY-REPORT.md) · [연결 해제](PROJECT-UNLINK-REPORT.md) · [통계](ANALYTICS-REPORT.md) |
| 운영·백업·복구·접속 설정 | 운영 · [Nginx](NGINX-LOCAL.md) |
| 최신 개발본·고정 이미지·개발 빌드 | [개발본 안내](development/README.md) · [개발 버전](../../unified-work-assistant/development/version.json) |
| 배포 묶음의 설치·복원·포함 버전 | [배포 README](deployment/README.md) · [배포 상태](deployment/PREPARATION_REPORT.md) |
| 화면 설계 기준 | [DESIGN.md](DESIGN.md) |

날짜가 있는 검증 기록은 해당 시점의 결과다. 로컬 실행본과 배포 묶음의 적용 버전은 구분한다.

## 시스템을 이해하는 순서

1. **Authentik**에서 회사 계정과 서비스 이용·관리자 자격을 관리합니다.
2. **Outline**의 컬렉션을 Workhub 프로젝트에 연결합니다. 실제 프로젝트 접근 권한은 Outline 직접·그룹 권한을 따릅니다.
3. **Outline**의 최상위 **업무 목록**에서 **＋ 새 업무**로 업무를 등록합니다. 관리자는 완료 기준과 담당자를 지정하고, 일반 직원은 본인 업무를 등록합니다. 칸반과 진행 통계도 Outline에서 사용합니다.
4. 담당자가 **Rocket.Chat의 통합 업무 비서 개인 대화방**에서 여러 업무를 한 번에 보고하면 업무명·완료 기준별 통합 초안을 제시합니다. 명확한 보고는 직접 해석하고 모호한 표현은 기존 검색·AI 경로로 확인합니다. Workhub의 기존 단일 업무 보고도 유지합니다.
5. DM의 **보고 및 반영**을 누르고 채널·토론방을 고르면 보고 게시와 Outline 기존 기준 갱신·없는 본인 업무 생성을 함께 처리합니다. 채널 선택 화면의 **뒤로 가기**로 실행 없이 돌아올 수 있습니다. 실행 전에는 초안 수정·취소가 가능합니다.
6. **진행 통계**에서 프로젝트별·전체 프로젝트 진행률과 담당 업무를 확인합니다. 자료 검색은 허용된 문서를 RAG로 찾아 답변과 출처를 제공합니다.

업무의 원본은 Outline입니다. Workhub의 SQLite는 현재 업무 사본·관측 이력·초안·중복 방지·로그인 세션을 저장합니다. 업무를 여러 번 보고해도 같은 문서 ID를 갱신하므로 업무 수가 늘어나지 않습니다. 이력은 주기적으로 관측한 버전이며 모든 중간 편집을 기록하는 감사 로그는 아닙니다.

기본 실행은 16개 서비스입니다. 기존 보고 PoC의 `report-worker`, `report-review`, `reportdb`는 `legacy-report` 선택 프로필에만 남아 있습니다. 현재 업무 봇은 `src/workhub`의 구현을 사용합니다.

|소스|역할|
|---|---|
|`src/workhub`|업무 보드·통계·권한·계정·보고·Rocket.Chat 봇|
|`src/document-agent`|Outline 문서 비서·RAG·Open WebUI 연동. `Outline/local-ai`에서 가져와 확장|
|`src/report-agent`|기존 보고 양식·관련 코드와 이전 PoC 보관. 원본은 `ai-agent-main/ai-agent-main`|

## 현재 상태와 추가 참고

- `deployment/`는 **20261007-1**입니다. 이전 버전은 `deployment-archive/20260928-1/`, `20260922-1/`, `20260921-1/`에 보관했습니다.
- 2026-10-07까지 적용한 프로젝트 관리·진행 통계·새 업무 등록·칸반·검색·내 업무 조회·보고 초안 개선을 최신 개발 ZIP과 배포 묶음에 포함했습니다.
- 로컬 원본 컨테이너·데이터를 유지했고, 별도 배포 복원본에서 검증했습니다.
- 존재하지 않는 예전 RAG 대상 `통합 업무`를 제거한 설정 보정은 배포본과 현재 로컬에 모두 반영했습니다.
- 현재 실행 이미지 16개와 데이터 저장소 14개를 보존한 배포본 **20261007-1**을 별도 저장소에 복원·기동해 검증했습니다. 최신 Workhub 테스트 436개와 배포 도구 테스트 9개를 통과했습니다.
- 실제 회사 서버 주소·HTTPS·SMTP·백업 예약은 환경에 맞춰 설정해야 합니다.
- [업무 목록 문서 계층](HIERARCHY-REPORT.md), [프로젝트 연결 해제](PROJECT-UNLINK-REPORT.md), [화면 디자인](DESIGN.md)은 별도 참고 문서입니다.
- [초기 권한 설계](OUTLINE-PROJECT-AUTHORIZATION-DESIGN.md)는 설계 의도 참고용이며 현재 구현 상태를 판정하는 문서는 아닙니다.

## 실행과 중지

이 폴더에서 PowerShell로 실행한다.

```powershell
./start.ps1
./stop.ps1
docker compose ps
docker compose logs --tail 50 document-agent
```

접속 주소:

- 통합 업무 포털·통계: http://workhub.test
- Outline: http://outline.workhub.test
- Outline 문서 채팅: http://ai.workhub.test
- 문서 비서 API: http://localhost:3002 (브라우저 방문은 Workhub로 이동, 사용자 검색은 인증된 허브·문서 채팅 경로 사용)
- Rocket.Chat: http://rocketchat.workhub.test (Authentik로 로그인)
- Authentik: http://authentik.workhub.test

위 주소는 이 PC의 hosts에 등록했습니다. 기존 localhost:8004/8090/3001/3000/9000은 해당 새 주소로 이동합니다. 인증서 설치 없이 HTTP로 사용하며, 443/9443 포트는 제공하지 않습니다. 다른 PC와 실제 서버 접속은 [Nginx 안내](NGINX-LOCAL.md)를 참고하세요.

기존 report-worker·review·reportdb는 `legacy-report` 프로필에만 있다.
이전 PoC의 보고 DB 중심 기능이며 Outline 통합 기능이 아니다. 기본 실행에서는 켜지 않는다.

## 파일과 데이터

- `src/document-agent`: Outline 비서 소스 복사본
- `src/workhub`: 새 통합 포털·SSO·봇·Outline 업무·통계 구현
- `src/report-agent`: Rocket.Chat 업무비서 소스 복사본
- `runtime/document-agent`: 기존 초안·첨부 사본·작업/조사 기록
- `runtime/workhub`: 업무 통계 사본·관측 이력·개인 변경 제안·SSO 세션 SQLite
- `runtime/authentik`: 인증 서비스 파일·템플릿·인증서
- `.local/compose.json`: 기존 자격증명을 보존한 실제 실행 설정. 비공개이며 Git에서 제외.
- `.local/migration*.json`: 이전 대상과 파일 해시 검증 결과
- `.local/snapshot-*.json`: 이전 전후 DB 레코드 수
- `backups/pre-migration`: Outline·Authentik·RAG의 DB 덤프
- Docker의 `unified-work-assistant_*` 볼륨: 이전된 문서·첨부·채팅·DB·모델

비밀키·원문·채팅을 포함한 .local, runtime, backups는 외부 공유 대상이 아니다.
기존 폴더와 기존 볼륨은 복구용으로 남아 있다. 새 데이터는 새 프로젝트에 기록된다.

## 복구

```powershell
./rollback.ps1
```

새 프로젝트를 정지한 뒤 기존 컨테이너를 다시 시작한다.
이 작업은 이전 시점의 상태로 돌아간다. 이전 이후 새 프로젝트에 작성한 내용은 자동 역이전하지 않는다.
복구 전에 새 데이터를 별도로 백업해야 한다. 기존 시작 스크립트와 새 시작 스크립트를 동시에 사용하지 않는다.

## 리소스 방침

WSL 메모리 6GB 유지. Ollama는 모델 1개·추론 1개만 허용한다.
서버 기본 유지 시간은 60초다. 기존 문서 비서는 요청에서 5분을 지정하므로 해당 요청은 5분 유지된다.
모델 파일은 보존하며, Gemma를 추가 적재하지 않는다.
동시 서비스 기동 확인은 소규모 로컬 개발 준비 확인이며 회사 운영 부하 검증이 아니다.

Rocket.Chat 초기 관리자 ID는 `poc-admin`이다. 초기 자격증명은 생성 도구가 사용하는
`src/report-agent/rocketchat/.local/credentials.json`의 admin 항목에 보관되어 있다.
별도 비밀번호 복사 파일은 만들지 않는다. 이 계정은 복구·프로비저닝용으로 유지한다.
일반 사용자와 테스트 관리자는 Authentik SSO로 로그인한다. 계정 그룹과 세션 회수 범위는 OPERATIONS.md에 설명했다.

## Rocket.Chat 업무 버튼 스타일

`ops/workhub-chat-buttons.css`는 업무 비서의 첨부 버튼만 대상으로 한다.
업무 다시 선택은 회청색(←), 프로젝트 변경은 보라색(↖), 보고 확정은 초록색,
초안 취소는 붉은색이다. 업무·프로젝트 이동 버튼에는 이동 범위 설명도 표시한다.
기존 메시지에는 색상만 반영되며 새 화살표와 설명은 새로 받은 메뉴부터 표시된다.

스타일을 수정하거나 새 Rocket.Chat 환경에 반영할 때 실행한다:

```powershell
node ops/configure_chat_buttons.mjs
```

설정 도구는 `theme-custom-css`의 Workhub 구간만 교체하며 다른 사용자 정의 CSS는
유지한다. 변경 전 값은 `.local/chat-css-before-*.txt`에 보관한다.
사용자는 Rocket.Chat을 새로고침하고 봇에게 `현재 업무` 또는 `프로젝트`를 보내면 된다.
웹과 같은 화면을 사용하는 데스크톱 클라이언트에 적용되며, 모바일 네이티브 앱의
버튼 색상은 앱 렌더러에 따라 다르다. 화살표·이동 범위 설명은 메시지 자체에 포함된다.
관련 동작 회귀 검증: `python -m unittest workhub.test_chat_ui workhub.test_cancellation workhub.test_report_recovery`.
