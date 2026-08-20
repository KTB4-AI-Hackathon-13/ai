from app.template_generation.service import SYSTEM_PROMPT


class TestSystemPromptCollectsPreferences:
    def test_required_info_list_includes_preferences_or_constraints(self):
        assert "제약" in SYSTEM_PROMPT or "선호" in SYSTEM_PROMPT
