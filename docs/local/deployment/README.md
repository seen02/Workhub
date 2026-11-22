# Workhub 배포본 20261007-1

2026-10-07 현재 실행본의 프로젝트 관리·진행 통계·새 업무 등록·칸반·자료 검색·내 업무 조회·보고 초안 개선과 현재 계정·문서·업무·채팅·RAG·모델 데이터를 포함합니다. 실행 이미지는 linux/amd64입니다.

## Ubuntu 최초 시작

1. Ubuntu x86-64 서버에 [공식 설치 안내](https://docs.docker.com/engine/install/ubuntu/)에 따라 Docker Engine + Compose v2와 Python 3.10 이상을 준비합니다. Docker를 실행할 권한이 있는 계정에서 진행합니다. ARM 서버용 묶음은 아닙니다.
2. 이 폴더 전체를 서버로 복사합니다. 숨김 폴더 `.private`와 `artifacts`도 반드시 포함합니다. 비밀번호와 문서 데이터가 포함되어 있으므로 공개 저장소에 올리지 않습니다.
3. 복사한 폴더에서 실행합니다.

```sh
python3 manage.py load-images artifacts/workhub-images-20261007-1.tar
python3 manage.py --project workhub-server preflight
python3 manage.py --project workhub-server restore artifacts/source-baseline
```

`restore`는 최초 한 번만 실행합니다. 이미지와 백업의 체크섬을 확인하고 새 저장소에 복원하며, 기존 데이터가 있는 저장소에는 덮어쓰지 않습니다. 복원 시 Workhub 세션은 초기화되므로 다시 로그인합니다.

4. 서버 자체에서만 시험하면 다음 설정은 생략합니다. 직원 PC에서 접속하려면 복원 완료 후 서버의 실제 사설 IP로 설정합니다.

```sh
python3 configure_access.py --listen 192.0.2.50
```

위 IP는 예시입니다. 해당 서버에 실제 할당된 주소로 바꾸세요. 이 명령은 Nginx HTTP 80만 그 주소에 바인딩하고 다른 호스트 포트는 로컬 전용으로 둡니다. 이미지를 다시 빌드하거나 SSO 이름을 바꾸지는 않습니다. 초기 `restore` 전에는 실행하지 마세요. 복원은 백업과 설정 일치를 확인합니다.

5. 접속할 직원 PC의 hosts 또는 사내 DNS에 다음 이름을 서버 IP로 등록합니다. 서버 내 브라우저를 사용할 때도 필요합니다. 컨테이너 내부에서는 Docker 별칭으로 자동 연결됩니다.

```text
192.0.2.50 workhub.test rocketchat.workhub.test outline.workhub.test authentik.workhub.test ai.workhub.test
```

Ubuntu hosts는 `/etc/hosts`, Windows는 `C:\Windows\System32\drivers\etc\hosts`입니다. 방화벽에서는 사내 이용자 대역의 서버 TCP 80 접근만 허용합니다. IP 주소만 브라우저에 입력하면 올바른 서비스/SSO로 연결되지 않습니다.

Docker 공개 포트는 UFW 규칙을 우회할 수 있으므로, 접근 대역 제한은 사내 네트워크 방화벽 또는 Docker에 맞는 방화벽 규칙으로 적용합니다.

6. 시작합니다.

```sh
python3 manage.py --project workhub-server start
python3 manage.py --project workhub-server status
```

Workhub: http://workhub.test / 채팅: http://rocketchat.workhub.test / Outline: http://outline.workhub.test / Authentik: http://authentik.workhub.test
기존 Authentik 계정으로 로그인합니다. 이 배포본은 별도 인증서 설치 없이 HTTP로 확인하는 준비본입니다. 실제 운영 전에는 사내 정식 주소·HTTPS 및 SSO 복귀 주소를 함께 맞춰야 합니다.

## 재시작·중지·백업

```sh
python3 manage.py --project workhub-server stop
python3 manage.py --project workhub-server start
python3 backup_cycle.py --project workhub-server --destination ./backups
```

중지는 데이터와 컨테이너를 보존합니다. 백업 명령은 잠시 중지하고 백업·검증 후 다시 실행합니다. 운영 데이터에는 `restore`를 재실행하거나 `docker compose down -v`를 사용하지 마세요.

## 포함 파일

- `compose.json`, `config/nginx.conf`: Linux에서 실행할 Docker 서비스와 HTTP 라우팅
- `.private/environment.json`: 비공개 연결 설정과 인증 정보
- `artifacts/workhub-images-20261007-1.tar`: 16개 서비스 실행 이미지
- `artifacts/source-baseline`: 현재 데이터 14개 저장소, AI 모델 및 검색 색인 포함
- `manage.py`: 이미지 불러오기·검증·복원·실행 도구. 서비스 자체는 Docker가 실행합니다.
- `configure_access.py`: 초기 복원 후 서버의 사설 IP 바인딩 설정
- `artifacts/workhub-development-20261007-1.zip`: 실제 설정·데이터를 제외한 최신 개발 소스·테스트·Outline 원본 및 패치·개발 빌드 안내
- `source-manifest.json`, `source-audit.json`, `checksums.json`, `reports`: 소스·배포 파일 해시와 검증 결과

새 서버 자원 요구량과 동시 AI 응답 속도는 서버에서 확인해야 합니다. 이번 검증은 기본 실행·연결·데이터 복원 중심이며 실제 Ubuntu 서버 설치를 대신하지 않습니다.

## 개발본과 이전 배포본

개발 ZIP을 별도 폴더에 풀면 `development/README.md`에서 코드 수정과 개발 이미지 빌드·테스트 절차를 확인할 수 있습니다. 회사 서버의 첫 기동은 위 배포 절차를 사용합니다. 개발 ZIP과 실행 배포본은 같은 20261007-1 기준입니다.

이전 20260928-1 배포본은 `../deployment-archive/20260928-1/`에 원본 그대로 보존했습니다. 기존 서버에 새 데이터가 쌓인 뒤 과거 백업을 덮어써서 돌아가는 방법은 사용하지 않습니다.
