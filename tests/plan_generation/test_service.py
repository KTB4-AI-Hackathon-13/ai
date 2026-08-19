import httpx
import pytest

from app.plan_generation import service
from app.plan_generation.schemas import (
    PlanConfirmRequest,
    PlanGenerateRequest,
    PlanReviseRequest,
    SchedulePlan,
)


def _template_answers(start_date="2026-08-20", end_date="2026-08-29"):
    return {"start_date": start_date, "end_date": end_date, "experience": "beginner"}


class TestDaysBetweenInclusive:
    def test_counts_both_endpoints(self):
        assert service._days_between_inclusive("2026-08-20", "2026-08-29") == 10

    def test_same_day_is_one_day(self):
        assert service._days_between_inclusive("2026-08-20", "2026-08-20") == 1

    def test_end_before_start_raises(self):
        with pytest.raises(service.InvalidDateRange):
            service._days_between_inclusive("2026-08-29", "2026-08-20")

    def test_bad_format_raises(self):
        with pytest.raises(service.InvalidDateRange):
            service._days_between_inclusive("2026/08/20", "2026-08-29")


class TestRequireDateRange:
    def test_missing_start_date_raises(self):
        with pytest.raises(service.InvalidDateRange):
            service._require_date_range({"end_date": "2026-08-29"})

    def test_valid_range_does_not_raise(self):
        service._require_date_range(_template_answers())


class TestGeneratePlan:
    def test_rejects_missing_date_range(self):
        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal="근육을 만들고 싶어",
            category="운동",
            template_answers={"experience": "beginner"},
        )
        with pytest.raises(service.InvalidDateRange):
            service.generate_plan(req)

    def test_builds_plan_from_llm_response(self, monkeypatch):
        fake_response = {
            "assistant_message": "10일짜리 운동 계획을 만들었어요.",
            "summary": "가벼운 근력 운동 10일 플랜",
            "daily_tasks": [
                {
                    "scheduled_date": "2026-08-20",
                    "title": "하체 운동",
                    "description": "스쿼트 3세트 x 12회",
                    "estimated_min": 30,
                }
            ],
            "ready_to_confirm": True,
            "user_confirmed": False,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        notified = []
        monkeypatch.setattr(
            service.be_client,
            "notify_conversation",
            lambda conversation_id, role, content: notified.append((conversation_id, role, content)),
        )

        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
        )
        result = service.generate_plan(req)

        assert result.assistant_message == fake_response["assistant_message"]
        assert result.plan.summary == fake_response["summary"]
        assert len(result.plan.daily_tasks) == 1
        assert result.ready_to_confirm is True
        assert [role for _, role, _ in notified] == ["user", "assistant"]


class TestRevisePlan:
    def test_builds_revised_plan_from_llm_response(self, monkeypatch):
        fake_response = {
            "assistant_message": "주말은 빼고 다시 짰어요.",
            "summary": "주중 위주 근력 운동 플랜",
            "daily_tasks": [],
            "ready_to_confirm": False,
            "user_confirmed": False,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            current_plan=SchedulePlan(summary="기존 플랜", daily_tasks=[]),
            user_message="주말엔 시간이 없어요",
        )
        result = service.revise_plan(req)

        assert result.ready_to_confirm is False
        assert result.confirmed is False
        assert result.submitted is None
        assert result.plan.summary == fake_response["summary"]

    def test_user_confirmed_submits_current_plan_to_be(self, monkeypatch):
        fake_response = {
            "assistant_message": "이건 무시돼야 함",
            "summary": "이것도 무시돼야 함",
            "daily_tasks": [],
            "ready_to_confirm": True,
            "user_confirmed": True,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)
        submitted = []
        monkeypatch.setattr(
            service.be_client,
            "submit_final_plan",
            lambda schedule_id, plan: submitted.append((schedule_id, plan)),
        )

        current_plan = SchedulePlan(summary="기존 플랜", daily_tasks=[])
        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            current_plan=current_plan,
            user_message="네 이걸로 확정할게요",
        )
        result = service.revise_plan(req)

        assert result.confirmed is True
        assert result.submitted is True
        assert result.plan == current_plan
        assert submitted == [("sched-1", current_plan.model_dump())]

    def test_user_confirmed_but_be_submission_fails_does_not_raise(self, monkeypatch):
        fake_response = {
            "assistant_message": "이건 무시돼야 함",
            "summary": "이것도 무시돼야 함",
            "daily_tasks": [],
            "ready_to_confirm": True,
            "user_confirmed": True,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        def _raise(*args, **kwargs):
            raise httpx.HTTPError("boom")

        monkeypatch.setattr(service.be_client, "submit_final_plan", _raise)

        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            current_plan=SchedulePlan(summary="기존 플랜", daily_tasks=[]),
            user_message="네 이걸로 확정할게요",
        )
        result = service.revise_plan(req)

        assert result.confirmed is True
        assert result.submitted is False


class TestConfirmPlan:
    def test_submits_plan_and_echoes_schedule_id(self, monkeypatch):
        submitted = []
        monkeypatch.setattr(
            service.be_client,
            "submit_final_plan",
            lambda schedule_id, plan: submitted.append((schedule_id, plan)),
        )

        req = PlanConfirmRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            plan=SchedulePlan(summary="최종 플랜", daily_tasks=[]),
        )
        result = service.confirm_plan(req)

        assert result.submitted is True
        assert result.schedule_id == "sched-1"
        assert submitted == [("sched-1", {"summary": "최종 플랜", "daily_tasks": []})]
