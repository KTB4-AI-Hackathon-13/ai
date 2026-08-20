# template_generation/schemas.py

from fastapi import APIRouter, HTTPException

from app.template_generation.schemas import TemplateRequest, TemplateResponse
from app.template_generation.service import generate_template

router = APIRouter(prefix="/templates", tags=["templates"])


@router.post("", response_model=TemplateResponse)
def create_template(request: TemplateRequest):
    try:
        return generate_template(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
