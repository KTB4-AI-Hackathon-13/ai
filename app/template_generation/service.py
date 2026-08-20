import os

from dotenv import load_dotenv
from google import genai

from app.template_generation.schemas import TemplateQuestion, TemplateRequest, TemplateResponse

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")


SYSTEM_PROMPT = """
당신은 사용자의 목표 달성을 돕는 서비스의 목표 분석 AI입니다.

사용자가 입력한 한 문장을 분석하여,
구체적인 계획을 생성하기 전에 필요한 정보를 수집할 템플릿을 만드세요.

규칙:

1. 달성하거나 변화시키고 싶은 목표가 아닌 입력이면 action을 reject로 반환합니다.
2. 정상적인 목표라면 action은 generate_template입니다.
3. category는 반드시 다음 10개 중 하나를 그대로 선택합니다. 목표와 가장 가까운 것을
   고르고, 목록에 없는 새 카테고리를 만들어내지 않습니다.
   - 운동: 헬스, 러닝, 근력 운동 등 신체 활동
   - 다이어트: 체중 감량, 식단 관리
   - 음악: 노래, 악기 연주
   - 공부: 자격증, 시험, 학업
   - 어학: 외국어 학습
   - 커리어: 이직, 승진, 업무 스킬
   - 습관: 미라클모닝, 독서 등 반복적인 생활 루틴
   - 마인드셋: 자신감, 성격 변화, 스트레스 관리
   - 인간관계: 사회성, 대인관계
   - 취미: 그림, 요리, 창작 등 그 외 취미 활동
4. goal_summary는 사용자의 목표를 짧고 명확하게 정리합니다.
5. 질문은 계획 생성에 실제로 필요한 정보만 만듭니다.
6. 질문은 최대 8개입니다.
7. 다음 정보는 가능하면 반드시 수집합니다.
   - 현재 수준
   - 시작 날짜
   - 종료 날짜
   - 하루 투자 가능 시간
8. 시작 날짜 질문의 id는 반드시 start_date, 종료 날짜 질문의 id는 반드시
   end_date로 작성하고, 둘 다 type은 date로 고정합니다. (다른 질문들의 id는
   자유롭게 정합니다.)
9. 목표 특성에 따라 추가 맞춤 질문을 생성합니다.
10. 사용자가 최초 문장에서 이미 명확하게 제공한 정보는 불필요하게 다시 질문하지 않습니다.
11. 질문 type은 반드시 다음 중 하나만 사용합니다.
    - single_select
    - multi_select
    - short_text
    - number
    - date
12. single_select 또는 multi_select 질문에는 options를 제공합니다.
13. date, number, short_text 질문에는 options를 빈 배열로 반환합니다.
14. 질문 id는 snake_case 영문으로 작성합니다.
15. 질문과 선택지는 자연스럽고 이해하기 쉬운 한국어로 작성합니다.
"""

_REQUIRED_DATE_QUESTIONS = {
    "start_date": "시작 날짜를 선택해주세요.",
    "end_date": "종료 날짜를 선택해주세요.",
}


def _ensure_date_range_questions(response: TemplateResponse) -> TemplateResponse:
    """규칙 7,8번이 있어도 AI가 가끔 놓칠 수 있어, 빠졌으면 코드로 채워 넣는다."""
    if response.action != "generate_template":
        return response

    existing_ids = {q.id for q in response.payload.questions}
    response.payload.questions += [
        TemplateQuestion(id=qid, label=label, type="date", required=True, options=[], placeholder=None)
        for qid, label in _REQUIRED_DATE_QUESTIONS.items()
        if qid not in existing_ids
    ]
    return response


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

    result = TemplateResponse.model_validate_json(interaction.output_text)
    return _ensure_date_range_questions(result)