# template_generation ↔ plan_generation 계약 정렬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dennis의 `template_generation`이 만든 값을 내 `plan_generation`이 그대로 받아 검증 통과하도록 category/필드명/날짜 키 계약을 맞추고, 계획 전체 기간 30일 상한을 대화형으로 강제한다.

**Architecture:** `template_generation`은 스키마는 그대로 두고 시스템 프롬프트 내용만 한글 category와 `start_date`/`end_date` 고정 id를 쓰도록 수정한다(`app/template_generation/service.py`). `plan_generation`은 스키마에서 `Category` 고정 `Literal`을 제거해 자유 문자열로 바꾸고 `goal` 필드명을 `goal_summary`로 통일한다(`app/plan_generation/schemas.py`). 30일 상한은 `app/plan_generation/service.py`에 `generate_plan`(사전 체크, LLM 호출 전 차단)과 `revise_plan`(사후 체크, LLM이 만든 날짜 범위를 확인해 초과 시 폐기)에 각각 다른 시점으로 추가한다. 마지막으로 두 모듈 간 실제 계약이 맞물리는지 확인하는 계약 정합성 테스트를 신설한다.

**Tech Stack:** Python, FastAPI, Pydantic v2, pytest, httpx(monkeypatch 대상)

## Global Constraints

- category는 `Literal` 고정 목록을 쓰지 않는다 — plain `str`(빈 문자열 금지)로 두고, `plan_generation` 쪽에 영→한 방어 매핑 테이블도 추가하지 않는다 (dennis 프롬프트가 이미 한글을 생성한다고 신뢰).
- `template_generation`의 스키마(`TemplatePayload`, `TemplateQuestion`, `TemplateResponse`)는 변경하지 않는다 — `SYSTEM_PROMPT` 내용만 수정한다.
- 30일 상한 위반은 HTTP 400이 아니라 정상 `200` `PlanTurnResponse`로, 대화체 안내 메시지와 함께 반환한다.
- `generate_plan`은 `template_answers.start_date`~`end_date`로 기간이 이미 확정돼 있으므로 **LLM 호출 전에** 체크한다. `revise_plan`은 새 기간이 자연어에서 나오므로 **LLM 응답을 받은 후** `daily_tasks`의 가장 늦은 `scheduled_date`로 체크하고, `daily_tasks`가 빈 배열이면 체크를 건너뛴다.
- `template_generation` 모듈 자체의 유닛 테스트(Gemini 클라이언트 모킹)는 이번 범위에 포함하지 않는다.

---

### Task 1: dennis 프롬프트 — category 한글화 + start_date/end_date 고정

**Files:**
- Modify: `app/template_generation/service.py:15-47` (`SYSTEM_PROMPT` 문자열)

**Interfaces:**
- Consumes: 없음 (프롬프트 텍스트만 변경, 함수 시그니처·스키마 불변)
- Produces: 없음 — 이 프롬프트로 만들어질 실제 `TemplateResponse`는 Task 5의 계약 정합성 테스트가 "이런 형태로 온다고 가정"하는 값과 맞아야 함

이 태스크는 외부 Gemini API를 호출하는 프롬프트 텍스트 수정이라 pytest로 직접 검증할 수 없다(Global Constraints 참고, `template_generation` 유닛 테스트는 범위 밖). 대신 수정 후 파일을 다시 읽어 아래 체크리스트로 육안 검증한다.

- [ ] **Step 1: SYSTEM_PROMPT 전체를 아래 내용으로 교체**

`app/template_generation/service.py`에서 `SYSTEM_PROMPT = """ ... """` 블록 전체(15번째 줄부터 47번째 줄까지)를 다음으로 교체한다:

