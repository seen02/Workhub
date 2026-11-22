# Outline 프로젝트 관리 통합

2026-10-27 비밀번호 변경 버튼: 개인 설정 → 프로필의 **비밀번호 변경**으로 새 탭에서 Authentik 변경 화면을 엽니다. 기존 OIDC 주소를 자동 사용하고 만료된 Authentik 세션은 로그인 후 변경 화면으로 이동합니다. 로컬 적용 이미지는 `unified-work-assistant/outline:password-change-20261027`이며 새 환경변수·DB 마이그레이션·Workhub 수정은 없습니다. 빌드는 `ops/Dockerfile.outline-password-change-local`, 로컬 이미지 선택·복구는 `python ops/apply_outline_password_change_local.py --apply` / `--rollback --apply`, 읽기 전용 실서비스 검증은 `node ops/verify_outline_password_change.mjs`를 사용합니다. 검증은 변경 폼까지만 열며 실제 비밀번호를 변경하지 않습니다.

2026-10-26: 일일 업무보고의 날짜별 보기·접기 상태 저장, 작업자 필터, 오늘 양식 생성·날짜 중복 방지, 미완료 업무 선택 이월·중복 제외, 날짜별 보고의 원자적 하위 문서 이동을 구현하고 로컬 Docker 서비스에 적용했습니다. 게시된 문서의 날짜 제목과 작업자 표를 감지하며 원문 편집 화면을 유지합니다. 서버는 현재 접근·편집·생성 권한을 검사하고, 부모 행 잠금·트랜잭션·문서 버전 검사를 사용합니다. 표·서식·첨부는 Markdown 재파싱 없이 구조 그대로 이동하고 협업 상태와 표준 문서 이벤트를 갱신합니다. 새 파일 6개를 포함한 92개 파일의 재현 패치를 검증했습니다. 예시 링크와 빌드·복구 방법은 로컬 반영 기록 (`../../reports/daily-reports-20261026.txt`; 로컬 자료)을 확인하세요.

2026-10-23: 문서 선택 도구 모음에 `업무로 추가`를 연결했습니다. 같은 컬렉션에 등록된 업무 목록을 조회하고 기존 새 업무 창을 재사용합니다. 선택 텍스트·출처 링크를 보존하고 원문 및 생성 위치 권한을 다시 확인합니다. 원본 위치는 바꾸지 않으며 표·이미지 단독 선택, 초안·공유·이력 화면은 대상에서 제외합니다. 로컬 및 VM 소스와 재현 패치를 갱신했고 빌드·배포는 하지 않았습니다. 검증 및 로컬 적용 명령 (`../../reports/selection-task-20261023.txt`; 로컬 자료)의 전용 Dockerfile을 사용하세요. 예전 중간 빌드 이미지를 요구하는 기존 Dockerfile과 구분합니다.

## 2026-10-20 본문 목차 블록

로컬 테스트 기준은 `unified-work-assistant`이며 배포 기준은 `output/outline-authentik`입니다. 본문 일반 문단에서 `/목차` 또는 `/toc`로 목차 블록을 삽입합니다. 문서 전체 제목 1~4단계, 제목 번호, 제목 수정·삭제·이동을 자동 반영합니다. 표 안 제목과 문서 자체 제목은 제외하고, 목차 링크로 접힌 토글 안의 제목도 펼쳐서 이동합니다. 읽기·공유 화면과 저장·복사·Markdown/HTML 내보내기를 지원합니다.

`export_patch.py`의 관리 대상에 목차 관련 15개 파일을 추가하고 재현 패치를 갱신했습니다. 기본 Compose는 기존 `.local/compose.json`의 이미지 태그를 사용하므로 프로젝트 최상위에서 아래 명령으로 해당 Outline 이미지를 빌드합니다. 기존 설정과 데이터 볼륨을 유지합니다.

```powershell
$outlineImage = (Get-Content .local/compose.json -Raw -Encoding UTF8 | ConvertFrom-Json).services.outline.image
docker build --network none -f ops/Dockerfile.outline-authentik-local -t $outlineImage integrations/outline
if ($LASTEXITCODE -ne 0) { throw "Outline 이미지 빌드 실패" }
docker compose -f compose.yml up -d --no-deps --no-build --force-recreate outline
docker compose -f compose.yml logs --tail=100 outline
```

이번 목차 변경은 Outline 소스에만 해당하며 Workhub 코드나 DB 스키마 변경이 없습니다. 기존에 안내한 프로젝트·업무 기능의 미적용 변경이 있다면 해당 기능의 배포 절차도 따릅니다. 이 작업에서는 Docker 이미지 생성이나 컨테이너 재실행을 수행하지 않았습니다. 재시작 후 브라우저를 강력 새로고침하고 `/목차` 삽입·제목 자동 갱신·클릭 이동·저장 후 재열기를 확인합니다. 상세 증빙은 반영 보고서 (`../../reports/toc-block-20261020/report.txt`; 로컬 자료)에 있습니다.

기존 컬렉션의 프로젝트 관리 설정에서 등록할 때도 연동 그룹 확인 → 편집 권한 설정 → 프로젝트 연결을 수행합니다. 같은 요청의 재시도는 권한과 업무 목록을 중복 생성하지 않으며, 완료된 옛 요청은 해제 후 권한을 다시 부여하지 않습니다. 수동으로 추가된 보기 전용 그룹은 임시로 편집 가능으로 올리고 연결 해제 시 보기 전용으로 복원합니다. 기존 수동 편집·관리 권한은 유지합니다. 그룹 권한 복원을 위한 `group_permissions.workhubPreviousPermission` 필드가 추가되며 Outline 시작 시 마이그레이션이 자동 적용됩니다. 프로젝트 연결·해제에 같은 주의 상자를 사용하고, 커스텀 업무 화면의 확정·생성·저장은 파랑, 취소·닫기는 중립색, 해제·삭제는 빨강으로 통일했습니다. Outline·Workhub 두 이미지를 함께 재빌드해야 합니다.

기본 권한이 `편집 가능`이면 생성 화면의 그룹 권한 안내를 숨기며, `보기 전용` 또는 `접근 불가`에서 프로젝트 연결을 선택하면 주황색 주의 상자와 경고 아이콘으로 표시합니다.

## 2026-10-20 생성 시 프로젝트 연동 그룹 자동 추가

Outline에 `Connect_as_a_project` 그룹을 만들고 현재 `OUTLINE_API_KEY`의 발급 계정을 포함시킨다. 새 컬렉션에서 `프로젝트로 연결 및 관리`를 선택하면 전체 문서에 대한 그룹 편집 권한 부여를 미리 안내한다. 그룹과 실제 API 키 계정의 참여 여부를 확인한 뒤 컬렉션·그룹 권한을 같은 트랜잭션으로 생성하고 프로젝트 연결을 진행한다. 연결 성공 시 권한 부여 알림을 한 번 표시한다. 기존 컬렉션을 나중에 연결할 때도 그룹 권한 설정을 자동 처리한다.

