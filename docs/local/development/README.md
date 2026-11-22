# 개발 기준 20261007-1과 추가 수정본

2026-10-07 실제 실행 코드와 대조한 작업 트리 스냅샷이다. Git의 초기 커밋만으로 최신 코드를 복원할 수 없으므로 배포 폴더의 `artifacts/workhub-development-20261007-1.zip`과 소스 해시 명세를 함께 사용한다.

이 스냅샷 이후 현재 작업 트리에는 보고 지연 수정이 추가됐다. `src/workhub/report_parser.py`와 `ai_runtime.py`가 변경됐고, 직접 해석하는 완료 표현을 넓히고 보고 모델의 유지 시간을 30분으로 설정했다. 고정된 개발 ZIP·배포 이미지의 `20261007-1`은 수정 전 기준이며, 추가 수정의 테스트·측정·적용 버전·복구는 [성능 기록](../보고_성능_및_신뢰성_개선_명세.md)에 기록한다. 로컬 추가 적용 이미지는 `unified-work-assistant/workhub:report-latency-20261007`이다.

## 포함 범위

- Workhub·문서 비서·이전 보고 PoC 소스, 테스트와 의존성 명세.
- 최신 Outline 연동 패치, 공식 원본 아카이브와 고정 커밋·해시. `integrations/outline/prepare_source.py`로 소스를 재현한다.
- 설정·검증·배포 도구와 현재 운영·기능 문서.
- 아래 개발용 Dockerfile은 배포본의 정확한 이미지 태그에서 시작하여 소스만 덮어쓴다. 기존 런타임 의존성을 유지하며 현재 실행 컨테이너를 바꾸지 않는다.

실제 `.local`, `.private`, DB·문서·채팅·계정·모델 데이터, 비밀번호와 인증서, 캐시·빌드 산출물은 개발 ZIP에 포함하지 않는다. 현재 서비스 설정과 데이터는 별도로 보호하는 배포 묶음에 있다. ZIP은 비공개 Git 작업 트리까지 포함한 개발 인계용 사본이며, 자동으로 Git 커밋·푸시한 결과가 아니다.

## 소스 수정과 개발 이미지

배포본의 이미지 아카이브를 먼저 불러온 뒤, 이 README의 상위 프로젝트 폴더에서 실행한다. Python 서비스의 코드만 수정할 때는 의존성을 다시 내려받지 않아도 된다.

```sh
docker build -f development/Dockerfile.workhub -t workhub-dev/workhub:20261007-1 .
docker build -f development/Dockerfile.document-agent -t workhub-dev/document-agent:20261007-1 .
docker build -f development/Dockerfile.embedding-worker -t workhub-dev/embedding-worker:20261007-1 .
```

새 라이브러리가 필요한 변경은 해당 원본 Dockerfile·requirements와 잠금 파일을 함께 검토한다. 위 Dockerfile은 코드 변경용이며 의존성 설치 단계를 대신하지 않는다.

Workhub 테스트는 데이터 볼륨 없이 실행한다.

```sh
docker run --rm --network none --entrypoint python workhub-dev/workhub:20261007-1 /app/run_workhub_tests.py
```

검증한 개발 이미지를 사용할 때는 별도 테스트용 Compose에 해당 이미지 값을 지정한다. 개발 소스만 푸는 것으로 `.local/compose.json`의 실제 인증·접속 설정이 생기지는 않는다. 최초 서비스 복원·기동은 `deployment/README.md`의 절차를 따른다.

## Outline 개발

`integrations/outline`에서 공식 원본과 최신 패치를 재현한 뒤 개발용 빌드를 진행한다. Yarn 의존성을 처음 준비할 때는 네트워크가 필요하다. 기존 `migration-baseline` 태그를 덮어쓰지 않고 이번 배포 태그를 직접 사용한다.

```sh
python3 prepare_source.py
docker build -f ../../development/Dockerfile.outline-dependencies -t workhub-outline-build:20261007-1 .
docker build -f ../../development/Dockerfile.outline -t workhub-dev/outline:20261007-1 .
```

Open WebUI 도구는 컨테이너 Python 파일이 아니라 WebUI DB의 도구·필터 항목에 설치된다. `ops/build_permissions_webui_payload.py`와 `ops/install_permissions_webui.py`의 기존 설치 흐름을 사용하며, 데이터 사본과 권한 설정을 확인한 뒤 개발 환경에 적용한다.

최근 검증과 포함 기능은 `deployment/PREPARATION_REPORT.md`, 현재 소스·실행 위치별 해시는 `deployment/source-audit.json`에 기록한다. 회사 서버 적용, 실제 Ubuntu 설치와 대규모 동시 부하는 별도 작업이다.