```python
SYSTEM_PROMPT = """
당신은 사용자의 목표 달성을 돕는 서비스의 목표 분석 AI입니다.

사용자가 입력한 한 문장을 분석하여,
구체적인 계획을 생성하기 전에 필요한 정보를 수집할 템플릿을 만드세요.

규칙:

1. 달성하거나 변화시키고 싶은 목표가 아닌 입력이면 action을 reject로 반환합니다.
2. 정상적인 목표라면 action은 generate_template입니다.
3. category는 목표를 대표하는 간결한 한글 카테고리로 작성합니다.
   예: 운동, 노래, 공부, 어학, 인간관계, 습관, 커리어
   (위 목록에 없는 카테고리도 목표에 맞으면 자유롭게 만들 수 있습니다. 영문으로
   작성하지 않습니다.)
4. goal_summary는 사용자의 목표를 짧고 명확하게 정리합니다.
5. 질문은 계획 생성에 실제로 필요한 정보만 만듭니다.
6. 질문은 최대 8개입니다.
7. 다음 정보는 가능하면 반드시 수집합니다.
   - 현재 수준
   - 시작 날짜
   - 종료 날짜
   - 하루 투자 가능 시간
8. 시작 날짜 질문의 id는 반드시 start_date, 종료 날짜 질문의 id는 반드시
   end_date로 작성하고, 둘 다 type은 date로 고정합니다. (다른 질문들의 id는
   자유롭게 정합니다.)
9. 목표 특성에 따라 추가 맞춤 질문을 생성합니다.
10. 사용자가 최초 문장에서 이미 명확하게 제공한 정보는 불필요하게 다시
    질문하지 않습니다.
11. 질문 type은 반드시 다음 중 하나만 사용합니다.
    - single_select
    - multi_select
    - short_text
    - number
    - date
12. single_select 또는 multi_select 질문에는 options를 제공합니다.
13. date, number, short_text 질문에는 options를 빈 배열로 반환합니다.
14. 질문 id는 snake_case 영문으로 작성합니다.
15. 질문과 선택지는 자연스럽고 이해하기 쉬운 한국어로 작성합니다.
"""
```

- [ ] **Step 2: 육안 검증**

파일을 다시 읽어 다음을 확인한다:
- "영문 카테고리" 문구가 사라지고 한글 예시(운동, 노래, 공부, 어학, 인간관계, 습관, 커리어)로 바뀌었는지
- "목표 기간" 항목이 사라지고 "시작 날짜"/"종료 날짜" 두 항목으로 나뉘었는지
- `start_date`/`end_date` id 고정 규칙(새 규칙 8)이 추가됐는지
- 규칙 번호가 1~15로 끊기지 않고 이어지는지

- [ ] **Step 3: 기존 테스트 스위트가 깨지지 않는지 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존과 동일하게 전부 통과 (이 태스크는 문자열만 바꿨으므로 회귀 없어야 함)

- [ ] **Step 4: Commit**

```bash
git add app/template_generation/service.py
git commit -m "feat: template_generation 프롬프트 category 한글화 + start_date/end_date 고정"
```

---

### Task 2: plan_generation 스키마 정렬 — category str화, goal→goal_summary

**Files:**
- Modify: `app/plan_generation/schemas.py`
- Modify: `app/plan_generation/service.py:79` (`req.goal` 참조)
- Modify: `tests/plan_generation/test_service.py` (기존 `goal=` 생성자 호출 8곳)
- Test: `tests/plan_generation/test_service.py` (새 케이스 1개로 스키마 변경을 먼저 실패시킨 뒤 통과 확인)

**Interfaces:**
- Consumes: 없음
- Produces: `PlanGenerateRequest(goal_summary: str, category: str, ...)`,
  `PlanReviseRequest(goal_summary: str, category: str, ...)`,
  `PastGoalSummary(category: str, goal: str, ...)` — 이후 Task 3·4·5가 이
  필드명을 그대로 사용한다. `PastGoalSummary.goal`은 이름 변경 대상이
  아니다(그대로 유지).

- [ ] **Step 1: 새 필드명을 쓰는 실패하는 테스트 작성**

