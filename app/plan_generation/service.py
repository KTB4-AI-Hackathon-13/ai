"""jena 담당 — plan_generation 비즈니스 로직. router.py는 이 모듈의 함수만 호출한다."""

import logging
from datetime import date

import httpx

from app.plan_generation import be_client
from app.plan_generation.prompts import PLAN_GENERATE_SYSTEM, PLAN_RESCHEDULE_SYSTEM, PLAN_REVISE_SYSTEM
from app.plan_generation.providers import generate_structured
from app.plan_generation.schemas import (
    PLAN_RESCHEDULE_JSON_SCHEMA,
    PLAN_TURN_JSON_SCHEMA,
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanGenerateRequest,
    PlanRescheduleConfirmRequest,
    PlanRescheduleConfirmResponse,
    PlanRescheduleRequest,
    PlanRescheduleResponse,
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


def _turn_result_to_response(data: dict) -> PlanTurnResponse:
    plan = SchedulePlan(summary=data["summary"], daily_tasks=data["daily_tasks"])
    return PlanTurnResponse(
        assistant_message=data["assistant_message"],
        plan=plan,
        ready_to_confirm=data["ready_to_confirm"],
    )


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
        submitted = _try_submit_final_plan(req.schedule_id, req.current_plan)
        assistant_message = (
            "네, 이 계획으로 확정할게요!"
            if submitted
            else "계획 확정 요청을 받았는데 저장 중 문제가 생겼어요. 잠시 후 다시 시도해주세요."
        )
        be_client.notify_conversation(req.conversation_id, role="assistant", content=assistant_message)
        return PlanTurnResponse(
            assistant_message=assistant_message,
            plan=req.current_plan,
            ready_to_confirm=True,
            confirmed=True,
            submitted=submitted,
        )

    result = _turn_result_to_response(data)
    be_client.notify_conversation(req.conversation_id, role="assistant", content=result.assistant_message)
    return result


def _try_submit_final_plan(schedule_id: str, plan: SchedulePlan) -> bool:
    try:
        be_client.submit_final_plan(schedule_id, plan.model_dump())
        return True
    except httpx.HTTPError as exc:
        logger.warning("확정 계획 BE 전송 실패(대화는 계속 진행): %s", exc)
        return False


def confirm_plan(req: PlanConfirmRequest) -> PlanConfirmResponse:
    be_client.submit_final_plan(req.schedule_id, req.plan.model_dump())
    return PlanConfirmResponse(submitted=True, schedule_id=req.schedule_id)


def reschedule_plan(req: PlanRescheduleRequest) -> PlanRescheduleResponse:
    """이미 캘린더에 있는 태스크 중 completed=false인 것만 골라 수정 제안을 만든다.
    이 함수는 BE에 아무것도 전송하지 않는다 — 사용자가 승인하면 별도로
    confirm_reschedule을 호출해야 실제로 반영된다."""
    _require_date_range(req.template_answers)

    data = generate_structured(
        system_prompt=PLAN_RESCHEDULE_SYSTEM,
        user_content=req.model_dump_json(exclude={"conversation_id", "schedule_id"}),
        json_schema=PLAN_RESCHEDULE_JSON_SCHEMA,
        schema_name="plan_reschedule",
    )

    be_client.notify_conversation(req.conversation_id, role="user", content=req.user_message)

    updated_by_id = {task["id"]: task for task in data["updated_tasks"]}
    effective_dates = [
        {"scheduled_date": updated_by_id[task.id]["scheduled_date"] if task.id in updated_by_id else task.scheduled_date}
        for task in req.tasks
        if not task.completed
    ]
    revised_days = _revised_duration_days(req.template_answers["start_date"], effective_dates)
    if revised_days is not None and revised_days > MAX_PLAN_DURATION_DAYS:
        message = _plan_duration_exceeded_after_revise_message(revised_days)
        be_client.notify_conversation(req.conversation_id, role="assistant", content=message)
        return PlanRescheduleResponse(assistant_message=message, updated_tasks=[], ready_to_confirm=False)

    be_client.notify_conversation(req.conversation_id, role="assistant", content=data["assistant_message"])
    return PlanRescheduleResponse(
        assistant_message=data["assistant_message"],
        updated_tasks=data["updated_tasks"],
        ready_to_confirm=True,
    )


def confirm_reschedule(req: PlanRescheduleConfirmRequest) -> PlanRescheduleConfirmResponse:
    """/plan/reschedule이 제안한 updated_tasks를 사용자가 승인했을 때, 그 내용을 그대로
    BE에 반영한다."""
    tasks = [task.model_dump() for task in req.updated_tasks]
    be_client.update_scheduled_tasks(req.schedule_id, tasks)
    return PlanRescheduleConfirmResponse(submitted=True, schedule_id=req.schedule_id)