그룹 누락·연동 계정 미가입 시 생성하지 않는다. 그룹 추가 후 연결 실패 시 컬렉션과 권한을 유지하고 같은 요청으로 재시도한다. 생성 요청 ID와 자동 권한 ID로 중복 생성을 방지한다. 연결 해제 성공 후 자동 추가한 그룹 권한만 회수하고 수동 권한은 보존한다. 연결 해제 응답 유실·권한 회수 실패는 동일 요청 상태 조회로 회수를 다시 수행한다. 기존 생성·연결 기록과 환경 변수를 재사용하며, 최신 연결 자동화에서는 권한 복원용 필드를 시작 시 자동 추가한다. 이번 기능은 Outline·Workhub 모두 재빌드해야 한다. 검증 결과 (`../../reports/project-group-validation.json`; 로컬 자료).

## 2026-10-19 업무 빠른 수정·일괄 변경 (소스 구현)

업무 화면은 Outline의 기본 테마·글꼴·여백을 따라 정리했다. `완료 포함` 체크박스 대신 `미완료 / 완료 / 전체` 전환 메뉴와 검색 조건에 맞는 개수를 표시한다. 행 선택 시 일괄 수정 도구를 표시하고, 상태 선택·진행 막대·오른쪽 편집 패널·칸반 카드도 같은 시각 체계로 조정했다. 밝은/어두운 테마와 키보드 전환, 작은 화면을 지원한다. 기존 저장·권한·완료 기준·실행 취소 기능은 유지한다. 디자인 수정 자체는 Outline 소스에만 해당하며 Workhub 변경은 없다. 디자인 검증 결과 (`../../reports/task-list-design-validation.json`; 로컬 자료)를 참고한다.

이번 변경은 개발 소스와 재현 패치에 반영했다. Docker 이미지 빌드, 컨테이너 재생성, 운영 문서 변경은 수행하지 않았다. **Outline과 Workhub 두 소스를 모두 빌드하여 적용**해야 한다. 기존 양쪽 `OUTLINE_KANBAN_ENABLED=true` 설정과 서명 브리지를 재사용하므로 새 환경 변수나 DB 마이그레이션은 필요하지 않다.

- 프로젝트의 등록된 최상위 `업무 목록`에서 `칸반 / 목록 / 문서 목록` 순서로 보기를 선택한다. 목록은 완료 업무를 기본 제외하며 페이지당 10개를 표시한다. 기존 칸반과 원문 보기를 유지한다.
- 목록의 담당자·상태 선택과 시작일·마감일 입력으로 한 건을 수정한다. 상태는 미착수·진행 중·보류·지연·완료를 선택할 수 있으며, 완료 기준을 모두 완료하거나 완료 업무를 미착수로 초기화할 때는 확인창을 표시한다. 날짜는 입력 후 Enter 또는 포커스 이동으로 저장하고 Esc로 취소한다. 빈 날짜는 미정이다. 업무명이나 완료 기준의 `편집`, 칸반의 `빠른 수정`을 누르면 오른쪽 패널이 열린다.
- Outline에서 완료 기준 상태를 변경하면 이전 칸반 수동 상태와 관계없이 업무 상태를 다시 계산한다. 전부 완료면 완료, 전부 예정이면 미착수, 그 외에는 진행 중이다. 기준 추가·삭제로 남아 있는 작업량이 바뀌어도 상태를 다시 계산하며, 이름·순서·담당자만 변경할 때는 직접 선택한 상태를 유지한다. 과거 칸반 전용 하단 설명은 제거했다.

후속 사용성 수정은 백엔드 전체 575개와 Outline 관련 테스트 70개, 전체 TypeScript 검사, 변경 파일 lint·포맷 검사 및 51개 파일 패치 재현 검증을 통과했다. 후속 검증 요약 (`../../reports/task-list-status-validation.json`; 로컬 자료)을 참고한다. Docker 빌드·컨테이너 재생성·실제 서비스 테스트는 수행하지 않았다.
- 체크박스는 현재 페이지를 선택하며, 필터 변경·페이지 이동 시 선택을 해제한다. 명시적 전체 선택은 수정 가능한 검색 결과 100개 이하일 때 제공한다. 일괄 변경은 담당자, 같은 마감일 지정, 기존 날짜의 ±일 이동을 지원한다. 시작일 함께 이동은 선택 사항이고 미정인 날짜는 유지한다.
- 관리자이며 문서 수정 권한이 있으면 패널에서 완료 기준 추가·이름 수정·담당자 변경·삭제·위로 이동을 할 수 있다. 입력 후 Enter로 다음 기준을 추가하고 새 입력란에 포커스를 이동한다. 기존 기준은 ID와 완료 상태를 보존한다. 삭제 항목은 저장 전까지 되돌릴 수 있고 최소 1개, 최대 40개를 유지한다. 원래 기준이 없는 업무는 빈 상태를 유지할 수 있다.
- 일반 담당자는 본인 업무의 정보를 수정하고, 배정된 완료 기준의 상태를 기존 칸반 API로 변경할 수 있다. 기준 구조 편집은 관리자만 가능하다. 업무 담당자 변경은 세부 담당자를 기본 유지하며, 관리자가 선택한 경우에만 기존 주담당자의 미완료 기준도 이전한다.
- 여러 필드와 완료 기준 편집은 변경 미리보기 후 확정한다. 완료 기준의 변경 전후 목록과 진행률, 업무별 담당자·날짜 변경을 표시한다. 완료 업무에 미완료 기준을 넣으려면 명시적으로 다시 열기를 선택해야 한다.
- 업무별 결과·변경 기록·재시도 영수증을 저장한다. 부분 실패 시 성공분을 반복 저장하지 않으며, 확정된 실패 업무만 최신 버전으로 다시 미리볼 수 있다. 통신 결과가 불확실하면 같은 요청을 재조회하며 동일 사용자·업무 목록의 세션 저장소로 새로고침 후 복구한다. 저장 도중 관리자 권한을 잃은 요청도 다시 검사한다.
- 실행 취소는 본인이 저장한 작업에 한해 제공하며 이후 수정이 있는 업무는 거부한다. 기존 보고와 변경·취소 기록을 보존한다. 원문·담당자·프로젝트 접근 권한을 매 요청에서 확인한다.

주요 구현은 `src/workhub/task_edit.py`, Outline의 `app/components/WorkhubKanban/TaskList.tsx`, `app/stores/WorkhubTaskEditStore.ts`, `server/routes/api/workhubKanban.ts`이다. 백엔드 테스트는 `src/workhub/test_task_edit.py`, 화면과 상태 관리 테스트는 각각 `TaskList.test.tsx`, `WorkhubTaskEditStore.test.ts`에 있다. 전체 백엔드 검증 로그 (`../../reports/task-edit-full-regression.log`; 로컬 자료), Outline 관련 테스트 로그 (`../../reports/task-edit-outline-tests.log`; 로컬 자료), 검증 요약 (`../../reports/task-edit-validation.json`; 로컬 자료)을 참고한다. 화면 테스트는 jsdom 기반이며 실제 서비스·브라우저 검증과 구분한다.

