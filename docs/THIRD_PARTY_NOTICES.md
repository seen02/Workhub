# 제3자 소프트웨어 및 출처 고지

이 저장소 전체에 단일 MIT 또는 Apache 라이선스를 적용하지 않는다. 프로젝트별 작성물의 추가 이용 허락은 부여하지 않으며, 기존 라이선스와 별도 계약에 따른 권리는 유지한다. 상세 범위는 [LICENSE](../LICENSE), [라이선스 안내](LICENSING.md)를 따른다.

## Outline 수정본

- 원본: [outline/outline](https://github.com/outline/outline)
- 버전: **1.10.0**
- 기준 커밋: `65be53c3eb093a535ce260eb2f2da897bb07a29e`
- 원저작권 고지: `(c) 2026 General Outline, Inc.`
- 라이선스: **Business Source License 1.1**. 사용 중인 버전은 현재 오픈소스 라이선스가 아닌 소스 공개형 라이선스다.
- 원문: [Outline 원본 LICENSE](https://github.com/outline/outline/blob/65be53c3eb093a535ce260eb2f2da897bb07a29e/LICENSE), [저장소 내 사본](../LICENSES/Outline-1.10.0.txt)
- 원본 파라미터: Licensor `General Outline, Inc.`, Change Date `2030-09-01`, Change License `Apache License, Version 2.0`. 본문의 전환 시점 및 Additional Use Grant 조건을 포함해 원문 전체가 적용된다.
- 적용 대상: `unified-work-assistant/integrations/outline/patches/`의 변경 패치, 복원한 Outline 원본·수정본, 기타 위치에 포함된 Outline 파생 코드. 다른 경로에 배치하거나 패치로 배포해도 원래 조건이 사라지지 않는다.
- 변경 내용: [변경 기록](local/integrations/outline/MODIFICATIONS.md), [원본 고정 정보](../unified-work-assistant/integrations/outline/upstream.lock.json).

`production/outline/`에는 운영용 Outline 소스를 포함한다. 로컬 테스트용 `unified-work-assistant/integrations/outline/`은 원본 고정 정보와 변경 패치로 보관한다. 다운로드 아카이브·빌드 산출물·컨테이너 이미지는 제외한다. 원본 해시를 검증한 뒤 변경 패치를 적용해 소스를 복원한다. 원본 아카이브에 포함된 하위 구성 요소의 LICENSE·NOTICE 등도 보존해야 한다.

## Rocket.Chat

- 원본: [RocketChat/Rocket.Chat](https://github.com/RocketChat/Rocket.Chat)
- 설정에서 참조하는 공식 이미지: `registry.rocket.chat/rocketchat/rocket.chat:8.5.0`
- 원저작권 고지: `Copyright (c) 2015-2022 Rocket.Chat Technologies Corp.`
- Community 영역: 원본의 예외·제3자 구성 요소를 제외한 **MIT (Expat)** 라이선스.
- Enterprise 영역: `apps/meteor/ee/`, `ee/` 등에 별도 **Rocket.Chat Enterprise Edition license** 적용. 구체적 적용 범위와 예외는 원문이 정한다.
- 원문 사본: [루트 LICENSE](../LICENSES/Rocket.Chat-8.5.0.txt), [Enterprise LICENSE](../LICENSES/Rocket.Chat-Enterprise-8.5.0.txt).
- 공식 원문: [루트](https://github.com/RocketChat/Rocket.Chat/blob/8.5.0/LICENSE), [Enterprise](https://github.com/RocketChat/Rocket.Chat/blob/8.5.0/apps/meteor/ee/LICENSE).

이 저장소는 연동 코드와 설정을 보관한다. Rocket.Chat 서버 소스나 컨테이너 이미지를 이 업로드에 포함하지 않는다. 이미지 참조만으로 실행 중인 에디션·구독 상태 또는 Enterprise 기능의 사용 권한을 인증하지 않는다.

## 기존 구성 요소의 출처

프로젝트의 기존 기록에 따르면 다음 소스에서 가져와 확장했다. 아래 경로는 로컬 출처 기록이며 공식 프로젝트명이나 공개 저장소 URL을 의미하지 않는다.

| 현재 위치 | 기존 기록상 출처 | 라이선스 처리 |
|---|---|---|
| `unified-work-assistant/src/document-agent/` | `Outline/local-ai` | 기존 권리 관계 유지. 명칭이 비슷하다는 이유로 Outline 본체의 BSL을 자동 적용하거나 MIT로 변경하지 않는다. |
| `unified-work-assistant/src/report-agent/` | `ai-agent-main/ai-agent-main` | 기존 권리 관계 유지. 원본 권리자의 별도 이용 허락을 대체하지 않는다. |
| `unified-work-assistant/src/workhub/` | 통합 포털·봇·업무·권한 등의 구현 | 제3자에서 유래한 부분이 있다면 원래 조건을 유지한다. 이 업로드에서 새로운 포괄적 오픈소스 이용 허락은 부여하지 않는다. |

## 외부 실행 구성 요소 및 의존성

설정에는 Open WebUI, Authentik, Ollama, MongoDB, Redis, PostgreSQL, pgvector, Nginx, Mailpit 등의 외부 구성 요소와 Python·JavaScript 의존성이 포함된다. 이들의 실행 파일, 모델 가중치, 패키지 캐시, 데이터 볼륨은 업로드하지 않는다. 각 파일의 버전·태그·다이제스트와 upstream의 해당 버전 라이선스를 확인해야 한다.

- [Open WebUI](https://github.com/open-webui/open-webui): 버전에 따라 브랜딩 조건이 존재한다. [공식 라이선스 안내](https://docs.openwebui.com/license/). 로컬 재태깅 이미지명만으로 원본 버전이나 적용 조건을 단정하지 않는다.
- [Authentik](https://github.com/goauthentik/authentik), [Ollama](https://github.com/ollama/ollama), [MongoDB](https://github.com/mongodb/mongo), [Redis](https://github.com/redis/redis), [PostgreSQL](https://www.postgresql.org/about/licence/), [pgvector](https://github.com/pgvector/pgvector), [Nginx](https://nginx.org/LICENSE), [Mailpit](https://github.com/axllent/mailpit): 실제 사용 버전과 포함 구성 요소의 원래 조건을 따른다.
- 모델의 이용 조건은 추론 엔진의 라이선스와 별개다. 이 저장소는 모델 가중치에 별도의 이용 권한을 부여하지 않는다.

이 문서는 주요 구성 요소의 범위·출처 고지다. 전체 전이 의존성의 법률 검토 완료, 회사의 공개 승인, 상표 사용 허락, 운영 배포 적합성을 인증하는 문서가 아니다.

## 운영용 소스의 범위

`production/`은 별도 운영 폴더의 Outline·Authentik 로그인·업무 관리 API와 배포 설정이다. Rocket.Chat·Ollama·Qwen 및 AI 검색은 포함하지 않는다. Outline의 원문 조건과 하위 구성 요소의 고지를 보존한다. 기존 출처는 `production/source-origin.json`과 `production/NOTICE.txt`에 기록되어 있다.