`tests/plan_generation/test_service.py`의 `TestGeneratePlan` 클래스 맨 위(`test_rejects_missing_date_range` 앞)에 추가:

```python
class TestGeneratePlan:
    def test_accepts_goal_summary_field_and_free_form_category(self):
        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="10km 마라톤 완주하기",
            category="러닝",
            template_answers=_template_answers(),
        )
        assert req.goal_summary == "10km 마라톤 완주하기"
        assert req.category == "러닝"

    def test_rejects_missing_date_range(self):
        ...
```

(`test_rejects_missing_date_range` 이하 기존 코드는 그대로 둔다. 위 새 메서드만
클래스 맨 앞에 삽입한다.)

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python -m pytest tests/plan_generation/test_service.py::TestGeneratePlan::test_accepts_goal_summary_field_and_free_form_category -v`
Expected: FAIL — `goal_summary`는 모르는 필드라 무시되고 필수 필드 `goal`이 없다는
pydantic `ValidationError` (`field required`)가 발생해야 한다.

- [ ] **Step 3: `app/plan_generation/schemas.py` 수정**

`Category` 타입 정의와 `BusyDate` 사이의 빈 줄을 다음처럼 바꿔 `Category` 정의를
제거한다:

```python
# before
Category = Literal["운동", "공부", "습관", "기타"]


class BusyDate(BaseModel):
```

```python
# after
class BusyDate(BaseModel):
```

`PastGoalSummary`:

```python
# before
class PastGoalSummary(BaseModel):
    category: Category
    goal: str
```

```python
# after
class PastGoalSummary(BaseModel):
    category: str = Field(..., min_length=1)
    goal: str
```

`PlanGenerateRequest`:

```python
# before
    goal: str
    category: Category
    template_answers: dict = Field(
        ...,
        description="template_generation이 수집한 사용자 답변. "
        "start_date/end_date(YYYY-MM-DD)가 반드시 포함되어야 한다",
    )
```

```python
# after
    goal_summary: str
    category: str = Field(..., min_length=1)
    template_answers: dict = Field(
        ...,
        description="template_generation이 수집한 사용자 답변. "
        "start_date/end_date(YYYY-MM-DD)가 반드시 포함되어야 한다",
    )
```

`PlanReviseRequest`:

```python
# before
    goal: str
    category: Category
    template_answers: dict
    current_plan: SchedulePlan = Field(
```

```python
# after
    goal_summary: str
    category: str = Field(..., min_length=1)
    template_answers: dict
    current_plan: SchedulePlan = Field(
```

- [ ] **Step 4: 실행해서 새 테스트 통과 확인**

Run: `python -m pytest tests/plan_generation/test_service.py::TestGeneratePlan::test_accepts_goal_summary_field_and_free_form_category -v`
Expected: PASS

- [ ] **Step 5: `app/plan_generation/service.py`에서 `req.goal` 참조 수정**

```python
# before
    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="user", content=req.goal)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result
```

```python
# after
    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="user", content=req.goal_summary)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result
