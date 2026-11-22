# 로컬 Nginx 구성 — 2026-09-22

## 현재 접속 방법

|서비스|현재 주소|기존 입구 주소|
|---|---|---|
|Workhub 업무 보드·통계|http://workhub.test|http://localhost:8004|
|Rocket.Chat|http://rocketchat.workhub.test|http://localhost:3000|
|Outline|http://outline.workhub.test|http://localhost:8090|
|문서 비서 Open WebUI|http://ai.workhub.test|http://localhost:3001|
|Authentik|http://authentik.workhub.test|http://localhost:9000|

현재 PC의 Windows hosts에 5개 이름을 127.0.0.1로 등록했습니다. 기존 입구 주소는 새 주소로 302 이동합니다. 주소가 달라졌으므로 새 주소에서 처음 한 번 로그인해야 합니다. 이전 주소에 저장된 세션과 새 주소의 브라우저 세션은 별개입니다. HTTP API를 직접 호출하는 외부 스크립트는 새 주소로 바꾸세요. POST 요청을 이전 주소에 보내고 리다이렉트에 의존하지 마세요.

현재는 **HTTP 로컬 테스트용**입니다. 브라우저가 '안전하지 않음'으로 표시할 수 있습니다. Windows 인증서 설치는 취소했고 테스트 CA가 신뢰 저장소에 없는 것을 확인했습니다. TLS 인증서와 개인 키도 사용하지 않습니다. 실제 직원 계정·자료를 처리하는 운영 서버에는 HTTPS를 적용해야 합니다. 일부 브라우저의 알림·클립보드 등 HTTPS 전용 기능은 HTTP에서 제한될 수 있습니다.

## 바뀐 구조

브라우저 → Nginx(HTTP 80) → 각 Docker 서비스입니다. Nginx가 요청의 호스트 이름을 보고 목적지를 구분합니다. 공개 대표 주소, Authentik의 4개 OAuth 제공자 복귀 주소, Rocket.Chat의 사이트·인증 주소도 같은 이름으로 맞췄습니다. 계정, 클라이언트 ID·비밀키, DB·첨부·채팅 볼륨은 유지했습니다.

- 설정: `config/nginx-local/default.conf`
- 실행 Compose: `.local/compose.json` (`compose.yml`에서 include)
- 서비스 공개 주소: `.local/integration.json`
- 전환 전 설정·SSO 복구 정보: `.local/nginx-transition/before-*` — 비공개 보관
- HTTP 80은 현재 PC의 127.0.0.1에만 바인딩합니다. 기존 8090·9000의 외부 바인딩은 유지하지만 새 로컬 주소로 이동하는 입구입니다. 다른 PC에서 사용하는 구성은 아직 아닙니다.
- 기존 Authentik 직접 HTTPS 포트 9443은 제거했습니다. 로컬 443도 열지 않습니다.
- WebSocket 전달, 버퍼링 해제, 최대 업로드 250MB, 전달 헤더 설정, Docker 내부 이름 재조회, Nginx 상태 검사와 로그 용량 제한을 설정했습니다.
- 없어진 RAG 컬렉션 `통합 업무`의 오래된 이름 설정도 제거했습니다. 현재 프로젝트 등록과 자료는 유지했습니다.

## 검증 결과

`reports/nginx-local-verification.json`의 자동 검사 **32개 통과**:

- 기존 주소 5개 이동, 새 주소 5개 응답, OIDC issuer 4개 일치
- 팀장·홍길동·김철수 로그인, 프로젝트 노출·담당자 후보·접근 차단
- Outline 보고 확정, 중복 확정, 초안 취소, 기존 완료 기준 상태 유지
- 통계 API, 업무 봇 연결, Rocket.Chat·Outline WebSocket 연결
- 팀 협업 시연 RAG 질문 2개에 답변과 출처 반환

