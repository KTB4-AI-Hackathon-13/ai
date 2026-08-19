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

Category = Literal["운동", "공부", "습관", "기타"]


class BusyDate(BaseModel):
    """BE가 사용자 캘린더를 스캔해 전처리한 기존 일정. 참고용 힌트일 뿐, 강제 규칙은 아니다."""

    date: str = Field(..., description="YYYY-MM-DD")
    event_count: int = Field(..., description="그 날짜에 이미 잡힌 일정 개수")
    all_day: bool = Field(False, description="하루 종일 막혀 있는 일정(출장/휴가 등) 여부")


class DailyTask(BaseModel):
    scheduled_date: str = Field(..., description="YYYY-MM-DD. 이 작업을 배치한 실제 날짜")
    title: str
    description: str
    estimated_min: int


class SchedulePlan(BaseModel):
    summary: str
    daily_tasks: List[DailyTask]


class PlanGenerateRequest(BaseModel):
    conversation_id: str = Field(..., description="이 대화를 식별하는 BE 쪽 ID")
    goal: str
    category: Category
    template_answers: dict = Field(
        ...,
        description="template_generation이 수집한 사용자 답변. "
        "start_date/end_date(YYYY-MM-DD)가 반드시 포함되어야 한다",
    )
    busy_dates: List[BusyDate] = Field(
        default_factory=list,
        description="BE가 사용자 캘린더를 스캔해 전처리한 기존 일정(참고용)",
    )


class PlanReviseRequest(BaseModel):
    conversation_id: str
    goal: str
    category: Category
    template_answers: dict
    current_plan: SchedulePlan = Field(..., description="직전 턴에서 사용자에게 보여준 계획")
    user_message: str = Field(..., description="계획에 대한 사용자의 수정 요청/피드백 자유 텍스트")
    busy_dates: List[BusyDate] = Field(default_factory=list)


class PlanTurnResponse(BaseModel):
    """generate/revise 공통 응답 — 챗봇 말풍선에 보여줄 메시지와 갱신된 계획을 함께 반환한다."""

    assistant_message: str = Field(..., description="사용자에게 그대로 보여줄 챗봇 응답 텍스트")
    plan: SchedulePlan
    ready_to_confirm: bool = Field(
        ..., description="AI 판단으로 이 계획이 바로 확정해도 될 만큼 안정적인지 여부(참고용 신호)"
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
        "estimated_min": {"type": "integer"},
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
    },
    "required": ["assistant_message", "summary", "daily_tasks", "ready_to_confirm"],
    "additionalProperties": False,
}