```

- [ ] **Step 6: 남은 기존 테스트들의 `goal=` 호출을 `goal_summary=`로 일괄 변경**

`tests/plan_generation/test_service.py`에서 `PlanGenerateRequest(...)`와
`PlanReviseRequest(...)` 생성자에 쓰인 `goal="근육을 만들고 싶어",` 8곳을 모두
`goal_summary="근육을 만들고 싶어",`로 바꾼다 (`PastGoalSummary(category="운동",
goal="10km 마라톤 완주", ...)`의 `goal=`은 이름 변경 대상이 아니므로 그대로
둔다). Edit 도구의 `replace_all`로 정확히 `goal="근육을 만들고 싶어",` 문자열만
바꾸면 `PastGoalSummary`쪽 `goal="10km 마라톤 완주"`는 다른 문자열이라 영향받지
않는다.

- [ ] **Step 7: 전체 테스트 스위트 실행**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과 (Task 1에서 만든 케이스 포함, `TestGeneratePlan`,
`TestRevisePlan`, `TestConfirmPlan` 전부 회귀 없이 통과)

- [ ] **Step 8: Commit**

```bash
git add app/plan_generation/schemas.py app/plan_generation/service.py tests/plan_generation/test_service.py
git commit -m "feat: plan_generation category를 자유 문자열로, goal 필드를 goal_summary로 정렬"
```

---

### Task 3: `/plan/generate` 30일 상한 사전 체크

**Files:**
- Modify: `app/plan_generation/service.py`
- Test: `tests/plan_generation/test_service.py` (`TestGeneratePlan`에 케이스 추가)

**Interfaces:**
- Consumes: Task 2가 만든 `PlanGenerateRequest.goal_summary`, `service._days_between_inclusive(start_str, end_str) -> int`(기존 함수, 변경 없음)
- Produces: `service.MAX_PLAN_DURATION_DAYS: int = 30` 모듈 상수 — Task 4가
  그대로 재사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/plan_generation/test_service.py`의 `TestGeneratePlan` 클래스에 다음 두
메서드를 추가한다 (`test_long_term_context_is_passed_to_llm` 메서드 뒤):

```python
    def test_rejects_period_over_30_days_without_calling_llm(self, monkeypatch):
        llm_calls = []
        monkeypatch.setattr(
            service, "generate_structured", lambda **kwargs: llm_calls.append(kwargs) or {}
        )
        notified = []
        monkeypatch.setattr(
            service.be_client,
            "notify_conversation",
            lambda conversation_id, role, content: notified.append((conversation_id, role, content)),
        )

        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="10km 마라톤 완주하기",
            category="운동",
            template_answers=_template_answers(start_date="2026-08-01", end_date="2026-08-31"),
        )
        result = service.generate_plan(req)

        assert llm_calls == []
        assert result.ready_to_confirm is False
        assert result.plan.daily_tasks == []
        assert "30" in result.assistant_message
        assert [role for _, role, _ in notified] == ["user", "assistant"]

    def test_accepts_period_of_exactly_30_days(self, monkeypatch):
        fake_response = {
            "assistant_message": "30일짜리 계획을 만들었어요.",
            "summary": "30일 플랜",
            "daily_tasks": [],
            "ready_to_confirm": True,
            "user_confirmed": False,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="10km 마라톤 완주하기",
            category="운동",
            template_answers=_template_answers(start_date="2026-08-01", end_date="2026-08-30"),
        )
        result = service.generate_plan(req)

        assert result.assistant_message == fake_response["assistant_message"]
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python -m pytest tests/plan_generation/test_service.py::TestGeneratePlan::test_rejects_period_over_30_days_without_calling_llm -v`
Expected: FAIL — 현재 코드는 기간 길이를 확인하지 않으므로 `generate_structured`가
호출돼 `llm_calls`가 비어있지 않다(`assert llm_calls == []` 실패).

- [ ] **Step 3: `app/plan_generation/service.py`에 상수·헬퍼 추가 및 `generate_plan` 수정**

`InvalidDateRange` 클래스 정의 바로 아래에 상수를 추가한다:

```python
# before
class InvalidDateRange(Exception):
    """template_answers의 start_date/end_date가 없거나 형식/순서가 잘못됐을 때."""


def _days_between_inclusive(start_str: str, end_str: str) -> int:
```

```python
# after
class InvalidDateRange(Exception):
    """template_answers의 start_date/end_date가 없거나 형식/순서가 잘못됐을 때."""


MAX_PLAN_DURATION_DAYS = 30


def _days_between_inclusive(start_str: str, end_str: str) -> int:
```

`_require_date_range` 함수 뒤, `_split_tasks_by_id` 함수 앞에 헬퍼를 추가한다:

