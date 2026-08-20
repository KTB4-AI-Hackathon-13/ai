"""BE로 나가는 아웃바운드 호출 2가지.

  1. notify_conversation  대화 메시지 한 턴을 BE로 보내 DB에 쌓는다 (vinny 담당 API).
  2. submit_final_plan    사용자가 최종 확정한 계획을 BE로 보내 캘린더에 반영한다 (vinny 담당 API).

경로/페이로드는 BE 쪽 실제 계약이 확정되면 조정한다 — 지금은 잠정 값이다.
BE_BASE_URL이 비어 있으면(로컬 단독 테스트 등) 호출을 건너뛰고 조용히 무시한다.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0)


def _base_url() -> str | None:
    return os.environ.get("BE_BASE_URL") or None


def notify_conversation(conversation_id: str, role: str, content: str) -> None:
    """대화 메시지 한 턴을 BE에 알린다. 실패해도 계획 생성 흐름은 막지 않는다(best-effort)."""
    base_url = _base_url()
    if not base_url:
        logger.info("BE_BASE_URL 미설정 — 대화 기록 전송 생략")
        return

    try:
        httpx.post(
            f"{base_url}/internal/ai/conversations/{conversation_id}/messages",
            json={"role": role, "content": content},
            timeout=_TIMEOUT,
        ).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("대화 기록 BE 전송 실패(무시하고 진행): %s", exc)


def submit_final_plan(schedule_id: str, plan: dict) -> None:
    """확정된 계획을 BE로 전송한다. 실패 시 예외를 그대로 올려서 호출자가 사용자에게 알리게 한다."""
    base_url = _base_url()
    if not base_url:
        logger.info("BE_BASE_URL 미설정 — 최종 계획 전송 생략")
        return

    httpx.post(
        f"{base_url}/internal/ai/schedules/{schedule_id}/plan",
        json=plan,
        timeout=_TIMEOUT,
    ).raise_for_status()
