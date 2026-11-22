# 업무보고 모델 비교

`comparison_50.json`은 실제 직원 보고를 사용하지 않은 합성 한국어 보고 50건이다.
기존 `work_reports.json` 8건은 계산 규칙 회귀 테스트로 유지한다.

## 실행

저장소 루트에서:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:4b
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull gemma3:4b
.\.venv\Scripts\python.exe backend/evals/compare_models.py
```

두 모델이 설치되어 있어야 실행한다. 앱의 기본 모델 설정은 바꾸지 않는다.
DB 저장 없이 `LocalProvider`와 실제 `normalize_parsed`를 호출한다.
결과는 매 사례마다 `results/comparison.json`에 기록되며, 재실행 시 갱신된다.

## 평가 설계

- 명시 진행률, 개수 비율, 진행률 미상, 일부 완료, 부정·예정 표현, 복수 업무,
  실제 이슈, 해결된 이슈·이슈 없음, 시간, 날짜·과거·목표 수치: 각 5건.
- 기대값을 먼저 정의하고 동일한 50건을 Qwen3와 Gemma에 순차 입력한다.
- 두 모델에 같은 앱 Prompt, Pydantic Schema, temperature=0, 120초 timeout,
  최대 2회 시도를 적용한다. Gemma는 thinking 모델이 아니므로 `think` 옵션만 제외한다.
- Mock으로 전환하지 않는다. 모델 응답 실패는 실패로 기록한다.
- 원본과 앱 후처리 결과를 별도로 채점하여 계산 코드가 만든 회귀를 식별한다.
- 진행률·상태·시간은 기대값과 일치 여부를 검사한다. 업무명·이슈·다음 작업은
  핵심 키워드 중 하나 이상 포함하는지를 검사한다. 이슈·다음 작업 없음은 null을 검사한다.
- 업무명이 복수 업무를 모두 포함하는지, 불필요한 설명이 섞였는지 등은 자동 키워드 점수만으로
  알 수 없다. 이 점수는 의미 정확도나 실제 직원 수정률이 아니다.
- 시간 항목은 시간을 명시한 5건만 채점한다. 나머지 사례의 시간 환각은 별도 검토 대상이다.
- 첫 요청의 모델 로딩과 재시도 시간을 응답시간에 포함한다. 단일 실행이므로
  실행 순서·GPU 상태·캐시 효과가 있으며 결과를 보편적 모델 성능으로 해석하지 않는다.
- 모델의 confidence는 자기 보고값이며 정답률이나 보정된 확률로 사용하지 않는다.
- 복수 업무의 전체 진행률을 계산할 가중치가 없으면 기대값은 null이다.

## 다음 활용

2026-09-07 진행률 수정 후 기본 모델은 Gemma 3 4B다. 최초 비교 파일은 유지하며
재평가는 별도 디렉터리에 기록한다:

```powershell
.\.venv\Scripts\python.exe backend/evals/compare_models.py --models gemma3:4b --output backend/evals/results/gemma_regression
.\.venv\Scripts\python.exe backend/evals/compare_models.py --models gemma3:4b --dataset backend/evals/additional_synthetic_10.json --output backend/evals/results/additional_synthetic
```

추가 10건도 사용자의 요청으로 만든 합성 예시다. 실제 익명화 보고 검증으로 표시하지 않는다.
원본 모델의 null/추정값은 그대로 보존하고 수정된 후처리 결과와 비교한다.

실제 익명화 보고로 확장할 때에는 담당자가 기대값을 검토하고 별도의 미사용 평가셋을 남긴다.
Prompt나 후처리 개선에는 개발 평가셋을 사용하고 최종 비교는 미사용 평가셋에서 수행한다.
