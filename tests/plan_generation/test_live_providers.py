"""실제 LLM 프로바이더를 호출하는 라이브 테스트 — 기본 `pytest` 실행에서는 제외된다.

  pytest -m live -q

.env에 뭘 채워뒀는지에 따라 어느 프로바이더가 응답하는지가 정해진다
(app/plan_generation/providers.py의 Gemini → Cerebras → Groq 순서 그대로 탄다).
로컬에서 Groq 키만 넣고 Gemini/Cerebras 키를 비워두면 Groq로 빠르게 확인할 수 있다.
"""

import pytest

from app.plan_generation.providers import generate_structured

pytestmark = pytest.mark.live

_PING_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def test_generate_structured_returns_valid_json():
    result = generate_structured(
        system_prompt="너는 테스트용 봇이다. 사용자가 무엇을 묻든 answer 필드에 'pong'이라고만 답한다.",
        user_content="ping",
        json_schema=_PING_SCHEMA,
        schema_name="ping_test",
    )
    assert "answer" in result
    assert isinstance(result["answer"], str)
