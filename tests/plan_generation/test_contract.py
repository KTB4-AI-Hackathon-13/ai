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
