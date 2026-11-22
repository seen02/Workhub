# Outline 변경 고지

이 폴더는 공식 Outline의 Workhub 연동 수정본을 재현하기 위한 자료다. 공식 Outline 배포본이나 공식 유지보수 프로젝트로 표시하지 않는다.

- 원본: [outline/outline](https://github.com/outline/outline)
- 버전: `1.10.0`
- 기준 커밋: `65be53c3eb093a535ce260eb2f2da897bb07a29e`
- 원저작권자: General Outline, Inc.
- 적용 조건: [원래 Business Source License 1.1](../../../../unified-work-assistant/integrations/outline/LICENSE). 변경 패치와 수정·파생 부분도 이 조건의 적용 대상이다.
- 변경 기여: 이 Workhub 프로젝트의 기여자. 이 표기는 권리 양도나 모든 변경분의 개인 소유를 주장하지 않는다.
- 업로드 정리일: `2026-10-28`

## 주요 변경

- 컬렉션과 프로젝트의 등록·연결 해제 및 그룹 권한 연동.
- 업무 등록, 담당자·완료 기준 처리, 프로젝트별·전체 진행 통계.
- 업무 목록 본문의 칸반 및 상태 이동.
- 문서 검색과 Workhub 검색의 연결.
- 본문 목차 블록과 문서 선택 내용의 업무 등록.
- 일일 업무보고의 날짜별 보기·이월·문서 이동.
- Authentik 계정 연결과 비밀번호 변경 화면 연결.

정확한 변경 파일·내용은 `upstream.lock.json`의 `patchedFiles`와 `patches/0001-workhub-project-management.patch`를 기준으로 한다. 기존 상세 개발·검증 기록은 [README.md](README.md)에 있다.

## 원본 복원과 검증

원본 소스와 아카이브는 GitHub 사본에서 제외한다. 프로젝트 루트에서 Python 3.12 이상과 Git으로 다음을 실행한다.

```sh
python integrations/outline/prepare_source.py
python ops/verify_outline_source_patch.py
```

첫 명령은 고정된 공식 아카이브의 SHA-256을 검증하고 패치를 적용한다. 이미 소스 폴더가 있으면 덮어쓰지 않는다. 두 번째 명령은 패치가 고정 파일 목록의 현재 소스를 재현하는지 확인한다. 다운로드·빌드 의존성 및 실행용 환경 설정은 별도로 준비한다.

복원한 원본에 포함된 하위 LICENSE·NOTICE·저작권 표시는 유지한다. 원본 라이선스의 Licensor·Additional Use Grant·Change Date·Change License를 임의로 바꾸지 않는다.
