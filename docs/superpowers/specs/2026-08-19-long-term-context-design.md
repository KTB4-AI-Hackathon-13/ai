# 장기 이력(long_term_context) 컨텍스트 계약 설계

## 배경

이 서비스(AI)는 상태 없는 순수 추론 서버로, 원본 대화/이력은 전부 BE DB가 소유한다. 지금까지는
`/plan/generate` 호출 시 이번 목표에 필요한 정보(goal, template_answers, busy_dates)만 받았고,
"이 사용자가 과거에 어떤 목표를 세우고 어떻게 진행했는지", "반복적으로 드러난 선호/제약이 뭔지"는
전혀 반영하지 못했다.

이 설계는 BE가 자신의 DB를 정제해 만든 요약본을 `/plan/generate` 요청에 실어 보내면, AI가 첫
계획을 만들 때 그것을 참고하도록 하는 **입력 계약**만 정의한다. BE가 DB에서 어떻게 정제/요약하는지
(몇 개까지 포함할지, 얼마나 오래된 것까지 볼지 등)는 전적으로 BE 책임이며 이 레포의 범위 밖이다.

## 데이터 흐름

```
BE DB (사용자의 과거 확정 계획들 + 누적 선호)
   │  BE가 조회/정제
   ▼
PlanGenerateRequest.long_term_context  ──▶  AI가 프롬프트에 반영 ──▶ 첫 계획 생성
```

- `/plan/generate`(새 목표를 시작하는 첫 턴)에만 적용한다.
- `/plan/revise`에는 적용하지 않는다 — revise는 이미 `current_plan`(이번 목표 안에서의
  체크포인트)으로 맥락을 유지하므로, 목표를 가로지르는 장기 이력은 다시 볼 필요가 없다.
- AI 서비스는 이 값을 저장하지 않는다. 요청 처리 동안만 존재했다가 응답과 함께 사라진다 — 매
  요청마다 BE가 최신 상태로 다시 정제해서 보내야 한다.

필드명은 `user_history`가 아니라 `long_term_context`로 한다 — "AI 쪽에 저장된 이력"처럼 오해되는
것을 피하고, "BE가 매번 실어 보내는 요약 컨텍스트"라는 의미를 명확히 하기 위함이다.

## 스키마 변경 (`app/plan_generation/schemas.py`)

```python
class PastGoalSummary(BaseModel):
    category: Category
    goal: str
    period_days: int
    completion_status: Literal["completed", "abandoned", "in_progress"]


class LongTermContext(BaseModel):
    past_goals: List[PastGoalSummary] = Field(default_factory=list)
    preferences: List[str] = Field(
        default_factory=list,
        description="누적된 선호/제약 자유 텍스트 (예: '아침엔 시간 없음', '헬스장 장비 없음')",
    )


class PlanGenerateRequest(BaseModel):
    ...
    long_term_context: Optional[LongTermContext] = Field(
        None,
        description="BE가 정제해 전달하는 이 사용자의 과거 목표/선호 이력. 첫 목표라면 생략 가능",
    )
```

`PlanReviseRequest`, `PLAN_TURN_JSON_SCHEMA`(LLM structured output용)는 변경하지 않는다 —
`long_term_context`는 입력 전용이며 응답 스키마와 무관하다.

## 서비스 로직 (`app/plan_generation/service.py`)

`generate_plan`은 이미 `req` 전체를 `model_dump_json(exclude={"conversation_id",
"schedule_id"})`로 직렬화해 LLM에 넘기는 방식이라, `long_term_context`도 자동으로 포함된다.
별도의 가공/분기 로직은 추가하지 않는다. 값이 `None`이면 그대로 `null`로 직렬화되고, 프롬프트
규칙이 이를 "이력 없음"으로 해석하도록 한다.

## 프롬프트 변경 (`app/plan_generation/prompts.py`)

`PLAN_GENERATE_SYSTEM`에 규칙 추가:

> `long_term_context`가 주어지면 `past_goals`의 완료 패턴(예: 자주 중도 포기했는지, 완주했는지)과
> `preferences`를 계획의 난이도/구성에 반영한다. 예를 들어 과거에 고강도 계획을 자주 포기했다면
> 이번엔 더 가볍게 시작하고, `preferences`에 누적된 제약(예: "아침엔 시간 없음")은 별다른 언급이
> 없어도 계속 지킨다. `long_term_context`가 없거나 `past_goals`/`preferences`가 모두 비어있으면
> 무시하고 기존 방식대로 진행한다.

## 테스트 계획 (`tests/plan_generation/test_service.py`)

- `long_term_context` 없이(기존 기본값 `None`) 호출 시 기존 동작 회귀 없는지 확인
- `long_term_context`가 주어졌을 때 `generate_structured`에 전달되는 `user_content`에 해당
  값이 포함되는지 확인 (LLM으로 실제 잘 전달되는지 검증)

## 범위 밖

- BE DB 스키마, 이력 정제/요약 로직 (다른 레포, BE 책임)
- 이미 확정되어 진행 중인 계획을 중간에 재조정할 때 완료된 task를 식별하는 문제(`DailyTask`에
  완료 상태 필드가 없는 gap) — 별도 스펙으로 분리해서 다룬다
- 이전에 언급된 "확정 시 category가 BE로 전달되지 않는 문제" — 별도 이슈로 분리
