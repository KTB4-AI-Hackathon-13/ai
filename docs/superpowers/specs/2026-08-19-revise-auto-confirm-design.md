# /plan/revise 내 확정 의도 자동 감지 설계

## 배경

기존 구조는 "사용자가 계획을 확정했다"는 판단을 FE/BE가 하고(예: 확정 버튼 클릭), 그 결과로
`/plan/confirm`을 호출했다. 이 판단을 AI 서비스(LLM) 쪽으로 가져와, 사용자가 대화 중
자연어로 확정 의사를 밝히면 그 자리에서 BE로 최종 계획을 전송하도록 한다.

## 전체 흐름

```
generate ─▶ revise ─▶ revise ─▶ revise (user_confirmed=true 감지)
                                     │
                                     ▼
                          service가 즉시 submit_final_plan() 호출
                                     │
                                     ▼
                    응답에 confirmed=true, submitted=true/false 포함
```

- `/plan/generate`, `/plan/revise` 요청에 `schedule_id` 필수 필드 추가 (BE가 대화 시작
  시점부터 실어 보냄)
- `/plan/revise`가 매 턴마다 LLM에게 "이번 `user_message`가 수정 요청인지 확정 의사표시인지"를
  함께 판단시킴 (`user_confirmed` 필드)
- 확정으로 판단되면 서비스가 그 자리에서 `be_client.submit_final_plan(schedule_id,
  current_plan)`을 호출한다. 이때 전송하는 계획은 **LLM이 새로 생성한 게 아니라
  `current_plan`을 그대로 사용** — 확정 순간에 계획 내용이 의도치 않게 바뀌는 것을 방지
- `POST /plan/confirm`은 수동 폴백 경로로 그대로 남긴다 (FE가 명시적 확정 버튼을 두는
  경우를 대비한 안전망 겸 통합테스트/디버깅용). 실패 시 기존처럼 502를 던지는 동작 유지

## 스키마 변경 (`app/plan_generation/schemas.py`)

`PlanGenerateRequest`, `PlanReviseRequest`에 `schedule_id: str` 필수 필드 추가.

`PlanTurnResponse`에 필드 추가:
- `confirmed: bool = False` — 이번 턴에 사용자가 확정 의사를 밝혔는지
- `submitted: bool | None = None` — `confirmed=True`일 때만 의미 있음 (BE 전송 성공 여부)

`PLAN_TURN_JSON_SCHEMA`(strict structured output용)에 `user_confirmed: boolean` 필드
추가, `required`에도 포함.

`ready_to_confirm`(AI가 보기에 계획이 안정적인지 판단하는 참고용 신호)과
`user_confirmed`(방금 사용자 발화가 확정 의사표시였는지 판단)는 별개 필드로 유지한다.

## 서비스 로직 (`app/plan_generation/service.py`)

`revise_plan`에서 LLM 응답의 `user_confirmed`가 `true`이면:
1. `req.current_plan`을 그대로 사용해 `be_client.submit_final_plan(req.schedule_id,
   req.current_plan.model_dump())` 호출
2. 호출이 `httpx.HTTPError`를 던지면 예외를 상위로 전파하지 않고 잡아서
   `submitted=False`로 응답 — 대화가 끊기지 않고 사용자에게 재시도 안내
3. `assistant_message`는 LLM이 생성한 문구 대신 서비스가 고정 문구로 덮어씀:
   - 성공: "네, 이 계획으로 확정할게요!"
   - 실패: "계획 확정 요청을 받았는데 저장 중 문제가 생겼어요. 잠시 후 다시 시도해주세요."
4. 응답의 `plan`은 `req.current_plan`, `confirmed=True`, `ready_to_confirm=True`

`user_confirmed`가 `false`이면 기존 로직(LLM이 만든 `plan`을 그대로 응답)을 그대로 사용.

`router.py`, `be_client.py`는 변경하지 않는다.

## 프롬프트 변경 (`app/plan_generation/prompts.py`)

`PLAN_REVISE_SYSTEM`에 규칙 추가:

> user_message가 계획에 대한 수정/피드백이 아니라 "이대로 확정할게요", "좋아요 이걸로
> 할게요", "네 진행해주세요" 같은 명확한 승인/확정 의사표시라면 user_confirmed를 true로
> 설정한다. 조금이라도 수정 요청이 섞여 있거나("이대로 좋은데 마지막날만 빼줘") 의도가
> 불명확하면 false로 설정한다. user_confirmed가 true일 때 summary/daily_tasks는
> current_plan과 동일하게 그대로 반환한다(변경하지 않는다).

원칙: **애매하면 무조건 false(수정 취급)**. 오탐(false positive)으로 확정 안 한 계획이
BE로 잘못 전송되는 리스크가, 반대(진짜 확정을 한 턴 더 물어보는 것)보다 크다.

## 테스트 계획 (`tests/plan_generation/test_service.py`)

- `user_confirmed=True` + BE 전송 성공 → `confirmed=True, submitted=True`, 응답
  `plan`이 `current_plan`과 동일한지, `submit_final_plan`이 올바른 인자로 호출됐는지 확인
- `user_confirmed=True` + BE 전송 실패(`submit_final_plan`이 `httpx.HTTPError` 발생) →
  `submitted=False`, 예외가 상위로 전파되지 않는지 확인
- `user_confirmed=False` → 기존 수정 흐름 회귀 확인
- `schedule_id` 필드 추가에 맞춰 기존 테스트 fixture들 업데이트

## 범위 밖

- `/plan/generate`(첫 턴)에서의 확정 의도 감지는 다루지 않는다 — 첫 턴에 계획을 아직
  보여주기 전이라 "확정"이 성립하지 않음
- 실제 LLM tool/function-calling API 도입은 하지 않는다 — 기존 structured output
  패턴(JSON schema 확장)으로 충분