`ops/verify_sso.mjs`에서 Workhub·Outline·Open WebUI의 관리자 SSO도 통과했습니다. 브라우저에서 Workhub 업무 보드, Outline 컬렉션 목록, Rocket.Chat Authentik 로그인과 `시작` 입력 후 프로젝트 선택 버튼 응답을 확인했습니다. Rocket.Chat의 'Unique ID change detected'는 기존 워크스페이스에 대한 **Configuration update**로 처리했습니다. 새 워크스페이스를 만들지 않았습니다. 16개 서비스 실행 중이며 healthcheck가 있는 15개 모두 healthy입니다. `reports/nginx-data-preservation.json`에서 16개 서비스 이미지·데이터 연결 경로 유지도 확인했습니다. 이 검증은 가벼운 연결·기능 점검이며 부하 검증이나 운영 HTTPS 검증은 아닙니다.

검증 과정에서 기존 상태를 유지하는 보고 확정/취소 이력은 추가했습니다. 업무 완료 기준과 진행률은 바꾸지 않았습니다.

## 로컬에서 직접 확인

1. http://workhub.test 접속 후 기존 Authentik 계정으로 로그인합니다.
2. 업무 보드의 프로젝트·담당자와 진행 통계를 확인합니다.
3. http://rocketchat.workhub.test 에서 **Authentik로 로그인**하고 통합 업무 비서에 `시작`을 입력합니다.
4. 프로젝트·업무를 선택해 초안 생성 → 취소, 또는 보고 확정을 확인합니다.
5. Workhub 자료 검색에서 팀 협업 시연 프로젝트를 선택하고 '배포 전에 확인할 항목과 출처를 알려줘'를 질문합니다.
6. http://localhost:8090 으로 들어가 Outline 새 주소로 이동하는지 확인합니다.

일반 실행·중지는 기존 `start.ps1`, `stop.ps1`과 동일합니다. Nginx만 문법 검사할 때는 `docker compose exec reverse-proxy nginx -t`를 사용합니다.

## 되돌리기

전환 상태를 되돌릴 필요가 있을 때 이 폴더에서 실행합니다. Python에는 기본 표준 라이브러리만 필요합니다.

```powershell
./ops/rollback_nginx_local.ps1 -Python python
```

현재 접속 가능한 주소를 통해 SSO 설정을 먼저 복원하고, 기존 Compose·공개 주소 설정을 복원한 뒤 컨테이너를 다시 구성합니다. 볼륨을 삭제하지 않습니다. hosts의 테스트 주소도 지우려면 관리자 PowerShell에서 `./ops/set_nginx_test_hosts.ps1 -Mode Remove`를 실행하세요. SSO 복원에 실패하면 스크립트는 Compose 변경 전에 중단하므로 원인을 확인해야 합니다.

## 실제 서버에서 추가할 일

1. 사내 DNS 이름과 서버 IP를 확정합니다. 이 PC 전용 hosts와 127.0.0.1 바인딩을 그대로 서버 배포에 쓰지 않습니다.
2. 실제 이름에 맞는 공인 인증서 또는 회사가 관리하는 사내 인증서를 Nginx에 설치합니다. 이번 테스트 CA를 직원 PC에 배포할 필요는 없습니다.
3. Nginx 443과 HTTP→HTTPS 이동, 서비스별 공개 URL, Authentik issuer·복귀 주소, Rocket.Chat 인증 주소, Outline HTTPS 강제와 쿠키 설정을 함께 변경합니다. 인증서는 자동 갱신되도록 구성합니다.
4. 서버 방화벽은 필요한 접속 포트만 허용하고, 오래된 localhost 포트의 공개 입구는 닫습니다. 서비스는 Docker 내부에서 연결합니다. 도메인 외에 SMTP, 정기 백업과 복원 절차도 실제 환경에 맞춥니다.
5. 로그인·보고·검색·실시간 연결·첨부 업로드를 실제 HTTPS에서 다시 확인합니다. HTTP 점검 결과만으로 HTTPS 전환 완료로 간주하지 않습니다.
6. 최종 주소·인증 설정을 포함해 배포본을 다시 생성하고, 복원 후 같은 점검을 수행합니다. **기존 `deployment/` 버전 20260922-1은 이번 로컬 Nginx 전환을 포함하지 않습니다.**
