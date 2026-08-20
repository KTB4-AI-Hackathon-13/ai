from app.plan_generation.prompts import PLAN_GENERATE_SYSTEM, PLAN_REVISE_SYSTEM


class TestPromptsHonorTemplateAnswerPreferences:
    def test_generate_prompt_instructs_honoring_template_answer_preferences(self):
        assert "template_answers" in PLAN_GENERATE_SYSTEM
        assert "선호" in PLAN_GENERATE_SYSTEM

    def test_revise_prompt_instructs_honoring_template_answer_preferences(self):
        assert "template_answers" in PLAN_REVISE_SYSTEM
        assert "선호" in PLAN_REVISE_SYSTEM
