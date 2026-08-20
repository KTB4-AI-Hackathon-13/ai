"""jena 담당 — 계획 생성 대화 엔드포인트.

  POST /plan/generate   템플릿 답변(+참고용 캘린더 정보) → 첫 계획 초안 + 챗봇 소개 멘트
  POST /plan/revise     사용자 피드백 → 수정된 계획 + 챗봇 설명 멘트
  POST /plan/confirm    [B안 반영 후 사실상 불필요] BE는 이미 /plan/revise 응답에서
                         최종 plan을 갖고 있어 이 엔드포인트를 호출할 이유가 없다.
                         팀 논의 후 삭제 여부 결정 — 지금은 호환을 위해 남겨둠.

이 서버는 상태 없는 순수 추론 서버다 — 대화 이력이나 계획 상태를 자체 저장하지 않는다.
매 요청마다 BE가 필요한 컨텍스트(template_answers, current_plan 등)를 그대로 실어 보낸다.
"""

from fastapi import APIRouter, HTTPException

from app.plan_generation import service
from app.plan_generation.providers import GenerationFailed
from app.plan_generation.schemas import (
    PlanConfirmRequest,
    PlanConfirmResponse,
    PlanGenerateRequest,
    PlanReviseRequest,
    PlanTurnResponse,
)

router = APIRouter(prefix="/plan", tags=["plan_generation"])


@router.post("/generate", response_model=PlanTurnResponse)
def generate(req: PlanGenerateRequest) -> PlanTurnResponse:
    try:
        return service.generate_plan(req)
    except service.InvalidDateRange as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenerationFailed as exc:
        raise HTTPException(status_code=502, detail=f"AI 서비스 일시 오류 — 잠시 후 다시 시도해주세요. ({exc})") from exc


@router.post("/revise", response_model=PlanTurnResponse)
def revise(req: PlanReviseRequest) -> PlanTurnResponse:
    try:
        return service.revise_plan(req)
    except service.InvalidDateRange as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GenerationFailed as exc:
        raise HTTPException(status_code=502, detail=f"AI 서비스 일시 오류 — 잠시 후 다시 시도해주세요. ({exc})") from exc


@router.post("/confirm", response_model=PlanConfirmResponse)
def confirm(req: PlanConfirmRequest) -> PlanConfirmResponse:
    # [B안 반영] confirm_plan()이 더 이상 BE로 httpx 호출을 하지 않으므로,
    # httpx.HTTPError를 잡던 예외처리는 삭제했다 (이제 절대 발생하지 않음).
    return service.confirm_plan(req)