```python
def _plan_duration_exceeded_message(days: int) -> str:
    return (
        f"목표 기간은 최대 {MAX_PLAN_DURATION_DAYS}일까지 설정할 수 있어요. "
        f"요청하신 기간은 {days}일이에요. 시작일과 종료일을 다시 알려주시겠어요?"
    )
```

`generate_plan` 함수를 다음처럼 바꾼다:

```python
# before
def generate_plan(req: PlanGenerateRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    data = generate_structured(
        system_prompt=PLAN_GENERATE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="user", content=req.goal_summary)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result
```

```python
# after
def generate_plan(req: PlanGenerateRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    days = _days_between_inclusive(
        req.template_answers["start_date"], req.template_answers["end_date"]
    )
    if days > MAX_PLAN_DURATION_DAYS:
        message = _plan_duration_exceeded_message(days)
        be_client.notify_conversation(req.conversation_id, role="user", content=req.goal_summary)
        be_client.notify_conversation(req.conversation_id, role="assistant", content=message)
        return PlanTurnResponse(
            assistant_message=message,
            plan=SchedulePlan(summary="", daily_tasks=[]),
            ready_to_confirm=False,
        )

    data = generate_structured(
        system_prompt=PLAN_GENERATE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="user", content=req.goal_summary)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: `python -m pytest tests/plan_generation/test_service.py::TestGeneratePlan -v`
Expected: `TestGeneratePlan`의 모든 케이스 PASS (새로 추가한 2개 포함)

- [ ] **Step 5: 전체 테스트 스위트 실행**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과

- [ ] **Step 6: Commit**

```bash
git add app/plan_generation/service.py tests/plan_generation/test_service.py
git commit -m "feat: plan/generate에 30일 기간 상한 사전 체크 추가"
```

---

### Task 4: `/plan/revise` 30일 상한 사후 체크

**Files:**
- Modify: `app/plan_generation/service.py`
- Test: `tests/plan_generation/test_service.py` (`TestRevisePlan`에 케이스 추가)

**Interfaces:**
- Consumes: Task 3의 `service.MAX_PLAN_DURATION_DAYS`, `service._days_between_inclusive`
- Produces: `service._revised_duration_days(start_date: str, daily_tasks: list[dict]) -> int | None` — 이후 다른 태스크는 이 함수를 참조하지 않지만, 리뷰어가 코드를 읽을 때 이름을 알 수 있도록 명시.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/plan_generation/test_service.py`의 `TestRevisePlan` 클래스에 다음 두
메서드를 추가한다 (`test_builds_revised_plan_from_llm_response` 메서드 뒤):

