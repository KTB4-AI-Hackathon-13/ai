"""LLM 프로바이더 래퍼 — Gemini(최종 배포용) → Cerebras → Groq 순으로 시도한다.

해커톤 개발 기간 동안은 Gemini 키 없이 Cerebras/Groq로 실사용하고, 제출 직전에
GEMINI_API_KEY를 채워 넣는 것을 전제로 한다 — 코드/폴백 순서는 그대로 두고 .env에
어떤 키가 채워져 있는지로만 실제 사용 프로바이더가 정해진다.

.env 구성:
  GEMINI_API_KEY     최종 배포용. 비어 있으면 자동으로 Cerebras로 스킵된다.
  GEMINI_MODEL       기본 gemini-3.5-flash-lite.
  CEREBRAS_API_KEY   Gemini 없을 때(해커톤 기간 중 기본) 1차로 쓰는 키.
  CEREBRAS_MODEL     기본 gemma-4-31b (Cerebras 공개 엔드포인트 무료 모델).
  GROQ_API_KEY       Gemini/Cerebras 둘 다 없을 때 쓰는 키.
  GROQ_MODEL         기본 openai/gpt-oss-20b (Groq에서 strict json_schema를 지원하는 모델).

세 프로바이더 모두 구조화된 JSON을 강제하는 structured output을 지원하지만 strict 모드
스키마 요구사항이 같아서, 호출 지점에서 같은 raw JSON Schema(schemas.py)를 그대로
재사용할 수 있다.

Gemini는 공식 google-genai SDK를 쓴다. response_schema(OpenAPI 3.0 서브셋)는
additionalProperties 등을 지원하지 않아 우리 strict 스키마를 못 받으므로,
표준 JSON Schema를 그대로 받는 response_json_schema를 대신 사용한다.
"""

import json
import logging
import os

from cerebras.cloud.sdk import Cerebras
from google import genai
from google.genai import types
from groq import Groq

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
CEREBRAS_MODEL = os.environ.get("CEREBRAS_MODEL", "gemma-4-31b")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")


class GenerationFailed(Exception):
    """세 프로바이더 모두 실패했을 때만 던진다."""


def _call_gemini(system_prompt: str, user_content: str, json_schema: dict, schema_name: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_json_schema=json_schema,
        ),
    )
    return json.loads(response.text)


def _call_cerebras(system_prompt: str, user_content: str, json_schema: dict, schema_name: str) -> dict:
    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")

    client = Cerebras(api_key=api_key)
    completion = client.chat.completions.create(
        model=CEREBRAS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
        },
    )
    return json.loads(completion.choices[0].message.content)


def _call_groq(system_prompt: str, user_content: str, json_schema: dict, schema_name: str) -> dict:
    """Gemini/Cerebras 둘 다 실패했을 때 쓰는 마지막 폴백."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
        },
        # gpt-oss는 reasoning 모델이라 사고 과정에 토큰을 많이 쓴다 — 기본값(medium)으로
        # 두면 응답이 긴 경우 최종 JSON을 다 쓰기 전에 토큰 한도에 걸린다.
        reasoning_effort="low",
        max_completion_tokens=4096,
    )
    return json.loads(completion.choices[0].message.content)


def generate_structured(system_prompt: str, user_content: str, json_schema: dict, schema_name: str) -> dict:
    """Gemini로 먼저 시도하고, 실패하면 Cerebras, 그마저 실패하면 Groq로 폴백한다."""
    try:
        return _call_gemini(system_prompt, user_content, json_schema, schema_name)
    except Exception as gemini_exc:  # noqa: BLE001 — 폴백을 위해 의도적으로 광범위하게 잡는다
        logger.warning("Gemini 호출 실패, Cerebras로 폴백: %s", gemini_exc)
        try:
            return _call_cerebras(system_prompt, user_content, json_schema, schema_name)
        except Exception as cerebras_exc:  # noqa: BLE001
            logger.warning("Cerebras 호출 실패, Groq로 폴백: %s", cerebras_exc)
            try:
                return _call_groq(system_prompt, user_content, json_schema, schema_name)
            except Exception as groq_exc:  # noqa: BLE001
                raise GenerationFailed(
                    f"Gemini 실패({gemini_exc}) / Cerebras 실패({cerebras_exc}) / Groq 실패({groq_exc})"
                ) from groq_exc
