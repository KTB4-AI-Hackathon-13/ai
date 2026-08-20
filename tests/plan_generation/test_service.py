import httpx
import pytest

from app.plan_generation import service
from app.plan_generation.schemas import (
    LongTermContext,
    PastGoalSummary,
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
        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
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
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
        )
        result = service.generate_plan(req)

        assert result.assistant_message == fake_response["assistant_message"]
        assert result.plan.summary == fake_response["summary"]
        assert result.feedback_history == []
        assert len(result.plan.daily_tasks) == 1
        assert result.ready_to_confirm is True
        assert [role for _, role, _ in notified] == ["user", "assistant"]

    def test_long_term_context_defaults_to_none(self, monkeypatch):
        fake_response = {
            "assistant_message": "10일짜리 운동 계획을 만들었어요.",
            "summary": "가벼운 근력 운동 10일 플랜",
            "daily_tasks": [],
            "ready_to_confirm": True,
            "user_confirmed": False,
        }
        captured = {}
        monkeypatch.setattr(
            service,
            "generate_structured",
            lambda **kwargs: captured.update(kwargs) or fake_response,
        )
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
        )
        service.generate_plan(req)

        assert '"long_term_context":null' in captured["user_content"].replace(" ", "")

    def test_long_term_context_is_passed_to_llm(self, monkeypatch):
        fake_response = {
            "assistant_message": "10일짜리 운동 계획을 만들었어요.",
            "summary": "가벼운 근력 운동 10일 플랜",
            "daily_tasks": [],
            "ready_to_confirm": True,
            "user_confirmed": False,
        }
        captured = {}
        monkeypatch.setattr(
            service,
            "generate_structured",
            lambda **kwargs: captured.update(kwargs) or fake_response,
        )
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanGenerateRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            long_term_context=LongTermContext(
                past_goals=[
                    PastGoalSummary(
                        category="운동",
                        goal="10km 마라톤 완주",
                        period_days=30,
                        completion_status="abandoned",
                    )
                ],
                preferences=["아침엔 시간 없음"],
            ),
        )
        service.generate_plan(req)

        assert "마라톤" in captured["user_content"]
        assert "아침엔 시간 없음" in captured["user_content"]

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
            goal_summary="근육을 만들고 싶어",
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
        assert result.feedback_history == ["주말엔 시간이 없어요"]

    def test_accumulates_feedback_history_across_turns(self, monkeypatch):
        fake_response = {
            "assistant_message": "강도를 낮춰서 다시 짰어요.",
            "summary": "저강도 플랜",
            "daily_tasks": [],
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
            feedback_history=["주말엔 시간이 없어요"],
            user_message="강도도 좀 낮춰주세요",
        )
        result = service.revise_plan(req)

        assert result.feedback_history == ["주말엔 시간이 없어요", "강도도 좀 낮춰주세요"]

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
        created_calls, updated_calls = [], []
        monkeypatch.setattr(
            service.be_client,
            "create_plan_tasks",
            lambda schedule_id, summary, tasks: created_calls.append((schedule_id, summary, tasks)),
        )
        monkeypatch.setattr(
            service.be_client,
            "update_plan_tasks",
            lambda schedule_id, summary, tasks: updated_calls.append((schedule_id, summary, tasks)),
        )

        current_plan = SchedulePlan(summary="기존 플랜", daily_tasks=[])
        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(start_date="2026-08-20", end_date="2026-08-29"),
            current_plan=current_plan,
            feedback_history=["주말엔 시간이 없어요"],
            user_message="기간 한 달 더 늘려줘",
        )
        result = service.revise_plan(req)

        assert result.confirmed is False
        assert result.ready_to_confirm is False
        assert result.feedback_history == ["주말엔 시간이 없어요", "기간 한 달 더 늘려줘"]
        assert result.plan == current_plan
        assert "30" in result.assistant_message
        assert created_calls == []
        assert updated_calls == []

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

    def test_partial_current_plan_covering_only_remaining_days(self, monkeypatch):
        """current_plan이 목표 전체가 아니라 아직 완료되지 않은 남은 구간(11~30일차)만
        담고 있어도 기존 로직이 에러 없이 그대로 동작하는지 확인한다."""
        fake_response = {
            "assistant_message": "11~20일차를 더 가볍게 다시 짰어요.",
            "summary": "남은 구간 재조정 플랜",
            "daily_tasks": [
                {
                    "scheduled_date": "2026-08-30",
                    "title": "가벼운 유산소",
                    "description": "조깅 20분",
                    "estimated_min": 20,
                }
            ],
            "ready_to_confirm": True,
            "user_confirmed": False,
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        remaining_tasks = [
            {
                "scheduled_date": "2026-08-30",
                "title": "하체 운동",
                "description": "스쿼트 3세트 x 12회",
                "estimated_min": 30,
            }
        ]
        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(start_date="2026-08-01", end_date="2026-08-30"),
            current_plan=SchedulePlan(summary="남은 구간 플랜", daily_tasks=remaining_tasks),
            user_message="11일부터 20일까지만 좀 가볍게 다시 짜줘",
        )
        result = service.revise_plan(req)

        assert result.plan.summary == fake_response["summary"]
        assert result.confirmed is False

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
        created_calls, updated_calls = [], []
        monkeypatch.setattr(
            service.be_client,
            "create_plan_tasks",
            lambda schedule_id, summary, tasks: created_calls.append((schedule_id, summary, tasks)),
        )
        monkeypatch.setattr(
            service.be_client,
            "update_plan_tasks",
            lambda schedule_id, summary, tasks: updated_calls.append((schedule_id, summary, tasks)),
        )

        current_plan = SchedulePlan(
            summary="기존 플랜",
            daily_tasks=[
                {
                    "id": "task-1",
                    "scheduled_date": "2026-08-20",
                    "title": "하체 운동",
                    "description": "스쿼트 3세트 x 12회",
                    "estimated_min": 30,
                },
                {
                    "scheduled_date": "2026-08-21",
                    "title": "상체 운동",
                    "description": "벤치프레스 3세트 x 12회",
                    "estimated_min": 30,
                },
            ],
        )
        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            current_plan=current_plan,
            user_message="네 이걸로 확정할게요",
        )
        result = service.revise_plan(req)

        assert result.confirmed is True
        assert result.submitted is True
        assert result.plan == current_plan
        assert created_calls == [("sched-1", "기존 플랜", [current_plan.daily_tasks[1].model_dump()])]
        assert updated_calls == [("sched-1", "기존 플랜", [current_plan.daily_tasks[0].model_dump()])]

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

        monkeypatch.setattr(service.be_client, "create_plan_tasks", _raise)
        monkeypatch.setattr(service.be_client, "update_plan_tasks", lambda *a, **k: None)

        req = PlanReviseRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="근육을 만들고 싶어",
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
        created_calls, updated_calls = [], []
        monkeypatch.setattr(
            service.be_client,
            "create_plan_tasks",
            lambda schedule_id, summary, tasks: created_calls.append((schedule_id, summary, tasks)),
        )
        monkeypatch.setattr(
            service.be_client,
            "update_plan_tasks",
            lambda schedule_id, summary, tasks: updated_calls.append((schedule_id, summary, tasks)),
        )

        req = PlanConfirmRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            plan=SchedulePlan(
                summary="최종 플랜",
                daily_tasks=[
                    {
                        "id": "task-9",
                        "scheduled_date": "2026-08-20",
                        "title": "하체 운동",
                        "description": "스쿼트 3세트 x 12회",
                        "estimated_min": 30,
                    },
                    {
                        "scheduled_date": "2026-08-21",
                        "title": "상체 운동",
                        "description": "벤치프레스 3세트 x 12회",
                        "estimated_min": 30,
                    },
                ],
            ),
        )
        result = service.confirm_plan(req)

        assert result.submitted is True
        assert result.schedule_id == "sched-1"
        assert created_calls == [
            (
                "sched-1",
                "최종 플랜",
                [
                    {
                        "id": None,
                        "scheduled_date": "2026-08-21",
                        "title": "상체 운동",
                        "description": "벤치프레스 3세트 x 12회",
                        "estimated_min": 30,
                    }
                ],
            )
        ]
        assert updated_calls == [
            (
                "sched-1",
                "최종 플랜",
                [
                    {
                        "id": "task-9",
                        "scheduled_date": "2026-08-20",
                        "title": "하체 운동",
                        "description": "스쿼트 3세트 x 12회",
                        "estimated_min": 30,
                    }
                ],
            )
        ]
