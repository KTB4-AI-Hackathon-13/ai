# template_generation/schemas.py
from typing import Literal

from pydantic import BaseModel, Field

QuestionType = Literal[
    "single_select",
    "multi_select",
    "short_text",
    "number",
    "date",
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
    category: str | None = None
    goal_summary: str | None = None
    questions: list[TemplateQuestion] = Field(default_factory=list)
    message: str | None = None


class TemplateResponse(BaseModel):
    action: Literal["generate_template", "reject"]
    payload: TemplatePayload
