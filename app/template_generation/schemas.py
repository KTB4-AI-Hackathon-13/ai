from typing import Literal

from pydantic import BaseModel, Field

QuestionType = Literal[
    "single_select",
    "multi_select",
    "short_text",
    "number",
    "date",
]

CategoryType = Literal[
    "운동",
    "다이어트",
    "음악",
    "공부",
    "어학",
    "커리어",
    "습관",
    "마인드셋",
    "인간관계",
    "취미",
]


class TemplateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class TemplateQuestion(BaseModel):
    id: str
    label: str
    type: QuestionType
    required: bool
    options: list[str] = Field(default_factory=list)
    placeholder: str | None = None


class TemplatePayload(BaseModel):
    category: CategoryType | None = None
    goal_summary: str | None = None
    questions: list[TemplateQuestion] = Field(default_factory=list)
    message: str | None = None


class TemplateResponse(BaseModel):
    action: Literal["generate_template", "reject"]
    payload: TemplatePayload