Docker 없이 테스트하려면 프로젝트 최상위에서 필요한 Python 의존성을 갖춘 인터프리터로 `python ops/run_workhub_tests.py`를 실행한다. 특정 테스트만 실행할 때는 `python ops/run_workhub_tests.py workhub.test_task_edit`를 사용한다. 로컬 테스트 러너는 임시 DB, 가짜 접속 주소와 소스의 legacy 패키지를 사용한다. Outline 소스 폴더에서는 `node node_modules/vitest/vitest.mjs run --project app app/components/WorkhubKanban/TaskList.test.tsx app/stores/WorkhubTaskEditStore.test.ts app/stores/WorkhubKanbanStore.test.ts`와 `node node_modules/typescript/bin/tsc --noEmit`으로 확인한다.

2026-10-07 개발·배포 기준은 **20261007-1**이다. 최신 패치는 공식 원본 대비 44개 파일 재현 검증을 통과했으며 현재 Outline 실행 이미지와 함께 배포 묶음에 포함했다. 개발 빌드는 [개발본 안내](../../development/README.md), 서버 설치는 [배포 안내](../../deployment/README.md)를 사용한다.

Outline 1.10.0의 기존 설치 커밋 `65be53c3eb093a535ce260eb2f2da897bb07a29e`를 유지하고 컬렉션 생성·메뉴에 Workhub 프로젝트 관리를 추가한다. 원본 라이선스와 고지를 유지한다.

## 소스와 빌드

- `upstream.lock.json`: 공식 원본 커밋, archive SHA-256, 기존 이미지 digest.
- `patches/0001-workhub-project-management.patch`: 원본 대비 관리되는 변경.
- `prepare_source.py`: 새 환경에서 원본 검증·추출·패치 적용. 기존 소스 폴더는 덮어쓰지 않는다.
- `export_patch.py`: 검증한 소스 변경을 패치에 반영하는 개발 도구.
- `Dockerfile.dependencies`: Yarn 4.11.0과 원본 lockfile 기준 개발 의존성 준비.
- `Dockerfile`: 소스에서 프런트·서버를 빌드하고 기존 런타임 이미지에 결과를 복사한다.

이 폴더에서 실행한다. 기존 설치의 baseline 이미지가 먼저 필요하다.

```powershell
python prepare_source.py
docker build -f Dockerfile.dependencies -t workhub-outline-build:1.10.0 .
docker build -t unified-work-assistant/outline:project-management-20260930 .
```

소스가 이미 준비된 현재 PC에서는 `prepare_source.py`를 생략한다. 업데이트 시 latest로 교체하지 말고 새 원본 버전과 패치를 함께 검증한다.

## 서버 설정

Outline과 Workhub 모두 `OUTLINE_PROJECT_MANAGEMENT_ENABLED=true`, 동일한 전용 `OUTLINE_WORKHUB_BRIDGE_SECRET`이 필요하다. 브라우저에는 기능 활성화 여부만 공개한다.

- Outline: `WORKHUB_INTERNAL_URL=http://workhub:8000`.
- Workhub: `OUTLINE_WORKHUB_TEAM_ID`에 해당 Outline team ID.
- 기존 Authentik 디렉터리 연동과 UUID↔Outline 사용자 ID 매핑 필요.
- 공개 프록시는 `/internal/outline-projects/`를 차단한다. 내부 API는 서명·시각·nonce·현재 사용자 자격을 검사한다.
- 기존 API 키와 서명키는 비공개 실행 설정으로만 관리한다.

## 사용 흐름

1. Outline의 새 컬렉션에서 `프로젝트로 연결 및 관리`을 선택한다.
2. 컬렉션 생성 후 프로젝트 설정에서 책임자를 선택하고 등록한다. 연결 완료 시 최상위 `업무 목록` 문서를 자동 생성하며, 기존 문서가 있으면 내용과 ID를 보존하여 재사용한다. 문서 작성 권한이 필요하다.
3. 기존 컬렉션은 컬렉션 메뉴의 `프로젝트 관리 설정` 또는 `/workhub/projects/:collectionId`에서 관리한다.
4. 연결 해제 기본값은 문서 보존이다. 고급 옵션을 직접 선택해야 업무 목록과 하위 문서가 휴지통으로 이동한다.
5. 미완료 작업은 같은 요청 재시도 또는 `진행 중 요청 확인·완료`로 복구한다. 현재 관리자와 문서 권한을 다시 검사한다.

Workhub의 프로젝트 관리 버튼은 Outline 설정으로 이동한다. 구형 Workhub 변경 API는 활성화 상태에서 409와 새 진입점을 반환한다.

## 진행 통계 화면

2026-10-01 로컬 실행본에는 `/workhub/analytics`와 사이드바의 `진행 통계`, 연결된 컬렉션의 `진행 통계 보기`가 추가되어 있다. Outline과 Workhub 양쪽에 `OUTLINE_ANALYTICS_ENABLED=true`를 설정한다. 프로젝트 관리 및 검색 플래그와 독립적이며 동일한 기존 서버 서명키와 계정 매핑을 재사용한다. 공개 프록시의 `/internal/outline-analytics/`는 차단해야 한다.

칸반 추가 전 이미지 태그는 `unified-work-assistant/outline:task-sidebar-20261002`, `unified-work-assistant/workhub:task-create-20261001`이며, 현재 실행 태그는 아래 칸반 절에 기록한다. 통계 조회와 수동 동기화는 Outline 로그인으로 호출하며 브라우저가 Workhub 내부 API에 직접 접근하지 않는다. 두 화면의 계산은 `src/workhub/analytics_service.py`를 함께 사용한다. 관리자는 본인 관리 프로젝트에서 담당자가 본인으로 선택된 상태로 시작하되, 상단 지표와 프로젝트 현황은 선택 프로젝트 범위의 전체 업무를 집계한다. 담당자 선택은 업무 목록과 일정에 적용하고 상단 건수 카드를 누르면 팀 전체 목록을 연다. 일반 직원은 본인 참여 업무만 조회한다. 직원의 타인 담당자 조회는 서버에서 403으로 거부하며 담당자·팀 전체·담당자 비교 제어를 숨긴다. Outline의 프로젝트와 마감 확인 기간은 관리자와 일반 직원 모두 화면 최하단의 조회 조건 영역에 둔다. 관리자용 프로젝트 범위, 담당자, 팀 전체·내 업무 전환도 같은 하단 영역에 배치한다.

검증 결과는 [진행 통계 구현 및 검증 결과](../../Outline_진행_통계_구현_검증_결과.md)에 있다. 재현 스크립트는 `../../ops/verify_outline_analytics.mjs`, `verify_outline_analytics_revocation.mjs`, `verify_outline_analytics_mobile.mjs`, `benchmark_outline_analytics.py`, `benchmark_outline_analytics_ui.mjs`이다. 100건·1,000건 부하는 원본 데이터 변경 없이 합성 데이터로 확인한다. 적용 전 설정·소스 백업은 `../../backups/pre-outline-analytics-20261001/`에 있다. 기능만 끄려면 양쪽 통계 플래그를 false로 전환하고 서비스를 재생성한다. 이전 실행 이미지는 양쪽 `search-20260930` 태그이며 DB 초기화가 필요하지 않다.

