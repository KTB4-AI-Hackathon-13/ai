"""BE로 나가는 아웃바운드 호출들.

  1. notify_conversation  대화 메시지 한 턴을 BE로 보내 DB에 쌓는다 (vinny 담당 API).
  2. create_plan_tasks    확정된 계획 중 새로 생성하는 태스크(id 없음)를 BE로 보낸다 (vinny 담당 API).
  3. update_plan_tasks    확정된 계획 중 기존 태스크(id 있음)의 수정 내용을 BE로 보낸다 (vinny 담당 API).

생성/수정을 별도 엔드포인트로 나누는 이유: 이미 캘린더에 올라가 완료 처리된 태스크가 섞여
있는 재조정(revise) 확정 흐름에서, BE가 "새 태스크 추가"와 "기존 태스크 내용 변경"을 요청
단계에서부터 명확히 구분해 처리(및 이력 기록)할 수 있게 하기 위함이다.

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


def create_plan_tasks(schedule_id: str, summary: str, tasks: list[dict]) -> None:
    """확정된 계획 중 새로 생성할 태스크(id 없음)를 BE로 전송한다.
    실패 시 예외를 그대로 올려서 호출자가 사용자에게 알리게 한다."""
    base_url = _base_url()
    if not base_url:
        logger.info("BE_BASE_URL 미설정 — 신규 태스크 전송 생략")
        return
    if not tasks:
        return

    httpx.post(
        f"{base_url}/internal/ai/schedules/{schedule_id}/plan/tasks",
        json={"summary": summary, "tasks": tasks},
        timeout=_TIMEOUT,
    ).raise_for_status()


def update_plan_tasks(schedule_id: str, summary: str, tasks: list[dict]) -> None:
    """확정된 계획 중 기존 태스크(id 있음)의 수정 내용을 BE로 전송한다.
    실패 시 예외를 그대로 올려서 호출자가 사용자에게 알리게 한다."""
    base_url = _base_url()
    if not base_url:
        logger.info("BE_BASE_URL 미설정 — 태스크 수정 전송 생략")
        return
    if not tasks:
        return

    httpx.patch(
        f"{base_url}/internal/ai/schedules/{schedule_id}/plan/tasks",
        json={"summary": summary, "tasks": tasks},
        timeout=_TIMEOUT,
    ).raise_for_status()
