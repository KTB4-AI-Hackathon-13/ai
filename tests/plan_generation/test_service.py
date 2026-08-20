import httpx
import pytest

from app.plan_generation import service
from app.plan_generation.schemas import (
    LongTermContext,
    PastGoalSummary,
    PlanConfirmRequest,
    PlanGenerateRequest,
    PlanRescheduleConfirmRequest,
    PlanRescheduleRequest,
    PlanReviseRequest,
    RescheduledTaskUpdate,
    RescheduleTask,
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
        submit_calls = []
        monkeypatch.setattr(
            service.be_client,
            "submit_final_plan",
            lambda schedule_id, plan: submit_calls.append((schedule_id, plan)),
        )

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
        assert submit_calls == []

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
            goal_summary="근육을 만들고 싶어",
            category="운동",
            template_answers=_template_answers(),
            current_plan=SchedulePlan(summary="기존 플랜", daily_tasks=[]),
            user_message="네 이걸로 확정할게요",
        )
        result = service.revise_plan(req)

        assert result.confirmed is True
        assert result.submitted is False


class TestReschedulePlan:
    def _tasks(self):
        return [
            RescheduleTask(
                id=1,
                scheduled_date="2026-08-19",
                title="핵심 개념 학습 완료",
                description="핵심 개념 정리",
                estimated_min=45,
                completed=True,
            ),
            RescheduleTask(
                id=2,
                scheduled_date="2026-08-23",
                title="미니 프로젝트 구현",
                description="미니 프로젝트 구현",
                estimated_min=90,
                completed=False,
            ),
            RescheduleTask(
                id=3,
                scheduled_date="2026-08-23",
                title="달력 컴포넌트 연결",
                description="달력 컴포넌트 연결",
                estimated_min=50,
                completed=False,
            ),
        ]

    def test_proposes_only_changed_tasks_without_calling_be(self, monkeypatch):
        fake_response = {
            "assistant_message": "달력 컴포넌트 연결을 8월 24일로 옮길게요.",
            "updated_tasks": [
                {
                    "id": 3,
                    "scheduled_date": "2026-08-24",
                    "title": "달력 컴포넌트 연결",
                    "description": "달력 컴포넌트 연결",
                    "estimated_min": 50,
                }
            ],
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)
        submit_calls = []
        monkeypatch.setattr(
            service.be_client,
            "update_scheduled_tasks",
            lambda schedule_id, tasks: submit_calls.append((schedule_id, tasks)),
        )

        req = PlanRescheduleRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="AI 확정 학습 계획",
            category="학습",
            template_answers=_template_answers(start_date="2026-08-15", end_date="2026-08-31"),
            tasks=self._tasks(),
            user_message="달력 컴포넌트 연결을 8월 24일로 옮겨줘",
        )
        result = service.reschedule_plan(req)

        assert result.ready_to_confirm is True
        assert result.assistant_message == fake_response["assistant_message"]
        assert len(result.updated_tasks) == 1
        assert result.updated_tasks[0].id == 3
        assert result.updated_tasks[0].scheduled_date == "2026-08-24"
        assert submit_calls == []  # 제안 단계에서는 BE 호출이 없어야 함

    def test_no_changes_returns_empty_updated_tasks(self, monkeypatch):
        fake_response = {"assistant_message": "요청하신 대로 바뀔 게 없었어요.", "updated_tasks": []}
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanRescheduleRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="AI 확정 학습 계획",
            category="학습",
            template_answers=_template_answers(start_date="2026-08-15", end_date="2026-08-31"),
            tasks=self._tasks(),
            user_message="이미 완료된 태스크는 그대로 둬",
        )
        result = service.reschedule_plan(req)

        assert result.ready_to_confirm is True
        assert result.updated_tasks == []

    def test_rejects_proposal_pushing_incomplete_task_beyond_30_days(self, monkeypatch):
        fake_response = {
            "assistant_message": "기간을 늘려서 옮길게요.",
            "updated_tasks": [
                {
                    "id": 3,
                    "scheduled_date": "2026-09-25",
                    "title": "달력 컴포넌트 연결",
                    "description": "달력 컴포넌트 연결",
                    "estimated_min": 50,
                }
            ],
        }
        monkeypatch.setattr(service, "generate_structured", lambda **kwargs: fake_response)
        monkeypatch.setattr(service.be_client, "notify_conversation", lambda *a, **k: None)

        req = PlanRescheduleRequest(
            conversation_id="conv-1",
            schedule_id="sched-1",
            goal_summary="AI 확정 학습 계획",
            category="학습",
            template_answers=_template_answers(start_date="2026-08-15", end_date="2026-08-31"),
            tasks=self._tasks(),
            user_message="9월 25일로 옮겨줘",
        )
        result = service.reschedule_plan(req)

        assert result.ready_to_confirm is False
        assert result.updated_tasks == []
        assert "30" in result.assistant_message


class TestConfirmReschedule:
    def test_submits_updated_tasks_to_be(self, monkeypatch):
        submitted = []
        monkeypatch.setattr(
            service.be_client,
            "update_scheduled_tasks",
            lambda schedule_id, tasks: submitted.append((schedule_id, tasks)),
        )

        req = PlanRescheduleConfirmRequest(
            schedule_id="sched-1",
            updated_tasks=[
                RescheduledTaskUpdate(
                    id=3,
                    scheduled_date="2026-08-24",
                    title="달력 컴포넌트 연결",
                    description="달력 컴포넌트 연결",
                    estimated_min=50,
                )
            ],
        )
        result = service.confirm_reschedule(req)

        assert result.submitted is True
        assert result.schedule_id == "sched-1"
        assert submitted == [
            (
                "sched-1",
                [
                    {
                        "id": 3,
                        "scheduled_date": "2026-08-24",
                        "title": "달력 컴포넌트 연결",
                        "description": "달력 컴포넌트 연결",
                        "estimated_min": 50,
                    }
                ],
            )
        ]

    def test_be_submission_failure_propagates(self, monkeypatch):
        def _raise(*args, **kwargs):
            raise httpx.HTTPError("boom")

        monkeypatch.setattr(service.be_client, "update_scheduled_tasks", _raise)

        req = PlanRescheduleConfirmRequest(
            schedule_id="sched-1",
            updated_tasks=[
                RescheduledTaskUpdate(
                    id=3,
                    scheduled_date="2026-08-24",
                    title="달력 컴포넌트 연결",
                    description="달력 컴포넌트 연결",
                    estimated_min=50,
                )
            ],
        )

        with pytest.raises(httpx.HTTPError):
            service.confirm_reschedule(req)


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
