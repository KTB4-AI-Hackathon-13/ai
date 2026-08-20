"""jena 담당 — plan_generation 모듈의 요청/응답 스키마.

흐름: dennis의 template_generation이 사용자와 대화하며 goal/category/template_answers를
채우고 나면, 이 모듈이 넘겨받아 BE가 보내준 캘린더 정보(busy_dates)를 참고해 일별
계획표(daily_tasks)를 만든다. 계획은 한 번에 확정되지 않을 수 있어 대화로 조정하는
과정(/plan/revise)을 거치고, 사용자가 최종 확정하면(/plan/confirm) BE로 결과를 전송한다.

주의: 하루 작업 개수 상한(5개) 같은 캘린더 반영 여부의 최종 검증은 BE가 한다 — 이
서비스는 참고용 busy_dates만 받고, 강제 스킵/재배치 로직은 두지 않는다.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

class BusyDate(BaseModel):
    """BE가 사용자 캘린더를 스캔해 전처리한 기존 일정. 참고용 힌트일 뿐, 강제 규칙은 아니다."""

    date: str = Field(..., description="YYYY-MM-DD")
    event_count: int = Field(..., description="그 날짜에 이미 잡힌 일정 개수")
    all_day: bool = Field(False, description="하루 종일 막혀 있는 일정(출장/휴가 등) 여부")


class DailyTask(BaseModel):
    scheduled_date: str = Field(..., description="YYYY-MM-DD. 이 작업을 배치한 실제 날짜")
    title: str
    description: str
    estimated_min: int = Field(..., ge=1, description="소요 시간(분). 0은 허용하지 않는다.")


class SchedulePlan(BaseModel):
    summary: str
    daily_tasks: List[DailyTask]


class PastGoalSummary(BaseModel):
    category: str = Field(..., min_length=1)
    goal: str
    period_days: int
    completion_status: Literal["completed", "abandoned", "in_progress"]


class LongTermContext(BaseModel):
    """BE가 사용자 DB를 정제해 전달하는 과거 목표/선호 요약. AI 서비스는 저장하지 않고
    매 /plan/generate 요청마다 그대로 전달받아 프롬프트에만 반영한다."""

    past_goals: List[PastGoalSummary] = Field(default_factory=list)
    preferences: List[str] = Field(
        default_factory=list,
        description="누적된 선호/제약 자유 텍스트 (예: '아침엔 시간 없음', '헬스장 장비 없음')",
    )


class PlanGenerateRequest(BaseModel):
    conversation_id: str = Field(..., description="이 대화를 식별하는 BE 쪽 ID")
    schedule_id: str = Field(None, description="이 계획이 귀속될 BE 쪽 schedule ID (확정 시 전송에 사용)")
    goal_summary: str
    category: str = Field(..., min_length=1)
    template_answers: dict = Field(
        ...,
        description="template_generation이 수집한 사용자 답변. "
        "start_date/end_date(YYYY-MM-DD)가 반드시 포함되어야 한다",
    )
    busy_dates: List[BusyDate] = Field(
        default_factory=list,
        description="BE가 사용자 캘린더를 스캔해 전처리한 기존 일정(참고용)",
    )
    long_term_context: Optional[LongTermContext] = Field(
        None,
        description="BE가 정제해 전달하는 이 사용자의 과거 목표/선호 이력. 첫 목표라면 생략 가능",
    )


class PlanReviseRequest(BaseModel):
    conversation_id: str
    schedule_id: str = Field(None, description="이 계획이 귀속될 BE 쪽 schedule ID (확정 시 전송에 사용)")
    goal_summary: str
    category: str = Field(..., min_length=1)
    template_answers: dict
    current_plan: SchedulePlan = Field(..., description="직전 턴에서 사용자에게 보여준 계획")
    user_message: str = Field(..., description="계획에 대한 사용자의 수정 요청/피드백 자유 텍스트")
    feedback_history: List[str] = Field(
        default_factory=list,
        description="직전 턴들의 사용자 피드백 원문 목록 (이번 턴의 user_message는 미포함, 오래된 순)",
    )
    busy_dates: List[BusyDate] = Field(default_factory=list)


class PlanTurnResponse(BaseModel):
    """generate/revise 공통 응답 — 챗봇 말풍선에 보여줄 메시지와 갱신된 계획을 함께 반환한다."""

    assistant_message: str = Field(..., description="사용자에게 그대로 보여줄 챗봇 응답 텍스트")
    category: str = Field(..., description="이 계획이 속한 카테고리. 요청받은 값을 그대로 반환한다 (AI가 새로 판단하지 않음).")
    plan: SchedulePlan
    ready_to_confirm: bool = Field(
        ..., description="AI 판단으로 이 계획이 바로 확정해도 될 만큼 안정적인지 여부(참고용 신호)"
    )
    confirmed: bool = Field(False, description="이번 턴에 사용자가 확정 의사를 밝혔는지 여부")
    submitted: Optional[bool] = Field(
        None, description="[C안 이후 미사용] AI가 더 이상 BE로 저장을 시도하지 않아 항상 None"
    )
    feedback_history: List[str] = Field(
        default_factory=list,
        description="이번 턴까지 누적된 사용자 피드백 원문 목록",
    )


class PlanConfirmRequest(BaseModel):
    conversation_id: str
    schedule_id: str = Field(..., description="이 계획이 귀속될 BE 쪽 schedule ID")
    plan: SchedulePlan = Field(..., description="사용자가 대화로 최종 확정한 계획")


class PlanConfirmResponse(BaseModel):
    submitted: bool
    schedule_id: str


# ── strict structured output용 raw JSON Schema ──────────────────────
# Groq/Cerebras/Gemini의 strict 모드는 "모든 프로퍼티가 required + 선택 필드는 nullable
# union"이어야 하므로 Pydantic의 model_json_schema() 기본 출력을 그대로 못 쓰고 직접 정의한다.

_DAILY_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "scheduled_date": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "estimated_min": {"type": "integer", "minimum": 1},
    },
    "required": ["scheduled_date", "title", "description", "estimated_min"],
    "additionalProperties": False,
}

PLAN_TURN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "assistant_message": {"type": "string"},
        "summary": {"type": "string"},
        "daily_tasks": {"type": "array", "items": _DAILY_TASK_SCHEMA},
        "ready_to_confirm": {"type": "boolean"},
        "user_confirmed": {"type": "boolean"},
    },
    "required": ["assistant_message", "summary", "daily_tasks", "ready_to_confirm", "user_confirmed"],
    "additionalProperties": False,
}