## 새 업무 간편 등록

연결된 프로젝트의 실제 최상위 `업무 목록` 문서 헤더에 `＋ 새 업무`를 표시한다. 같은 제목의 일반 문서, 템플릿, 초안, 보관·삭제 문서, 읽기 전용 문서에서는 표시하지 않는다. Outline 로그인과 현재 문서 작성 권한, Workhub 서비스 계정 자격을 모두 확인한다.

1. `새 업무`를 누르면 현재 프로젝트가 채워진 기본 Outline 모달이 열린다. 사이드바와 즐겨찾기에서 등록된 `업무 목록` 문서의 `＋`를 눌러도 같은 창이 열린다. 다른 문서를 보고 있어도 버튼을 누른 업무 목록의 프로젝트에 등록하며, 취소하면 문서를 만들지 않는다. 일반 문서와 동일 제목의 미등록 문서는 기존 하위 문서 생성 방식을 유지한다.
2. 업무명만 필수 입력한다. 담당자는 본인을 기본값으로 한다. 관리자는 프로젝트 구성원으로 변경할 수 있으며, 일반 사용자는 본인으로 고정된다.
3. 마감일 아래의 오늘·내일·일주일 뒤·미정 버튼을 바로 누르거나, 달력 또는 직접 입력으로 선택한다. `20261008`, `2026.10.8`, `2026/10/8`도 입력란에서 나오면 `2026-10-08`로 바뀐다. 달력은 한국어로 표시하며 월·연도 이동과 키보드 조작을 지원한다. 잘못된 날짜나 역전된 기간은 등록하지 못한다.
4. 업무 내용은 선택 사항이다. 관리자용 완료 기준과 담당자 분배는 업무 내용 바로 아래에 표시한다. `추가 설정`에는 시작일(기본 오늘)과 결과물 링크를 둔다.
5. 등록하면 `업무 목록` 바로 아래에 읽을 수 있는 일반 업무 문서를 게시하고 미착수·0%로 통계에 반영한다. 템플릿을 직접 적용할 필요가 없다.
6. 현재 목록 화면을 유지하고 `업무 열기`와 `하나 더 등록`을 제공한다. 연속 등록은 담당자를 유지하며, 완료 후 창을 닫았다가 다시 열면 새 입력 화면이 열린다. 등록 성공이 확인되면 배경 목록 갱신을 기다리지 않고 완료 창을 닫을 수 있다.

모달·버튼·입력창·팝오버·달력 및 테마 색상은 Outline 기존 컴포넌트를 사용한다. 사이드바의 `＋`도 기존 모양을 유지하며 등록된 업무 목록은 서버 확인 후 툴팁과 접근성 이름을 `새 업무`로 표시한다. 클릭 시 현재 문서 상태·등록 ID·권한을 다시 확인하며 확인 실패 시 일반 문서를 대신 생성하지 않는다. 클릭 확인 중 버튼을 잠그고 사이드바의 가상화된 행 밖에 창 하나를 유지한다. 입력 간격을 줄이고 업무명 필수 안내를 표시한다. 완료 기준 추가 시 새 입력란에 커서를 옮기며, 취소·등록 버튼은 스크롤 중에도 창 하단에 표시한다. 모바일에서는 기본 전체 화면 모달을 사용하며 달력은 화면 안에 배치한다. 달력에서 Escape를 누르면 달력만 닫는다.

클라이언트는 전송 전 요청을 현재 사용자·팀·업무 목록별 세션 저장소에 기록한다. 서버는 요청 ID와 내용 해시, 생성 문서 UUID를 영속 저장한다. 통신 실패 시 같은 요청의 결과를 다시 확인하며, 새로고침 후에도 복구한다. 등록 결과가 불확실할 때는 입력을 잠그고 중복 생성 대신 기존 문서를 조회한다. 서버는 재시도에도 현재 계정과 프로젝트·문서 작성 권한을 다시 확인한다. 브라우저의 신원·관리자 필드 위조는 거부한다.

Outline과 Workhub 양쪽에 `OUTLINE_TASK_CREATION_ENABLED=true`를 설정한다. 통계·프로젝트 관리·검색 기능 플래그와 독립적이며 기존 내부 서명키와 계정 매핑을 사용한다. 공개 프록시에서 `/internal/outline-tasks/`를 차단한다. 칸반 추가 전 이미지 태그는 Outline `task-sidebar-20261002`, Workhub `task-create-20261001`이며, 현재 태그는 아래 칸반 절에 기록한다. 재현 가능한 적용 스크립트는 `../../ops/enable_outline_task_creation.mjs`이며, 적용 전 비공개 설정은 `../../backups/pre-outline-task-create-20261001/compose.private.json`에 보존한다. 기능을 끄려면 양쪽 등록 플래그를 false로 설정하고 두 서비스를 재생성한다. 기존 문서나 DB 초기화는 필요하지 않다.

검증: 백엔드 회귀 테스트 388개, Outline 앱 테스트 18개, 전체 TypeScript 검사와 변경 파일 lint 및 실행 이미지 빌드를 통과했다. 실제 화면 검증 79개를 모두 통과했으며 관리자·직원 로그인으로 작성 권한, 본인 기본 선택, 직원 타인 배정 차단, 관리자 완료 기준, 날짜 선택·검증, 게시 위치, 통계 반영, 연속 등록, 응답 유실 후 새로고침 복구, 중복 방지, 모바일·다크 테마를 확인했다. 검증 및 정리 후 동기화까지 원본 문서 8개의 내용 해시는 유지됐다. 검증용 문서 6개와 컬렉션 1개를 정리했으며 통계에서도 제외됐다. 실행 서비스 16개는 모두 가동 중이고 건강 검사가 있는 15개 서비스는 모두 정상이다.

- 실제 화면 검증 스크립트: `../../ops/verify_outline_task_creation.mjs`.
- 실제 화면 검증 결과: JSON 보고서 (`../../reports/outline-task-create-live.json`; 로컬 자료).
- 화면: 관리자 등록 (`../../reports/outline-task-create-admin.png`; 로컬 자료), 직원 등록 (`../../reports/outline-task-create-worker.png`; 로컬 자료), 직원 모바일 달력 (`../../reports/outline-task-create-worker-mobile-calendar.png`; 로컬 자료), 다크 테마 달력 (`../../reports/outline-task-create-admin-dark-calendar.png`; 로컬 자료).
- 상세 로그: `../../reports/task-creation-backend-tests.log`, `task-creation-outline-validation.log`, `task-creation-live-check.log`.
- 공식 원본 대비 패치 재현 검증: 변경·추가 파일 33개. `export_patch.py`와 `../../ops/verify_outline_source_patch.py` 사용.

