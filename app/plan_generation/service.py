"""jena 담당 — plan_generation 비즈니스 로직. router.py는 이 모듈의 함수만 호출한다."""

from datetime import date

from app.plan_generation import be_client
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


class InvalidDateRange(Exception):
    """template_answers의 start_date/end_date가 없거나 형식/순서가 잘못됐을 때."""


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


def _turn_result_to_response(data: dict) -> PlanTurnResponse:
    plan = SchedulePlan(summary=data["summary"], daily_tasks=data["daily_tasks"])
    return PlanTurnResponse(
        assistant_message=data["assistant_message"],
        plan=plan,
        ready_to_confirm=data["ready_to_confirm"],
    )


def generate_plan(req: PlanGenerateRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    data = generate_structured(
        system_prompt=PLAN_GENERATE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="user", content=req.goal)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result


def revise_plan(req: PlanReviseRequest) -> PlanTurnResponse:
    _require_date_range(req.template_answers)

    data = generate_structured(
        system_prompt=PLAN_REVISE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id"}),
        json_schema=PLAN_TURN_JSON_SCHEMA,
        schema_name="plan_turn",
    )

    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="user", content=req.user_message)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result


def confirm_plan(req: PlanConfirmRequest) -> PlanConfirmResponse:
    be_client.submit_final_plan(req.schedule_id, req.plan.model_dump())
    return PlanConfirmResponse(submitted=True, schedule_id=req.schedule_id)
