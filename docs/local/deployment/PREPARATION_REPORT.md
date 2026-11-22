# 최신 개발본·배포본 정리 — 20261007-1

2026-10-07 개발 작업 트리·현재 실행 이미지·서버 전달용 배포 묶음을 같은 버전으로 정리했다. 회사 서버에 적용한 결과가 아니라 로컬에서 복원·기동까지 검증한 배포 준비본이다.

## 포함한 최신 변경

- Outline 프로젝트 등록·책임자·연결 해제·재연결과 권한 검사.
- Outline 진행 통계, 담당자·프로젝트 조회 조건과 관리자·직원 구분.
- 새 업무 간편 등록, 날짜 입력·달력, 사이드바 등록과 연속 등록.
- 칸반 완료 기준·상태·초기화, 새 탭 탐색과 카드 드롭 판정 개선.
- 자료 검색·채팅 검색과 접근 권한, 최신 색인 갱신.
- 채팅 내 업무·기한 초과·완료 기준 조회와 계정·담당자 동기화.
- 보고 개편·오인식 수정·요청 내 조회 재사용과 2026-10-07 명확한 보고 초안 개선.
- 현재 계정·문서·업무·채팅·초안·RAG 색인·AI 모델 데이터, Nginx HTTP 임시 주소 5개와 기존 리소스 제한.

보고 업무 목록 사전 갱신, AI 입력·출력 축소, 제출 대기 분리 등 미착수 기능은 구현 완료로 표시하지 않는다. 단계별 상태는 개발 소스의 보고 성능 및 신뢰성 개선 명세를 따른다.

## 개발본

- `artifacts/workhub-development-20261007-1.zip`: 현재 작업 트리의 소스·테스트·의존성·운영 문서·배포 도구와 Outline 공식 원본/패치.
- 개발용 Dockerfile은 이번 배포 태그에서 시작한다. 로컬 Workhub 개발 이미지 `workhub-dev/workhub:20261007-1`도 만들고 **436개 테스트 통과**를 확인했다.
- Git 초기 커밋과 현재 미커밋 변경을 구분하여 `development/version.json`과 `source-manifest.json`에 기록한다. Git 초기화·커밋·푸시는 하지 않았다.
- 실제 인증 설정·데이터·인증서·캐시·빌드 산출물은 개발 ZIP에서 제외했다. DB에 설치되는 WebUI 도구는 소스와 별도로 설치 위치별 해시를 검사했다.

## 배포본과 검증

- Linux amd64 실행 이미지 **16개**와 일관된 데이터 저장소 **14개**를 포함한다. 이미지 아카이브는 약 6.97 GiB다.
- Workhub 실행 파일 81개, 문서 비서 Dockerfile에 지정된 파일 49개, 임베딩 워커 3개, WebUI 도구/필터 5개, Outline 서버 연동 소스 10개가 현재 개발 소스와 일치했다.
- 새 `test_report_fastpath.py`는 개발 전용 테스트 파일로 개발 ZIP·개발 이미지에 포함했다. 현재 서비스에 필요한 실제 코드의 불일치는 없다.
- Outline 공식 원본 SHA-256과 관리 패치 **44개 파일** 재현 검증을 통과했다. 프런트는 기존 검증된 실행 이미지를 정확한 digest로 고정했으며 이번 정리에서 재빌드하거나 동작을 바꾸지 않았다.
- 배포 관리 도구 안전성 테스트 **9개 통과**. 격리된 배포 실행본의 최신 Workhub 테스트도 **436개 통과**.
- `workhub-releasecheck-202610071`에 별도 저장소로 복원하여 16개 서비스의 건강 상태, SSO discovery, 봇 연결, 공개 프록시의 내부 API 차단을 확인했다.
- Outline·Authentik·Workhub·WebUI·문서 비서·Rocket.Chat·RAG의 주요 레코드 수가 원본 스냅샷과 같았다. Workhub 로그인 세션·인증 사본은 기존 복원 원칙대로 초기화하여 새 로그인을 요구한다.
- 원래 16개 컨테이너의 ID·이미지·마운트를 보존했고 모두 다시 실행했다. 검증본은 별도 데이터 저장소를 사용했고 검증 후 중지했다. 기존 데이터나 과거 배포본은 삭제하지 않았다.
- `checksums.json`, 이미지·개발 ZIP의 manifest 및 `artifacts/source-baseline/manifest.json`에 파일 체크섬을 기록했다.

## 버전과 실행 상태

| 구분 | 현재 기준 |
|---|---|
| 개발 소스·배포 묶음 | 20261007-1 |
| 로컬 Workhub | unified-work-assistant/workhub:report-fastpath-20261007 |
| 로컬 Outline | unified-work-assistant/outline:kanban-first-drop-20261006 |
| 로컬 문서 비서 | unified-work-assistant/document-agent:search-20260930 |
| 이전 배포본 | ../deployment-archive/20260928-1/ — 원본 보존 |
| 설치·복원·실행 | [README.md](README.md) |

검증 환경은 Windows Docker Desktop의 Linux amd64 컨테이너다. 실제 Ubuntu 서버 설치, 회사 서버 배포와 대규모 동시 AI 부하 검증은 수행하지 않았다. 실제 서버 주소·HTTPS·SMTP·백업 예약은 서버 환경에서 정해야 한다.

## 검증 자료와 복구

- 현재 실행 코드 대조, 소스 해시, 배포 파일 체크섬 (`checksums.json`; 로컬 자료).
- 별도 복원본 기동 (`reports/release-start-smoke.json`; 로컬 자료), 복원 레코드 비교 (`reports/inventory-restored.json`; 로컬 자료), 복원본 코드 대조 (`reports/restored-source-audit.json`; 로컬 자료).
- 개발 이미지 테스트 (`reports/development-workhub-tests.txt`; 로컬 자료), 배포본 최신 코드 테스트 (`reports/workhub-tests.txt`; 로컬 자료), 원래 서비스·데이터 분리 보존 (`reports/preservation.json`; 로컬 자료).
- 이전 배포 폴더는 `../deployment-archive/20260928-1/`, 수정 전 안내 문서는 `../backups/release-refresh-20261007-1/`에 보존했다. 패키지 선택을 되돌릴 때 이전 묶음을 사용하고 운영 데이터에 과거 백업을 덮어쓰지 않는다.
