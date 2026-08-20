"""jena 담당 — plan_generation 비즈니스 로직. router.py는 이 모듈의 함수만 호출한다.

[C안 반영] AI는 백엔드로 어떤 아웃바운드 호출도 하지 않는다. 대화 로그 저장과 계획
확정 저장 모두 백엔드가 이 응답을 받은 뒤 자기 쪽에서 직접 처리한다.

[category 추가] 응답(PlanTurnResponse)에 category를 포함시켰다. AI가 새로 판단하는
게 아니라, 요청으로 받은 category 값을 그대로 돌려주는 것뿐이라 LLM 호출/프롬프트는
안 건드려도 된다.
"""

import logging
from datetime import date

from app.plan_generation.prompts import PLAN_GENERATE_SYSTEM, PLAN_REVISE_SYSTEM
from app.plan_generation.providers import generate_structured
from app.plan_generation.schemas import (
    PLAN_TURN_JSON_SCHEMA,
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanGenerateRequest,
    PlanReviseRequest,
    PlanTurnResponse,
    SchedulePlan,
)

logger = logging.getLogger(__name__)


class InvalidDateRange(Exception):
    """template_answers의 start_date/end_date가 없거나 형식/순서가 잘못됐을 때."""


MAX_PLAN_DURATION_DAYS = 30


def _days_between_inclusive(start_str: str, end_str: str) -> int:
    try:
        start = date.fromisoformat(str(start_str))
        end = date.fromisoformat(str(end_str))
    except (TypeError, ValueError) as exc:
        raise InvalidDateRange("start_date/end_date는 YYYY-MM-DD 형식이어야 합니다.") from exc

    days = (end - start).days + 1
    if days < 1:
        raise InvalidDateRange("end_date는 start_date와 같거나 이후여야 합니다.")
    return days


def _require_date_range(template_answers: dict) -> None:
    """LLM 호출 전에 start_date/end_date 존재 및 형식만 미리 검증해 빠르게 실패시킨다."""
    try:
        start_date = template_answers["start_date"]
        end_date = template_answers["end_date"]
    except KeyError as exc:
        raise InvalidDateRange("template_answers에 start_date/end_date가 필요합니다.") from exc
    _days_between_inclusive(start_date, end_date)


def _plan_duration_exceeded_message(days: int) -> str:
    return (
        f"목표 기간은 최대 {MAX_PLAN_DURATION_DAYS}일까지 설정할 수 있어요. "
        f"요청하신 기간은 {days}일이에요. 시작일과 종료일을 다시 알려주시겠어요?"
    )


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


def _turn_result_to_response(data: dict, category: str, feedback_history: list[str]) -> PlanTurnResponse:
    plan = SchedulePlan(summary=data["summary"], daily_tasks=data["daily_tasks"])
    return PlanTurnResponse(
        assistant_message=data["assistant_message"],
        category=category,
        plan=plan,
        ready_to_confirm=data["ready_to_confirm"],
        feedback_history=feedback_history,
    )


def generate_plan(req: PlanGenerateRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    days = _days_between_inclusive(
        req.template_answers["start_date"], req.template_answers["end_date"]
    )
    if days > MAX_PLAN_DURATION_DAYS:
        message = _plan_duration_exceeded_message(days)
        return PlanTurnResponse(
            assistant_message=message,
            category=req.category,
            plan=SchedulePlan(summary="", daily_tasks=[]),
            ready_to_confirm=False,
            feedback_history=[],
        )

    data = generate_structured(
        system_prompt=PLAN_GENERATE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    return _turn_result_to_response(data, req.category, feedback_history=[])


def revise_plan(req: PlanReviseRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    feedback_history = req.feedback_history + [req.user_message]

    data = generate_structured(
        system_prompt=PLAN_REVISE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    revised_days = _revised_duration_days(req.template_answers["start_date"], data["daily_tasks"])
    if revised_days is not None and revised_days > MAX_PLAN_DURATION_DAYS:
        message = _plan_duration_exceeded_after_revise_message(revised_days)
        return PlanTurnResponse(
            assistant_message=message,
            category=req.category,
            plan=req.current_plan,
            ready_to_confirm=False,
            confirmed=False,
            feedback_history=feedback_history,
        )

    if data["user_confirmed"]:
        return PlanTurnResponse(
            assistant_message="네, 이 계획으로 확정할게요!",
            category=req.category,
            plan=req.current_plan,
            ready_to_confirm=True,
            confirmed=True,
            feedback_history=feedback_history,
        )

    return _turn_result_to_response(data, req.category, feedback_history)


def confirm_plan(req: PlanConfirmRequest) -> PlanConfirmResponse:
    """[사실상 불필요] BE는 이미 /plan/revise 응답에서 최종 plan을 갖고 있으므로
    이 엔드포인트를 다시 호출할 이유가 없다. 팀 논의 후 삭제 여부 결정.
    """
    return PlanConfirmResponse(submitted=True, schedule_id=req.schedule_id)