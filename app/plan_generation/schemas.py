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
    estimated_min: int


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
    schedule_id: str = Field(..., description="이 계획이 귀속될 BE 쪽 schedule ID (확정 시 전송에 사용)")
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
    schedule_id: str = Field(..., description="이 계획이 귀속될 BE 쪽 schedule ID (확정 시 전송에 사용)")
    goal_summary: str
    category: str = Field(..., min_length=1)
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
    confirmed: bool = Field(False, description="이번 턴에 사용자가 확정 의사를 밝혔는지 여부")
    submitted: Optional[bool] = Field(
        None, description="confirmed=True일 때만 의미 있음 — BE로 최종 계획 전송이 성공했는지 여부"
    )


class PlanConfirmRequest(BaseModel):
    conversation_id: str
    schedule_id: str = Field(..., description="이 계획이 귀속될 BE 쪽 schedule ID")
    plan: SchedulePlan = Field(..., description="사용자가 대화로 최종 확정한 계획")


class PlanConfirmResponse(BaseModel):
    submitted: bool
    schedule_id: str


class RescheduleTask(BaseModel):
    """FE/BE가 넘겨주는, 이 스케줄(목표)에 이미 있는 태스크 원본 한 건 — 완료/미완료 전체.
    BE의 schedule_items.id는 숫자라 그대로 int로 받는다."""

    id: int = Field(..., description="BE 쪽 태스크 id (schedule_items.id)")
    scheduled_date: str = Field(..., description="YYYY-MM-DD")
    title: str
    description: str
    estimated_min: int
    completed: bool = Field(
        ..., description="완료 여부(BE의 completedAt != null과 동일). true면 AI는 이 태스크를 "
        "절대 수정 대상으로 삼지 않는다 — 문맥 파악용으로만 참고한다."
    )


class RescheduledTaskUpdate(BaseModel):
    """이번 요청으로 실제로 내용이 바뀐 태스크 한 건. 응답엔 바뀐 것만 담긴다."""

    id: int = Field(..., description="RescheduleTask 중 어떤 태스크를 수정한 것인지(기존 id 그대로)")
    scheduled_date: str = Field(..., description="YYYY-MM-DD. 새로 배치된 날짜")
    title: str
    description: str
    estimated_min: int


class PlanRescheduleRequest(BaseModel):
    """이미 확정되어 캘린더에 올라간 계획을 사용자가 다시 수정하고 싶을 때 쓰는 요청.
    /plan/revise처럼 대화로 되묻진 않지만, 이 호출 자체는 BE에 아무것도 반영하지 않는다 —
    변경 제안만 만들어서 보여주고, 사용자가 그걸 보고 승인하면 /plan/reschedule/confirm으로
    그 결과를 그대로 다시 보내야 실제로 캘린더에 반영된다. 전체 계획을 통째로 교체하지 않고,
    완료되지 않은(completed=false) 태스크 중 실제로 바뀐 것만 찾아낸다."""

    conversation_id: str = Field(..., description="이 대화를 식별하는 BE 쪽 ID")
    schedule_id: str = Field(..., description="수정할 대상 계획이 귀속된 BE 쪽 schedule ID")
    goal_summary: str
    category: str = Field(..., min_length=1)
    template_answers: dict
    tasks: List[RescheduleTask] = Field(
        ...,
        description="이 스케줄(목표 하나)에 속한 전체 태스크(완료 + 미완료). 완료된 태스크도 "
        "문맥 파악을 위해 함께 보내되, AI는 completed=false인 것만 수정 대상으로 삼는다.",
    )
    user_message: str = Field(..., description="캘린더에 반영할 수정 요청 자유 텍스트")


class PlanRescheduleResponse(BaseModel):
    assistant_message: str = Field(..., description="사용자에게 그대로 보여줄 챗봇 응답 텍스트")
    updated_tasks: List[RescheduledTaskUpdate] = Field(
        default_factory=list,
        description="이번 요청으로 바뀌는 태스크 제안(diff). 아직 BE엔 반영 안 됨 — 사용자가 "
        "승인하면 이 값을 그대로 /plan/reschedule/confirm에 다시 실어 보내야 한다.",
    )
    ready_to_confirm: bool = Field(
        ..., description="이 제안을 그대로 확정해도 되는지 여부. 30일 상한 초과 등으로 반영이 "
        "불가능하면 false이고, 이때 updated_tasks는 빈 배열이다."
    )


class PlanRescheduleConfirmRequest(BaseModel):
    """/plan/reschedule 응답에서 받은 updated_tasks를 사용자가 승인했을 때, 그대로 다시
    실어 보내 실제로 BE에 반영시키는 요청. 이 서비스는 상태가 없어서 직전 제안을 기억하지
    않는다 — 승인된 내용을 호출자가 그대로 들고 있다가 다시 보내야 한다."""

    schedule_id: str = Field(..., description="수정할 대상 계획이 귀속된 BE 쪽 schedule ID")
    updated_tasks: List[RescheduledTaskUpdate] = Field(
        ..., description="/plan/reschedule 응답의 updated_tasks를 그대로 넣는다."
    )


class PlanRescheduleConfirmResponse(BaseModel):
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
        "user_confirmed": {"type": "boolean"},
    },
    "required": ["assistant_message", "summary", "daily_tasks", "ready_to_confirm", "user_confirmed"],
    "additionalProperties": False,
}

_RESCHEDULED_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "scheduled_date": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "estimated_min": {"type": "integer"},
    },
    "required": ["id", "scheduled_date", "title", "description", "estimated_min"],
    "additionalProperties": False,
}

PLAN_RESCHEDULE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "assistant_message": {"type": "string"},
        "updated_tasks": {"type": "array", "items": _RESCHEDULED_TASK_SCHEMA},
    },
    "required": ["assistant_message", "updated_tasks"],
    "additionalProperties": False,
}