2026-10-02 새 업무 창 사용성 개선은 현재 공식 [W3C 입력 검증 안내](https://www.w3.org/WAI/tutorials/forms/validation/)와 [GOV.UK 날짜 입력 패턴](https://design-system.service.gov.uk/patterns/dates/)을 참고했다. 라이브러리 업그레이드 없이 필수 안내, 유연한 날짜 입력, 빠른 선택과 등록 버튼 접근성을 개선했다. 변경 파일 lint, 전체 TypeScript 검사, 날짜 테스트 4개와 실행 이미지 빌드를 통과했다. `../../ops/verify_outline_task_usability.mjs`의 실제 브라우저 검사 67개에서 관리자·직원, 모바일, 달력, 긴 폼의 하단 버튼, 완료 기준 포커스, 날짜 변환 후 실제 등록과 연속 등록을 확인했다. 검증용 업무 1개를 삭제·통계에서 제외하고 기존 문서 8개의 내용 해시 보존을 확인했다. 결과는 JSON (`../../reports/task-create-usability-live.json`; 로컬 자료), 화면은 관리자 (`../../reports/task-create-usability-admin.png`; 로컬 자료), 모바일 (`../../reports/task-create-usability-admin-mobile.png`; 로컬 자료)에 있다. 로그는 `../../reports/task-create-usability-validation.log`, `task-create-usability-build.log`, `task-create-usability-live-check.log`에 있다.

2026-10-02 사이드바 `＋` 연결 검증: 변경 파일 lint, 전체 TypeScript 검사, 날짜 테스트 4개와 실행 이미지 빌드를 통과했다. `../../ops/verify_outline_task_sidebar.mjs`의 실제 검사 49개에서 관리자·직원의 본인 기본 선택, 다른 문서에서 지정 업무 목록의 창 열기, 등록 위치와 통계 반영, 취소 시 빈 문서 미생성, 확인 요청 실패 시 일반 문서 생성 차단, 연속 클릭, 일반 하위 문서 생성과 동일 제목의 미등록 문서 구분, 상단 등록 버튼 보존을 확인했다. `verify_outline_task_sidebar_starred.mjs`의 중요 문서(즐겨찾기)·모바일 검사 12개 및 기존 `verify_outline_task_creation.mjs`의 등록 회귀 검사 83개도 통과했다. 테스트 문서와 컬렉션·임시 중요 문서를 정리했고 기존 문서 8개의 내용 해시와 기존 중요 문서 목록·순서를 보존했다. 실행 서비스 16개가 가동 중이며 건강 검사가 있는 15개는 모두 정상이다. 결과: 사이드바 JSON (`../../reports/task-sidebar-live.json`; 로컬 자료), 중요 문서 JSON (`../../reports/task-sidebar-starred-live.json`; 로컬 자료), 기존 등록 회귀 JSON (`../../reports/outline-task-create-live.json`; 로컬 자료). 상세 로그는 `../../reports/task-create-sidebar-validation.log`, `task-create-sidebar-build.log`, `task-create-sidebar-live-check.log`, `task-create-sidebar-starred-check.log`, `task-create-sidebar-regression.log`에 있다.

## 업무 목록 본문 칸반

2026-10-02 연결된 프로젝트의 등록된 `업무 목록` 문서를 열면 본문 위치에 칸반을 표시한다. 별도 문서를 만들거나 기존 본문을 수정하지 않는다. 제목·수정 정보·상단 등록 버튼·사이드바는 기존 Outline 구성 요소를 유지하며, 칸반을 표시할 때만 본문 폭을 넓힌다. `문서 목록`은 원래 본문과 하위 문서 목록을 표시한다. 본문의 `원본 문서 편집` 버튼은 제거했다. 변경 이력·공유·기존 문서 편집 기능은 기본 Outline 화면을 사용한다. 같은 제목의 미등록 문서에는 칸반을 붙이지 않는다.

- 미착수·진행 중·보류·지연·완료의 다섯 열. 카드에는 담당자 이름, 마감일, 진행률, 완료 기준 완료/전체 수를 표시한다. 기한 경과는 별도 표시하고, 미기재 진행률을 0%로 간주하지 않는다.
- 업무명·담당자 검색과 `내 업무`(대표 담당자 또는 완료 기준 담당자로 참여한 업무) 필터. `내 업무`는 선택 시 중립색 배경과 체크 아이콘으로 표시한다. `모든 마감`·`7일 내 마감`·`기한 경과` 필터와 등록순·마감 빠른 순 정렬, 필터 초기화를 지원한다. 마감 필터는 미완료 업무만 대상으로 하며 정렬·필터는 원문을 변경하지 않는다. 카드 마감 배지는 오늘·D-n·n일 경과로 표시하고 완료 업무에는 긴급 배지를 표시하지 않는다. 관리자는 담당자 필터도 사용한다. 기본 보드는 현재 프로젝트에서 읽을 수 있는 모든 업무를 표시하며, 기존 개인 진행 통계의 본인 제한은 그대로 유지한다.
- 카드 전체가 업무 문서 링크이며 제목·담당자·진행률·여백 어느 곳을 눌러도 새 탭에서 해당 문서를 연다. Enter 키와 브라우저의 일반 링크 기능을 지원하며 칸반은 원래 탭에 유지한다. 아래 상세 패널은 표시하지 않는다. 관리자는 접근·수정 가능한 업무, 주담당자는 본인 업무를 완료 기준 유무와 관계없이 드래그할 수 있다. 카드와 모든 내부 요소에 잡기 커서를 적용하고 잠깐의 갱신·저장 중에도 커서 모양을 유지한다. 완료 열 이동은 미완료 기준의 개수를 확인한 뒤 다른 담당자의 기준까지 일괄 완료 처리한다. 완료→미착수 이동은 별도 확인창에서 모든 기준을 예정으로 초기화하고 체크를 해제하여 진행률을 0%로 만든다. 다른 이동은 기준을 유지하며 완료에서 진행 중·보류·지연으로 옮길 때에는 기준 진행률 100%를 유지한다. 기준 없는 업무의 완료·재개 진행률은 기존 100%·0% 규칙을 유지한다. 완료 기준 담당자로만 참여한 직원은 열 이동 권한이 없다.
- 칸반 상태는 문서의 `상태:`에 저장한다. 수동 관리 여부는 Workhub SQLite kv의 `task-status-mode:<문서 ID>`에 저장하여 `상태 관리: 칸반` 문구를 삭제해도 완료 기준 집계가 선택한 상태를 덮어쓰지 못하도록 한다. 기존 문서의 헤더 표시와 마지막 업무 사본에서 수동 관리 여부를 이어받으며, 이 설정에는 별도의 상태 값을 저장하지 않는다. 따라서 문서의 실제 상태를 직접 수정하면 해당 값이 기준이 된다. 이후 Rocket.Chat 보고·직접 체크 수정은 완료 기준과 진행률만 갱신하고 선택한 전체 상태는 유지한다. 보류·진행 중 상태의 100% 업무도 가능하다. 칸반 이동 전 문서는 기존 자동 상태 계산을 유지한다. 기존 Rocket.Chat의 보고 초안·보고 및 반영·채널 선택 흐름과 본인 기준 보고 권한은 유지하며, 칸반 이동을 보고 메시지로 자동 발송하지 않는다. 변경 이력에는 실행자·시간·이전/이후 상태·일괄 완료하거나 초기화한 기준을 기록한다.
- 현재 사용자에 대해 Outline 서버가 각 문서의 읽기·쓰기 정책을 확인한 후 서명한 문서 목록만 Workhub에 전달한다. 브라우저가 보내는 권한·신원은 거부한다. 조회는 업무 목록 바로 아래의 게시 문서를 원본에서 읽으며, 양식이 없는 문서나 오류 문서는 `분류 필요`에 남긴다. 보관·삭제·초안·템플릿은 제외한다.
- 새 업무 등록 시 즉시 갱신하고, 수동 새로고침·화면 복귀·활성 화면의 60초 갱신을 지원한다. 목록이 1,000개를 넘으면 분할 안내를 표시하며 일부 결과를 전체 결과처럼 표시하지 않는다. 모바일에서는 보드만 좌우로 스크롤하며 다크 테마도 Outline 색상 체계를 사용한다.
- 원본 revision·updatedAt를 확인하고 `lastRevision`을 전달하여 충돌 시 덮어쓰지 않는다. 요청 UUID·변경 내용·검증 결과를 기존 SQLite kv에 영속 저장한다. 통신이 끊기면 제어를 잠그고 `반영 결과 다시 확인`으로 같은 요청을 재조회한다. 재시도에도 현재 문서 권한·담당자 규칙을 다시 확인한다. 메모·완료 기준·보고 이력은 기존 원문 편집 함수를 통해 보존한다.

Outline·Workhub 양쪽 `OUTLINE_KANBAN_ENABLED=true`가 필요하다. 현재 로컬 이미지는 Outline `kanban-first-drop-20261006`, Workhub `report-fastpath-20261007`이며 기존 등록·통계·검색 플래그를 보존한다. 최신 적용 스크립트는 `../../ops/enable_outline_kanban_first_drop.mjs`, 적용 전 비공개 실행 설정은 `../../backups/pre-outline-kanban-first-drop-20261006/compose.private.json`이다. 기능만 끄려면 양쪽 플래그를 false로 전환하고 서비스를 재생성한다. 기존 문서와 DB 초기화는 필요 없다. 공개 프록시는 `/internal/outline-kanban/`를 차단한다. 업무 목록 확인·조회와 등록 가능 여부 조회는 Outline의 읽기 범위로 분류하고, 실제 등록·변경은 쓰기 범위와 CSRF 보호를 유지한다.

현재 초기화·상태 보존·잡기 커서 검증: `../../ops/verify_outline_kanban_reset.mjs`, 카드 이동 검증: `../../ops/verify_outline_kanban_navigation.mjs`, 완료 기준·문구 삭제 후 실제 보고 검증: `../../ops/verify_outline_kanban_criteria.mjs`, 드래그 중 미리보기 검증: `../../ops/verify_outline_kanban_drag_preview.mjs`. `../../ops/verify_outline_kanban.mjs`는 제거된 상세 패널이 있던 이전 버전의 검사 기록이다. 최신 백엔드 로그: `../../reports/kanban-reset-backend-tests.log`, Outline lint·앱/공통 권한 테스트·전체 타입 검사: `../../reports/kanban-first-drop-frontend-validation.log`. 공식 원본 대비 재현 가능한 패치는 44개 파일이며 `export_patch.py`와 `../../ops/verify_outline_source_patch.py`로 검증한다.

검증 결과: 백엔드 회귀 테스트 407개, 앱 테스트 23개, 공통 인증 테스트 31개를 Node·jsdom 양쪽에서 실행한 62개, 변경 파일 lint·전체 TypeScript 검사·실행 이미지 빌드가 통과했다. 실제 관리자·직원 계정의 API 및 브라우저 검사 65개에서 드래그의 원문 저장, 완료 기준 권한과 진행률 집계, 관리자 담당자 필터, 새 업무 즉시 표시, 원본 목록·편집, 일반 문서 보존, 모바일·다크 테마, 익명·타인 수정·신원 및 권한 주입 차단, CSRF, 읽기 전용 권한, 동시 편집 충돌, 응답 유실 후 같은 요청 복구를 확인했다. 테스트 업무·참고 문서 9개와 컬렉션 1개를 정리했고 기존 문서 8개의 내용 해시는 모두 유지됐다. 사용자 예시의 `위성영상 생성` 프로젝트 문서 5개도 내용 변경 없이 확인했다. 실행 서비스 16개는 가동 중이며 건강 검사가 있는 15개는 모두 정상이다.

- 실제 검증: JSON 보고서 (`../../reports/outline-kanban-live.json`; 로컬 자료), `../../reports/kanban-live-check.log`.
- 사용자 예시 프로젝트 화면: 기본 (`../../reports/outline-kanban-final.png`; 로컬 자료), 모바일 (`../../reports/outline-kanban-final-mobile.png`; 로컬 자료), 다크 테마 (`../../reports/outline-kanban-final-dark.png`; 로컬 자료).
- 원문 보존·화면 오류 확인: 미리보기 검증 (`../../reports/outline-kanban-preview.json`; 로컬 자료). 서비스 상태: `../../reports/kanban-service-health.txt`.

2026-10-02 화면 개선: [Trello의 마감일·구성원 필터](https://support.atlassian.com/trello/docs/filtering-for-cards-on-a-board/)와 [Asana의 카드별 담당자·마감일·하위 항목 표시](https://asana.com/features/project-management/project-views)를 참고해 마감 필터·정렬·배지와 선택 상태 표시만 추가했다. 카드 여백, 열 건수 배지, 선택 카드 테두리를 정돈하고 본문의 원본 문서 편집 버튼을 제거했다. 기존 등록·변경 권한과 완료 기준 계산은 유지한다. 앱 테스트 26개와 공통 인증 테스트 62개, 변경 파일 lint, 전체 타입 검사, 실행 이미지 빌드가 통과했다. 관리자·직원의 실제 검사 85개에서 선택 버튼의 배경과 체크 아이콘, 마감 필터·초기화, 각 열의 정렬, 제거 버튼, 기존 저장·복구·권한, 모바일·다크 테마를 확인했다. 검증 문서 9개와 컬렉션 1개를 정리하고 원본 문서 8개의 내용 해시를 보존했다.

- 개선 적용: `../../ops/enable_outline_kanban_polish.mjs`. 비공개 복구 설정: `../../backups/pre-outline-kanban-polish-20261002/compose.private.json`. 개선 전 Outline 이미지 `kanban-20261002`도 보존한다.
- 최신 결과: 실제 검사 JSON (`../../reports/outline-kanban-live.json`; 로컬 자료), `../../reports/kanban-polish-live-check.log`, `kanban-polish-validation.log`, `kanban-polish-build.log`.
- 선택 상태: 내 업무 선택 (`../../reports/outline-kanban-mine-selected.png`; 로컬 자료), 마감 필터 (`../../reports/outline-kanban-deadline-filter.png`; 로컬 자료). 위 기본·모바일·다크 테마 화면도 개선본으로 갱신했다.

2026-10-06 카드 이동 방식 변경: 카드 전체를 기본 링크로 바꾸어 해당 업무 Outline 문서를 새 탭으로 연다. 제목·담당자·진행률·여백과 Enter 키를 지원하며, 원래 칸반 탭을 유지한다. 링크에 `noopener noreferrer`를 적용하고 드래그 직후 클릭은 억제해 상태 이동 중 문서가 함께 열리지 않도록 했다. 상세 패널과 선택 상태 코드를 제거했으며 완료 기준은 업무 문서에서 확인한다. 드래그 상태 변경의 기존 권한·저장 로직은 유지한다.

앱·인증 테스트 88개와 lint·전체 타입 검사·실행 이미지 빌드가 통과했다. 관리자·직원의 실제 검사 69개에서 카드의 각 영역과 키보드·모바일·다크 테마의 문서 열기, 원래 탭 유지, 새 탭의 문서 내용, opener 분리, 상세 패널 제거, 실제 드래그 저장과 문서 오픈 억제, 드래그 후 클릭을 확인했다. 검증용 업무 2개를 정리했고 기존 문서 8개의 내용 해시를 보존했다.

- 적용: `../../ops/enable_outline_kanban_navigation.mjs`. 비공개 복구 설정: `../../backups/pre-outline-kanban-navigation-20261006/compose.private.json`. 이전 Outline 이미지 `kanban-polish-20261002`를 보존한다.
- 최신 검사: `../../ops/verify_outline_kanban_navigation.mjs`, JSON 보고서 (`../../reports/outline-kanban-navigation-live.json`; 로컬 자료), `../../reports/kanban-navigation-live-check.log`.
- 빌드·검사: `../../reports/kanban-navigation-validation.log`, `kanban-navigation-build.log`, `kanban-navigation-service-health.txt`. 모바일 화면 (`../../reports/kanban-navigation-worker-mobile.png`; 로컬 자료), 다크 테마 (`../../reports/kanban-navigation-worker-dark.png`; 로컬 자료).

2026-10-06 완료 기준 업무 이동: 관리자·주담당자의 열 이동을 허용하고, 미착수·진행 중·보류·지연 이동에서는 기준을 유지한다. 완료 이동은 Outline 기본 확인창에서 미완료 기준 개수를 표시한 뒤 모든 기준을 완료 처리한다. 수동 상태를 문서 헤더에 보존하고 Rocket.Chat 보고·문서 체크 변경·집계·적용 결과에서 같은 규칙을 사용한다. 완료 후 재개한 기준 업무는 진행률 100%를 유지한다. 기존 동시 변경·전송 실패 처리는 추가 변경하지 않았다.

백엔드 417개, Outline 앱·인증 88개, lint·전체 타입 검사·두 실행 이미지 빌드가 통과했다. 실제 화면/API/Rocket.Chat 검사 44개에서 모든 열 이동, 완료 확인 취소, 다른 담당자 기준의 일괄 완료, 재개 후 100% 유지, 새 탭 이동, 참여자 이동 차단, 비공개 테스트 채널의 실제 보고 전송·Outline 반영, 미보고 기준 유지, 모바일·다크 테마를 확인했다. 검증용 문서 2개와 비공개 채널을 삭제했으며 기존 문서 8개의 내용 해시를 유지했다. 사용자 예시 프로젝트의 기존 업무 4개도 원문 변경 없이 관리자에게 이동 가능으로 표시되는 것을 확인했다.

- 적용: `../../ops/enable_outline_kanban_criteria.mjs`. 이전 실행 설정: `../../backups/pre-outline-kanban-criteria-20261006/compose.private.json`.
- 최신 검증: `../../ops/verify_outline_kanban_criteria.mjs`, `../../ops/verify_kanban_report_state.py`, 실제 검사 JSON (`../../reports/outline-kanban-criteria-live.json`; 로컬 자료).
- 검사 로그: `../../reports/kanban-criteria-backend-tests.log`, `kanban-criteria-frontend-validation.log`, `kanban-criteria-live-check.log`, `kanban-criteria-service-health.txt`.

2026-10-06 드래그 미리보기 수정: 전역 사이드바 `DragPlaceholder`가 칸반 드래그까지 문서 이동으로 표시해 `제목없음` 미리보기가 중복 생성됐다. `workhub-task` 드래그에서는 사이드바 미리보기를 제외하고 브라우저의 카드 미리보기를 사용한다. 다른 드래그 유형과 업무 상태 저장 코드는 유지한다. 앱·인증 테스트 88개, 수정 파일 lint·전체 타입 검사·실행 이미지 빌드·42개 소스 파일 패치 재현 검증이 통과했다.

`상태 관리: 칸반`은 현재 문서 헤더에 저장된 실제 제어 설정이다. 서버가 이 표시를 읽어 문서의 `상태:`를 유지하고 완료 기준 진행률만 계산한다. Workhub SQLite의 업무 사본·변경 이력은 조회용이며 별도의 수동 상태 설정이 원문을 대신하지 않는다. 이번 미리보기 수정은 이 저장 방식에 변경을 가하지 않았다.

- 적용: `../../ops/enable_outline_kanban_drag_preview.mjs`. 복구 설정: `../../backups/pre-outline-kanban-drag-preview-20261006/compose.private.json`.
- 검증: `../../ops/verify_outline_kanban_drag_preview.mjs` (`before` 인자로 수정 전 오류 재현), `../../reports/kanban-drag-preview-live.log`, `kanban-drag-preview-validation.log`, `kanban-drag-preview-service-health.txt`.

2026-10-06 커서·초기화·상태 보존 보완: 이동 가능한 카드 전체와 내부 요소에 잡기 커서를 적용했다. 완료→미착수는 Outline 기본 확인창에서 다른 담당자를 포함한 모든 기준을 체크 해제하고 예정·0%로 저장한다. 문서 상태 동기화 전이라도 화면에서 완료로 표시되는 업무에는 같은 규칙을 적용한다. 변경 기준·실행자·시간을 기록하고 참여자·읽기 전용 사용자의 초기화 요청은 차단한다. 수동 관리 여부를 문서 ID별로 영속 보관하여 표시 문구 삭제가 자동 상태 계산을 다시 켜지 않도록 했다. 실제 상태는 계속 원문을 읽으며 별도의 상태 사본이 원문을 덮어쓰지 않는다. 보고 전송·동시 변경·실패 복구 흐름은 유지한다.

백엔드 424개, 앱·인증 88개, lint·전체 TypeScript 검사·실행 이미지 빌드·42개 소스 패치 재현 검증이 통과했다. 실제 브라우저/API 검사에서 카드 내부 커서·새 탭·드래그, 초기화 확인·취소·문서 저장·새로고침, 관리자와 주담당자 초기화, 문구 삭제 후 상태 이동·통계 동기화를 확인했다. 실제 Rocket.Chat 비공개 테스트 채널에서는 문구 삭제 후 보고 전송·원문 반영·보류 상태 유지·본인 기준만 수정되는 것을 검증했다.

- 적용: `../../ops/enable_outline_kanban_reset.mjs`. 복구 설정: `../../backups/pre-outline-kanban-reset-20261006/compose.private.json`.
- 결과: 초기화 및 상태 보존 (`../../reports/outline-kanban-reset-live.json`; 로컬 자료), 보고 회귀 (`../../reports/outline-kanban-criteria-live.json`; 로컬 자료), 확인창 (`../../reports/outline-kanban-reset-dialog.png`; 로컬 자료).
- 로그: `../../reports/kanban-reset-backend-tests.log`, `kanban-reset-frontend-validation.log`, `kanban-reset-live-check.log`, `kanban-reset-report-live-check.log`, `kanban-reset-service-health.txt`.

2026-10-06 드롭 판정 보완: 커서만으로 열을 판정하던 개별 드롭 영역을 보드 공통 영역으로 바꾸었다. 드래그 시작 때 카드 크기를 읽고 이동한 카드의 실제 위치와 각 열의 겹침을 비교한다. 가로 20%(최대 36px), 세로 20%(최대 24px) 이상 겹친 다른 열 중 가장 큰 겹침을 선택하며, 커서 직접 진입도 허용한다. 보이는 열만 대상으로 하고 원래 열은 제외한다. 열 사이 간격과 보드 가장자리 여유를 받고, 빈 열도 가장 긴 열과 동일한 높이로 늘렸다. 선택한 목적지 한 곳만 기존 파란 테두리로 표시하며 같은 판정을 강조와 저장 양쪽에 사용한다. 완료·초기화 확인창, 저장·권한·상태 유지 규칙은 그대로 사용한다.

새 판정 테스트 9개를 포함한 앱·인증 97개, lint·전체 TypeScript 검사·실행 이미지 빌드·44개 파일 소스 패치 재현 검증을 통과했다. 실제 마우스로 원래 열에 커서가 남은 부분 겹침, 빈 열 하단, 열 사이 간격, 경계 스침·보드 밖 취소, 완료 확인 취소·확정, 체크 초기화, 새 탭 열기와 모바일 폭을 확인했다. 검증용 문서 1개를 삭제했고 원본 문서 8개의 내용 해시를 보존했다. 서비스 16개가 실행 중이며 건강 검사가 있는 15개는 모두 정상이다.

- 적용: `../../ops/enable_outline_kanban_drop.mjs`. 복구 설정: `../../backups/pre-outline-kanban-drop-20261006/compose.private.json`.
- 검증: `../../ops/verify_outline_kanban_drop.mjs`, 실제 검사 (`../../reports/outline-kanban-drop-live.json`; 로컬 자료), 목적지 강조 (`../../reports/outline-kanban-drop-overlap.png`; 로컬 자료).
- 로그: `../../reports/kanban-drop-frontend-validation.log`, `kanban-drop-outline-build.log`, `kanban-drop-live-check.log`, `kanban-drop-service-health.txt`.

2026-10-06 첫 드롭·갱신 직후 이동 보완: HTML5 백엔드는 다음 프레임에서 마우스 위치를 갱신하기 전에 `canDrop`을 확인한다. 칸반 공통 영역은 업무 이동 권한과 저장 잠금만 확인하여 첫 이벤트를 받고, 실제 목적지는 놓는 순간 갱신된 카드 위치로 계산한다. 겹침 기준과 목적지 강조, 완료·초기화 확인창은 유지한다. 기존 카드가 있는 동안의 목록 조회는 드래그를 막지 않는다. 이동 시작 시 이전 조회 세대를 무효화하며, 조회는 중복 요청을 합치지 않는 API 경로로 보내 저장 후 조회가 이전 응답을 재사용하지 않도록 한다. 늦게 도착한 조회 결과나 오류가 새 상태를 덮어쓰지 않으며 권한·저장 중 잠금·충돌 검사는 유지한다.

앱·인증 테스트 99개, 변경 파일 lint·전체 TypeScript 검사·실행 이미지 빌드·44개 파일 소스 패치 재현 검증을 통과했다. 이전 화면 자산의 첫 드롭 거절 재현 12개 검사, 수정본의 첫 진입·연속 이동·재진입·조회 중 드래그·늦은 이전 응답·실제 마우스로 바로 놓기 34개 검사와 기존 드롭 회귀 33개 검사를 통과했다. 여섯 이동에 정확히 여섯 저장 요청을 보내며 드래그가 문서 탭을 열지 않는 것을 확인했다. 검증용 문서를 삭제했고 원본 문서 8개의 내용 해시를 유지했다. 실행 서비스 16개와 건강 검사가 있는 15개는 모두 정상이다.

- 적용: `../../ops/enable_outline_kanban_first_drop.mjs`. 복구 설정: `../../backups/pre-outline-kanban-first-drop-20261006/compose.private.json`.
- 검증: `../../ops/verify_outline_kanban_first_drop.mjs`. `--before`는 `.local/outline-first-drop-baseline/`에 추출한 이전 `kanban-drop-20261006` 이미지의 브라우저 자산을 사용하여 실행 서비스를 변경하지 않고 첫 드롭 오류를 재현한다.
- 결과: 첫 드롭 재현 (`../../reports/outline-kanban-first-drop-before.json`; 로컬 자료), 첫 드롭 수정 검증 (`../../reports/outline-kanban-first-drop-live.json`; 로컬 자료), 기존 드롭 회귀 (`../../reports/outline-kanban-drop-live.json`; 로컬 자료).
- 로그: `../../reports/kanban-first-drop-frontend-validation.log`, `kanban-first-drop-outline-build.log`, `kanban-first-drop-before.log`, `kanban-first-drop-live-check.log`, `kanban-first-drop-regression.log`, `kanban-first-drop-service-health.txt`.

## 프로젝트 관리 검증

실행 스크립트는 `../../ops/test_outline_project_management.py`, `verify_outline_project_management.mjs`, `verify_outline_project_edges.mjs`에 있다. 브라우저 검증은 `PLAYWRIGHT_MODULE`에 설치된 Playwright 모듈 경로를 지정한다. 실제 계정 정보는 기존 비공개 테스트 설정에서 읽는다.

실제 원문을 변경하지 않는 비교 기준은 `../../reports/outline-project-baseline.json`이며 실행 결과는 같은 reports 폴더에 저장한다. 새 기능을 검증하는 쓰기 작업은 `[검증]` 컬렉션에서만 수행한다.

## 복구

- 기존 이미지 `unified-work-assistant/outline:migration-baseline`, `unified-work-assistant/workhub:1.0`을 보존한다.
- 변경 전 Workhub DB·Outline DB·실행 설정은 `../../backups/pre-outline-project-management-20260930/`에 있다.
- 우선 두 서비스의 기능 플래그를 false로 바꾸고 필요한 이전 이미지로 돌아간다. pending 작업은 먼저 확인·완료한다.
- 정상 데이터가 추가된 후 DB 백업을 무조건 덮어쓰지 않는다. 새 테이블은 추가형이므로 UI 복귀에 DB 삭제가 필요하지 않다.
- 새 Workhub 버전을 유지하고 기능만 껐다 다시 켤 때 기존 레지스트리 변경을 revision에 반영한다. 이미지 자체를 이전 버전으로 되돌린 기간의 변경도 새 서비스 시작 시 대조한다.
- 배포 패키지 `deployment/`는 별도로 갱신해야 한다. 로컬 적용이 기존 배포 묶음을 자동 수정하지 않는다.