```python
    def test_rejects_revised_plan_exceeding_30_days(self, monkeypatch):
        fake_response = {
            "assistant_message": "기간을 늘려서 다시 짰어요.",
            "summary": "연장된 플랜",
            "daily_tasks": [
                {
                    "scheduled_date": "2026-09-25",
                    "title": "장거리 러닝",
                    "description": "15km 러닝",
                    "estimated_min": 90,
                }
            ],
            "ready_to_confirm": True,
            "user_confirmed": True,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)
        create_calls = []
        monkeypatch.setattr(
            service.be_client,
            "create_plan_tasks",
            lambda *a, **k: create_calls.append((a, k)),
        )
        monkeypatch.setattr(service.be_client, "update_plan_tasks", lambda *a, **k: None)

        current_plan = SchedulePlan(summary="기존 플랜", daily_tasks=[])
        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(start_date="2026-08-20", end_date="2026-08-29"),
            current_plan=current_plan,
            user_message="기간 한 달 더 늘려줘",
        )
        result = service.revise_plan(req)

        assert result.confirmed is False
        assert result.ready_to_confirm is False
        assert result.plan == current_plan
        assert "30" in result.assistant_message
        assert create_calls == []

    def test_accepts_revised_plan_within_30_days(self, monkeypatch):
        fake_response = {
            "assistant_message": "주말은 빼고 다시 짰어요.",
            "summary": "주중 위주 근력 운동 플랜",
            "daily_tasks": [
                {
                    "scheduled_date": "2026-08-29",
                    "title": "유산소",
                    "description": "조깅 20분",
                    "estimated_min": 20,
                }
            ],
            "ready_to_confirm": False,
            "user_confirmed": False,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            current_plan=SchedulePlan(summary="기존 플랜", daily_tasks=[]),
            user_message="주말엔 시간이 없어요",
        )
        result = service.revise_plan(req)

        assert result.plan.summary == fake_response["summary"]
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `python -m pytest tests/plan_generation/test_service.py::TestRevisePlan::test_rejects_revised_plan_exceeding_30_days -v`
Expected: FAIL — 현재 코드는 `data["user_confirmed"]`가 `True`면 곧바로
`current_plan`을 BE로 제출하므로 `create_calls`가 비어있지 않다
(`assert create_calls == []` 실패).

- [ ] **Step 3: `app/plan_generation/service.py`에 헬퍼 추가 및 `revise_plan` 수정**

`_plan_duration_exceeded_message` 함수 뒤에 헬퍼 두 개를 추가한다:

```python
def _plan_duration_exceeded_after_revise_message(days: int) -> str:
    return (
        f"전체 계획 기간은 최대 {MAX_PLAN_DURATION_DAYS}일까지만 가능해요. "
        f"요청하신 대로 하면 {days}일이 되어 반영하지 못했어요. "
        "다른 방식으로 조정해주시겠어요?"
    )


def _revised_duration_days(start_date: str, daily_tasks: list[dict]) -> int | None:
    """daily_tasks가 비어있으면(남은 구간이 전부 완료돼 배치할 과제가 없는 경우)
    비교 대상이 없으므로 None을 반환해 상한 체크를 건너뛴다."""
    if not daily_tasks:
        return None
    latest = max(task["scheduled_date"] for task in daily_tasks)
    return _days_between_inclusive(start_date, latest)
