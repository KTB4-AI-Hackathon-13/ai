# template_generation/service.py
import os

from dotenv import load_dotenv
from google import genai

from app.template_generation.schemas import TemplateRequest, TemplateResponse

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


SYSTEM_PROMPT = """
당신은 사용자의 목표 달성을 돕는 서비스의 목표 분석 AI입니다.

사용자가 입력한 한 문장을 분석하여,
구체적인 계획을 생성하기 전에 필요한 정보를 수집할 템플릿을 만드세요.

규칙:

1. 달성하거나 변화시키고 싶은 목표가 아닌 입력이면 action을 reject로 반환합니다.
2. 정상적인 목표라면 action은 generate_template입니다.
3. category는 목표를 대표하는 간결한 영문 카테고리로 작성합니다.
   예: fitness, singing, study, language, social, habit, career
4. goal_summary는 사용자의 목표를 짧고 명확하게 정리합니다.
5. 질문은 계획 생성에 실제로 필요한 정보만 만듭니다.
6. 질문은 최대 8개입니다.
7. 다음 정보는 가능하면 반드시 수집합니다.
   - 현재 수준
   - 시작 날짜
   - 목표 기간
   - 하루 투자 가능 시간
8. 목표 특성에 따라 추가 맞춤 질문을 생성합니다.
9. 사용자가 최초 문장에서 이미 명확하게 제공한 정보는 불필요하게 다시 질문하지 않습니다.
10. 질문 type은 반드시 다음 중 하나만 사용합니다.
    - single_select
    - multi_select
    - short_text
    - number
    - date
11. single_select 또는 multi_select 질문에는 options를 제공합니다.
12. date, number, short_text 질문에는 options를 빈 배열로 반환합니다.
13. 질문 id는 snake_case 영문으로 작성합니다.
14. 질문과 선택지는 자연스럽고 이해하기 쉬운 한국어로 작성합니다.
"""


def generate_template(request: TemplateRequest) -> TemplateResponse:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

    client = genai.Client(api_key=GEMINI_API_KEY)

    interaction = client.interactions.create(
        model=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        input=request.message,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": TemplateResponse.model_json_schema(),
        },
    )

    return TemplateResponse.model_validate_json(interaction.output_text)
