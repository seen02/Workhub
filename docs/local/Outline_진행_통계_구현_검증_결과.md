# Outline 진행 통계 구현 및 검증 결과

2026-10-01 기준, 구현 명세에 따라 Outline 전용 진행 통계 화면을 만들고 현재 로컬 서비스에 적용했다. Outline 로그인만으로 들어갈 수 있으며 Workhub와 같은 계산 서비스를 사용한다. 기존 프로젝트 11개, 업무 33개, 문서 61개의 내용과 revision 보존을 확인했다.

접속: [Outline 진행 통계](http://outline.workhub.test/workhub/analytics). 왼쪽 `진행 통계`를 누르거나 연결된 컬렉션 메뉴의 `진행 통계 보기`로 이동한다. 이번 적용 대상은 로컬 실행본이며 `deployment/` 배포 묶음은 갱신하지 않았다.

## 구현한 화면과 사용 방법

관리자와 일반 직원 모두 프로젝트와 마감 확인 기간을 화면 최하단의 `조회 조건` 영역으로 옮겼다. 관리자용 프로젝트 범위, 담당자, 팀 전체·내 업무 전환도 같은 영역에 함께 배치했다. 상단에는 현재 조회 범위와 통계, 새로고침을 표시한다. 하단 선택은 기존 조회와 주소 유지 규칙을 사용하며, 관리자 전체 집계와 일반 직원 본인 집계를 유지한다. 관리자 하단 화면 (`reports/outline-analytics-bottom-filters-admin-bottom.png`; 로컬 자료), 직원 하단 화면 (`reports/outline-analytics-bottom-filters-worker-bottom.png`; 로컬 자료), 직원 모바일 (`reports/outline-analytics-bottom-filters-worker-mobile.png`; 로컬 자료)에서 배치를 확인할 수 있다.

2026-10-01 추가 요청을 반영해 권한별 기본 화면과 서버 조회 범위를 수정했다. Workhub의 `projects.js`에서 관리자는 전체 담당자, 일반 직원은 본인 담당자로 초기화하는 흐름과 `analytics.js`의 관리자 관리 프로젝트 범위를 확인했다. 기존 API에는 일반 직원의 타인 담당자 요청을 막는 검사가 없어 공통 서비스에 이를 추가했다.

관리자는 `진행 통계`를 누르면 본인 관리 프로젝트에서 담당자가 본인으로 선택된 상태로, 일반 직원은 열람 가능한 프로젝트 안의 본인 참여 업무로 시작한다. 메뉴를 다시 누르면 이전 담당자·프로젝트·목록 조건을 초기화하고 담당자를 본인으로 되돌린다. 관리자는 팀 전체 또는 다른 담당자를 계속 선택할 수 있다. 일반 직원에게 담당자 선택, 팀 전체 전환, 담당자 비교, 관리 범위 선택, 담당자별 일정 비교를 표시하지 않는다. 직원 화면 (`reports/outline-analytics-groupA.png`; 로컬 자료)과 Workhub 직원 화면 (`reports/workhub-analytics-roles-groupA.png`; 로컬 자료)에 적용 결과가 있다.

관리자의 담당자 기본값을 본인으로 바꾸면서 상단 진행률까지 개인 참여 업무로 좁혔던 문제를 수정했다. 상단 여섯 지표와 프로젝트 현황은 선택한 프로젝트 범위의 열람 가능한 전체 업무를 집계한다. 본인 담당자 포커스는 점검 업무와 일정에 적용한다. 실제 기본 화면은 개인 참여 진행률 28.7%·8건 대신 전체 진행률 20%·32건을 표시한다. 담당자 변경 후에도 전체 집계를 유지하고, 상단 건수 카드를 누르면 담당자를 팀 전체로 바꿔 해당 수치에 맞는 목록을 연다. Outline과 Workhub에 같은 동작을 적용했다. 일반 직원은 계속 본인 참여 업무만 조회한다.

일반 직원의 다른 담당자 조회·새로고침은 403으로 거부하고 담당자를 생략하거나 빈 값으로 보내면 본인으로 강제한다. 업무 목록·완료 목록·일정·오류 문서·합계는 본인 참여 업무만 포함한다. 공동 업무의 상태와 진행률은 업무 전체 값이며 완료 기준 상세와 담당자 통계는 본인 것만 반환한다. 관리자 전용 구형 `/api/stats`도 제한해 다른 경로로의 우회를 막았다. Outline 문서 원문의 공유 권한 자체를 바꾸는 수정은 아니다.

Outline의 기존 사이드바, 버튼, 글자 크기, 배경, 구분선, 테마 색을 사용했다. 상단은 전체 진행률과 업무 수, 완료, 미완료, 마감 초과, 마감 임박을 표시한다. 진행률은 파란색, 점검이 필요한 마감 초과는 빨간색으로 강조한다. 빈 분모의 진행률은 `—`로 표시한다.

조회 조건 전체를 하단으로 옮긴 관리자 화면 (`reports/outline-analytics-bottom-filters-admin-top.png`; 로컬 자료)

| 기능 | 동작 |
|---|---|
| 조회 범위 | 관리자 기본값은 내가 관리하는 프로젝트와 본인 담당자, 직원 기본값은 본인 참여 업무 |
| 필터 | 프로젝트, 마감 확인 7일과 30일. 담당자 및 팀 전체와 내 업무 전환은 관리자만 제공 |
| 요약 카드 | 관리자 전체 업무 집계. 누르면 팀 전체의 해당 조건 목록으로 이동. 직원은 본인 집계 유지 |
| 프로젝트 현황 | 관리자는 담당자 선택과 무관한 프로젝트 전체 진행률·업무 수 표시. 직원은 본인 참여 집계. 행을 누르면 프로젝트 선택 |
| 업무 목록 | 제목·프로젝트·담당자 검색, 상태 및 위험 필터, 페이지당 20건. 목록 안에서 스크롤 |
| 완료 기준 | 펼쳐서 기준별 상태·담당자·다음 행동 또는 점검 제안 확인. 일반 직원은 본인 기준만 반환 |
| 원문 | 업무 제목에서 기존 Outline 문서를 새 탭으로 열기 |
| 담당자 현황 | 관리자만 완료·마감 초과·나머지 업무 비교와 담당자 선택 제공 |
| 일정 | 주간·월간, 이전·다음·오늘 이동, 날짜를 누르면 해당 기간 업무 조회 |
| 일정 누락 | 시작일·마감일 누락 및 역전된 기간을 별도로 표시 |
| 직원 일정 | 본인 참여 업무 일정만 표시 |
| 관리자 일정 | 현재 조회 범위의 일정과 담당자별 최대 동시 진행 업무 수 비교 |
| 갱신 | 화면이 보일 때 20초마다 조회, 탭 복귀 시 재조회. 새로고침 버튼은 원본 동기화 후 조회 |

프로젝트와 조회 범위, 확인 기간은 주소에 남아 새로고침 후 유지된다. 자동 갱신 때 검색·페이지·펼친 기준·일정 위치를 유지한다. 프로젝트 또는 관리 범위를 바꾸면 담당자 선택은 본인으로 돌아간다. 담당자와 세부 목록 필터는 주소에 저장하지 않는다.

어두운 테마 (`reports/outline-analytics-dark.png`; 로컬 자료)

390px 모바일 화면 (`reports/outline-analytics-mobile.png`; 로컬 자료), 모바일 월간 일정 (`reports/outline-analytics-mobile-calendar.png`; 로컬 자료), 데스크톱 월간 일정 (`reports/outline-analytics-calendar.png`; 로컬 자료)도 검수했다. 모바일 일정은 자체 영역에서 가로 스크롤하며 페이지 전체에는 가로 넘침이 없다.

## 집계와 권한 처리

Workhub 기존 `/api/analytics`와 Outline 내부 통계 요청이 새 공통 `analytics_service.query`를 호출한다. 계산식은 기존 `analytics.build`를 유지했다. 세 계정의 동일 조건 응답에서 summary, projects, owners, actions, completed_tasks, calendar_actions, schedule가 일치했다.

브라우저는 인증된 Outline API만 호출한다. Outline 서버가 로그인한 사용자 ID와 팀 ID를 구성해 기존 HMAC 서명·시각·nonce로 Workhub 내부 API를 호출한다. 브라우저에서 actor를 넣으면 거부한다. Workhub는 현재 계정 자격과 Outline 직접·그룹 권한을 다시 확인한다. 관리자 역할이 컬렉션 읽기 권한을 대신하지 않는다. 권한 조회 사본은 한 요청 안에서만 재사용한다.

설치 버전의 `server/policies/Document.ts`를 확인했다. 게시된 업무는 컬렉션의 `readDocument` 권한으로 읽을 수 있으며 문서 멤버십이 그 컬렉션 권한을 더 좁히지 않는다. 현재 업무 수집 대상은 게시된 문서이므로 컬렉션 정책을 집계 전에 적용한다. 정책이나 수집 대상이 달라지는 Outline 버전 업그레이드에서는 다시 검토해야 한다.

초기 조회나 조건 변경이 실패하면 해당 통계를 숨긴다. 같은 조건의 자동 조회가 일시 실패하면 이전 수치라는 안내와 함께 유지하며, 권한 오류 때는 즉시 폐기한다. 마지막 성공한 권한 확인 후 2분이 지나면 이전 수치도 숨긴다. 로그아웃·팀 변경 및 늦게 도착한 이전 요청 응답이 다른 계정이나 조건의 통계를 되살리지 않는다. 잘못된 조회 주소는 자동 재시도 때도 호출하지 않는다.

수동 동기화 요청은 이미 실행 중인 전체 동기화를 공유한다. 새 API의 응답은 `no-store`이고, 공개 프록시의 내부 경로 호출은 404다. 조회는 사용자별 분당 60회, 수동 새로고침은 분당 6회로 제한한다.

## 검증 결과

조회 조건 전체를 하단으로 옮긴 뒤 프런트 검사 15개, 전체 타입 검사, lint 및 이미지 빌드가 통과했다. 실제 관리자·직원 계정에서 32항목을 확인했다. 프로젝트와 담당자, 마감 기간의 최하단 배치, 7일·30일 전환, 관리자 담당자 변경 및 내 업무 복귀, 프로젝트 선택 후 통계 갱신, 역할별 집계 유지, 모바일 배치와 콘솔 오류 없음을 확인했다. 마감 기간 버튼의 접근성 이름도 명시했다. 현재 확인 결과 (`reports/outline-analytics-bottom-filters-live.json`; 로컬 자료), 로그 (`reports/outline-analytics-bottom-filters-live-log.txt`; 로컬 자료), 프런트 검사 (`reports/outline-analytics-bottom-filters-frontend.txt`; 로컬 자료), 최종 lint (`reports/outline-analytics-bottom-filters-final-lint.txt`; 로컬 자료)에 근거가 있다. 서버 집계와 권한 코드는 이번에 변경하지 않았다. 아래 22항목 확인은 프로젝트만 먼저 옮긴 이전 단계의 기록이다.

프로젝트 선택 위치 변경 후 프런트 검사 15개, 변경 파일 lint, 전체 타입 검사 및 이미지 빌드가 통과했다. 실제 관리자·직원 계정에서 22항목을 확인했다. 상단에서 프로젝트 선택 제거, 최하단 배치, 관리자 전용 범위 선택, 선택 후 API와 통계 갱신, 본인 담당자 및 역할별 집계 유지, 390px 모바일의 가로 넘침 없음과 콘솔 오류 없음이 포함된다. 이전 화면 확인 (`reports/outline-analytics-project-filter-live.json`; 로컬 자료), 실행 로그 (`reports/outline-analytics-project-filter-live-log.txt`; 로컬 자료), 프런트 검사 (`reports/outline-analytics-project-filter-frontend.txt`; 로컬 자료)에 근거가 있다. 이번 변경은 Outline 화면 배치만 변경했으며 서버 회귀 365개와 아래 전체 집계 확인 26항목은 직전 수정 때의 기록이다. 추가 검증 중 Docker 엔진 응답 오류가 발생해 재시작한 뒤 검증과 빌드를 순서대로 완료했다.

관리자 전체 집계를 복구한 뒤 서버 회귀 검사 365개, 프런트 검사 15개, 변경 파일 lint 및 전체 타입 검사가 통과했다. 실제 관리자·일반 직원 계정으로 26개 확인 항목이 통과했다. 담당자와 무관한 전체 집계, 프로젝트 선택, 카드에서 팀 목록 열기, 메뉴 재진입 시 본인 복귀, Workhub와 Outline 집계 일치, 직원 타인 조회 차단을 확인했다. 현재 확인 결과 (`reports/outline-analytics-overview-live.json`; 로컬 자료), 로그 (`reports/outline-analytics-overview-live-log.txt`; 로컬 자료)에 근거가 있다. 이전 본인 기본값 확인 11항목과 권한 제한 통합 확인 170항목은 이전 적용의 기록이다.

| 검사 | 결과와 근거 |
|---|---|
| Python 회귀 및 서버 신규 검사 | 365개 통과. 관리자 담당자 변경 시 전체 집계 유지, 접근 불가 업무 제외, 직원 전체 집계 미반환 포함. 실행 로그 (`reports/outline-analytics-overview-python-tests.txt`; 로컬 자료) |
| 프런트 단위 검사 | 15개 통과. 관리자 전체 집계 사용 및 카드 클릭 시 담당자 해제 포함. 실행 로그 (`reports/outline-analytics-bottom-filters-frontend.txt`; 로컬 자료) |
| 타입 및 정적 분석 | 전체 `yarn tsc --noEmit` 성공. 변경 파일 lint 오류·경고 0. 실행 로그 (`reports/outline-analytics-bottom-filters-frontend.txt`; 로컬 자료) |
| 실제 API와 브라우저 | 현재 전체 집계 수정은 관리자·직원 A의 API와 두 화면에서 검증. 결과 (`reports/outline-analytics-overview-live.json`; 로컬 자료). 이전 권한 적용 시 관리자·직원 A·직원 B로 170개 확인 항목 통과, 원문 61개 보존 포함. 이전 결과 (`reports/outline-analytics-live.json`; 로컬 자료) |
| 실제 권한 회수 | 검증용 비공개 컬렉션에 읽기 권한 부여 → 조회 성공 → 직접 권한 회수 → 같은 세션의 조회 차단, 전체 범위 후보에서도 제거. 결과 (`reports/outline-analytics-revocation.json`; 로컬 자료) |
| 화면 | 컬렉션 메뉴, 기본 범위, URL과 재로드, 내 업무, 완료 카드, 월간 일정, 두 테마, 오류 안내, 모바일 검사 통과. Edge 콘솔의 pageerror 없음 |
| 모바일 추가 확인 | 390px에서 요약 수치가 사이드바에 가리지 않고 표시됨, 페이지 가로 넘침 없음, 월간 일정 접근 성공. 결과 (`reports/outline-analytics-mobile.json`; 로컬 자료) |
| 소스 재현 | 고정 공식 원본 archive SHA-256 검증 후 패치 적용. 통합 패치의 수정 파일 25개 내용 일치. 결과 (`reports/outline-analytics-bottom-filters-patch.txt`; 로컬 자료) |
| 빌드와 실행 | 프런트·서버와 Workhub 이미지 빌드 성공. 16개 서비스 실행 중, health check가 있는 서비스 모두 healthy |
| 기존 데이터 | 프로젝트 ID 11개, 업무 ID와 컬렉션 연결 33개, 문서 본문 SHA-256 및 revision 61개 모두 적용 전과 동일 |

실제 API 검사는 Workhub 선행 로그인 없이 Outline에 로그인한 상태로 시작했다. 수치 비교를 위한 별도 Workhub 세션은 비교 단계에서만 만들었다. 직원의 관리자 관리 범위 조회, 접근 불가 프로젝트 주소, 비로그인 요청, actor 위조, 잘못된 확인 기간과 공개 내부 경로가 차단됐다.

일시 장애·빈 데이터·권한 오류의 화면 상태는 브라우저 응답을 모의 처리해 검증했다. 실제 계정과 컬렉션 접근 차단·권한 회수·수치 비교·수동 동기화는 실제 API로 확인했다. 계정 정지·업무 자격 회수·그룹 권한 회수는 이번 실행에서 실제 계정을 변경해 재현하지 않았으며 관련 서버·권한 회귀 검사와 기존 정책을 확인했다. 모든 명세 항목을 실제 환경에서 각각 재현했다는 의미는 아니다.

권한 회수 검사에 사용한 새 `[검증]` 컬렉션은 프로젝트 연결을 해제하고 휴지통으로 옮겼다. 기존 문서나 계정의 권한은 변경하지 않았다.

## 성능 측정

권한별 화면 수정 후 실제 조회 성공 5회 표본의 p95는 **1,443ms**였다. 표본이 작아 이 값은 최대값과 같으며 운영 부하의 장기 p95를 보장하지 않는다. 현재 데이터에서 명세의 로컬 조회 목표 5초 이내를 충족했다. 다음 합성 부하 수치는 최초 적용 시 측정 결과다.

| 합성 업무 수 | 공통 서비스 계산 p95 | 응답 크기 | 응답 후 요약 표시 | 렌더링 업무 행 |
|---|---:|---:|---:|---:|
| 100건 | 9.77ms | 107,088바이트 | 70ms | 20개 |
| 1,000건 | 54.78ms | 1,006,637바이트 | 496ms | 20개 |

계산은 각 20회, 브라우저 표시는 각 1회 측정했다. 1,000건에서도 월간 달력과 목록 검색을 확인했다. 합성 계산에서는 ACL과 Outline 네트워크 호출을 모의 처리했고 브라우저에서는 응답을 합성 데이터로 대체했다. 따라서 이 표는 1,000건의 실제 인증·권한·원본 네트워크 전체 성능을 나타내지 않는다. 계산 측정 (`reports/outline-analytics-benchmark.json`; 로컬 자료), 화면 측정 (`reports/outline-analytics-ui-benchmark.json`; 로컬 자료)에 근거가 있다.

## 변경 파일과 적용 상태

| 영역 | 주요 파일 |
|---|---|
| 공통 조회와 인증 | `src/workhub/analytics_service.py`, `main.py`, `outline_bridge.py` |
| 동기화 요청 공유 | `src/workhub/outline.py` |
| Outline API와 플래그 | `server/routes/api/workhubAnalytics.ts`, `server/routes/api/index.ts`, `server/env.ts` |
| 화면·달력·상태 | `app/scenes/WorkhubAnalytics/`, `app/stores/WorkhubAnalyticsStore.ts`, `RootStore.ts` |
| 메뉴 | 사이드바 링크, 인증 경로, 컬렉션 액션과 메뉴 hook |
| 재현과 프록시 | `integrations/outline/export_patch.py`, 통합 patch와 lock, `config/nginx-local/default.conf` |

Outline 파일 경로는 `integrations/outline/outline-65be53c3eb093a535ce260eb2f2da897bb07a29e/` 아래다. 전체 타입 검사에서 발견한 기존 KnowledgeSearch 요청 인자의 타입 오류도 `JSONObject`와 API 응답 제네릭을 사용하도록 수정했다. 검색 동작은 변경하지 않았다.

적용 이미지:

- `unified-work-assistant/outline:analytics-bottom-filters-20261001`
- `unified-work-assistant/workhub:analytics-overview-20261001`

양쪽 `OUTLINE_ANALYTICS_ENABLED=true`를 적용했다. 기존 프로젝트 관리와 검색 설정, 로그인 설정, API 키 및 데이터 볼륨을 유지했다. 조회 기능 추가에 새 영구 업무 테이블이나 DB 초기화가 필요하지 않았다.

## 재검증과 복구

`ops/run_workhub_tests.py`는 임시 DB에서 회귀 검사를 실행한다. 프런트는 기존 Yarn 환경에서 달력·store 단위 검사, 변경 파일 lint, 전체 타입 검사를 실행한다. 실제 계정 테스트는 `ops/verify_outline_analytics.mjs`, `verify_outline_analytics_revocation.mjs`, `verify_outline_analytics_mobile.mjs`를 사용한다. 계정·서비스 비밀은 기존 비공개 설정에서 읽으며 보고서에는 기록하지 않는다.

적용 전 설정·Workhub 소스·통합 패치와 원본 변경 파일 백업은 `backups/pre-outline-analytics-20261001/`, 원문 비교 기준은 `reports/outline-analytics-baseline.json`이다.

권한별 화면 수정 직전 설정과 변경 파일은 `backups/pre-outline-analytics-roles-20261001/`에 보존했다. 이 수정 직전 이미지는 양쪽 `analytics-20261001` 태그다. 검증 중 Docker 엔진이 응답하지 않아 재시작했고, 이후 빌드와 검사를 순서대로 다시 완료했다. 데이터 볼륨은 초기화하지 않았다.

관리자 본인 기본값 수정 직전 실행 설정은 `backups/pre-outline-analytics-self-20261001/compose.json`에 있으며 직전 이미지는 양쪽 `analytics-roles-20261001` 태그다.

관리자 전체 집계 복구 직전 설정은 `backups/pre-outline-analytics-overview-20261001/compose.json`에 보존했다. 직전 이미지는 양쪽 `analytics-self-20261001` 태그다. 추가 실제 검증 스크립트는 `ops/verify_outline_analytics_overview.mjs`다.

프로젝트 선택을 하단으로 옮기기 직전 설정은 `backups/pre-outline-analytics-project-filter-20261001/compose.json`에 있다. 직전 Outline 이미지는 `analytics-overview-20261001`이며 Workhub는 이번에 변경하지 않았다.

기능만 되돌리려면 양쪽 서비스의 `OUTLINE_ANALYTICS_ENABLED=false`로 변경한 뒤 서비스를 재생성한다. 실행 이미지 자체를 되돌릴 때는 적용 전 Outline과 Workhub의 `search-20260930` 태그를 사용한다. 통계 화면 복구에 기존 DB나 원문 문서를 덮어쓸 필요가 없다. 배포 묶음에 반영하려면 새 이미지, 통합 패치, 프록시 내부 경로 차단과 플래그를 별도로 포함해야 한다.

조회 조건 전체 이동 직전 설정은 `backups/pre-outline-analytics-bottom-filters-20261001/compose.json`에 보존했다. 직전 Outline 이미지는 `analytics-project-filter-20261001`이다.