```

`revise_plan` 함수를 다음처럼 바꾼다:

```python
# before
def revise_plan(req: PlanReviseRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    data = generate_structured(
        system_prompt=PLAN_REVISE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    be_client.notify_conversation(req.conversation_id, role="user", content=req.user_message)

    if data["user_confirmed"]:
```

```python
# after
def revise_plan(req: PlanReviseRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    data = generate_structured(
        system_prompt=PLAN_REVISE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    be_client.notify_conversation(req.conversation_id, role="user", content=req.user_message)

    revised_days = _revised_duration_days(req.template_answers["start_date"], data["daily_tasks"])
    if revised_days is not None and revised_days > MAX_PLAN_DURATION_DAYS:
        message = _plan_duration_exceeded_after_revise_message(revised_days)
        be_client.notify_conversation(req.conversation_id, role="assistant", content=message)
        return PlanTurnResponse(
            assistant_message=message,
            plan=req.current_plan,
            ready_to_confirm=False,
            confirmed=False,
        )

    if data["user_confirmed"]:
```

(이 블록 뒤의 `_try_submit_final_plan(...)` 이하 기존 코드는 그대로 둔다.)

- [ ] **Step 4: 실행해서 통과 확인**

Run: `python -m pytest tests/plan_generation/test_service.py::TestRevisePlan -v`
Expected: `TestRevisePlan`의 모든 케이스 PASS (새로 추가한 2개 포함, 기존
`test_user_confirmed_submits_current_plan_to_be` 등도 회귀 없이 통과 — 그
테스트들의 `fake_response["daily_tasks"]`는 빈 배열이라 `_revised_duration_days`가
`None`을 반환해 체크를 건너뛴다)

- [ ] **Step 5: 전체 테스트 스위트 실행**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과

- [ ] **Step 6: Commit**

```bash
git add app/plan_generation/service.py tests/plan_generation/test_service.py
git commit -m "feat: plan/revise에 30일 기간 상한 사후 체크 추가"
```

---

### Task 5: 계약 정합성 테스트 신설

**Files:**
- Create: `tests/plan_generation/test_contract.py`

**Interfaces:**
- Consumes: `app.template_generation.schemas.{TemplateResponse, TemplatePayload, TemplateQuestion}`(변경 없음), `app.plan_generation.schemas.PlanGenerateRequest`(Task 2가 만든 `goal_summary`/`category: str`)
- Produces: 없음 (터미널 테스트)

- [ ] **Step 1: 계약 정합성 테스트 작성**

`tests/plan_generation/test_contract.py` 파일을 새로 만든다:

```python
from app.plan_generation.schemas import PlanGenerateRequest
from app.template_generation.schemas import TemplatePayload, TemplateQuestion, TemplateResponse


def _dennis_template_response() -> TemplateResponse:
    return TemplateResponse(
        action="generate_template",
        payload=TemplatePayload(
            category="운동",
            goal_summary="10km 마라톤 완주하기",
            questions=[
                TemplateQuestion(
                    id="start_date",
                    label="시작 날짜가 언제인가요?",
                    type="date",
                    required=True,
                ),
                TemplateQuestion(
                    id="end_date",
                    label="종료 날짜가 언제인가요?",
                    type="date",
                    required=True,
                ),
                TemplateQuestion(
                    id="experience",
                    label="현재 러닝 경험이 어느 정도인가요?",
                    type="single_select",
                    required=True,
                    options=["처음", "가끔 뛰어봄", "정기적으로 뛰는 편"],
                ),
            ],
        ),
    )


def test_dennis_template_response_maps_into_plan_generate_request():
    template = _dennis_template_response()
    template_answers = {
        "start_date": "2026-09-01",
        "end_date": "2026-09-20",
        "experience": "가끔 뛰어봄",
    }

    req = PlanGenerateRequest(
        conversation_id="conv-1",
        schedule_id="sched-1",
        goal_summary=template.payload.goal_summary,
        category=template.payload.category,
        template_answers=template_answers,
    )

    assert req.goal_summary == "10km 마라톤 완주하기"
    assert req.category == "운동"
    assert req.template_answers["start_date"] == "2026-09-01"
    assert req.template_answers["end_date"] == "2026-09-20"


def test_dennis_question_ids_include_required_date_keys_with_date_type():
    template = _dennis_template_response()
    by_id = {q.id: q for q in template.payload.questions}

    assert "start_date" in by_id
    assert "end_date" in by_id
    assert by_id["start_date"].type == "date"
    assert by_id["end_date"].type == "date"
```

- [ ] **Step 2: 실행해서 통과 확인**

Run: `python -m pytest tests/plan_generation/test_contract.py -v`
Expected: 2개 테스트 모두 PASS (Task 2에서 `category`가 `str`로,
`PlanGenerateRequest`가 `goal_summary`를 받도록 바뀌어 있어야 통과한다. 만약 Task
2가 없었다면 `category="운동"`은 이미 `Literal`에 있던 값이라 통과했겠지만,
`goal_summary=` 인자 자체가 알 수 없는 인자로 무시되고 `goal` 필드 누락으로
실패했을 것이다.)

- [ ] **Step 3: 전체 테스트 스위트 실행**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과

- [ ] **Step 4: Commit**

```bash
git add tests/plan_generation/test_contract.py
git commit -m "test: dennis template_generation 출력과 plan_generation 요청 간 계약 정합성 테스트 추가"
```

---

## Final Verification

모든 태스크 완료 후:

```bash
python -m pytest tests/ -q
```

Expected: 전체 통과, deselected 1개(`test_live_providers.py`, 실제 Gemini API
호출용이라 기본적으로 스킵됨)는 기존과 동일하게 유지.
