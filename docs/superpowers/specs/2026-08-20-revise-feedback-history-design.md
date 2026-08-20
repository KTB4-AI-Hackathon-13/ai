# 계획 수정(revise) 대화의 피드백 히스토리 누적 — 설계 문서

**작성일:** 2026-08-20
**대상 브랜치:** `feature/plan-reschedule`

## 배경

`app/plan_generation/service.py`의 `revise_plan`은 매 요청마다 `current_plan`(직전 계획 상태)과
`user_message`(이번 턴 피드백) 딱 두 가지만 보고 계획을 수정한다. AI 서비스 자체는 완전히
stateless이고 대화 원문은 BE의 `notify_conversation` 호출을 통해 DB에만 기록될 뿐, AI 로직에는
재사용되지 않는다.

문제: 사용자가 여러 턴에 걸쳐 수정 요청을 하면(예: 2턴 전에 "주말 빼줘"라고 했는데 이번 턴
"강도 낮춰줘"만 반영하다가 주말 배치를 실수로 되돌리는 식), AI는 직전 요청만 보고 그 이전
요청들을 알 방법이 없어 같은 실수를 반복할 수 있다.

## 목표

사용자의 과거 수정 요청(피드백) 원문을 최소한으로 누적해서 매 revise 요청에 함께 전달함으로써,
AI가 이전 턴들의 요청을 잊고 되돌리는 실수를 줄인다.

## 설계

### 상태 소유권

AI 서비스는 계속 stateless를 유지한다. `current_plan`과 동일한 패턴으로, 히스토리는
**호출자(FE/BE)가 들고 있다가 매 요청에 실어서 보내는 방식**을 따른다. AI 서비스가 메모리나
DB에 대화 상태를 저장하는 방식(예: `conversation_id` 기준 서버 사이드 저장)은 채택하지 않는다
— 서버 재시작/스케일아웃에 안전하고, 기존 아키텍처와 일관성을 유지하기 위함이다.

### 스키마 변경 (`app/plan_generation/schemas.py`)

```python
class PlanReviseRequest(BaseModel):
    ...
    feedback_history: List[str] = Field(
        default_factory=list,
        description="직전 턴들의 사용자 피드백 원문 목록 (이번 턴의 user_message는 미포함, 오래된 순)",
    )

class PlanTurnResponse(BaseModel):
    ...
    feedback_history: List[str] = Field(
        default_factory=list,
        description="이번 턴까지 누적된 사용자 피드백 원문 목록. 다음 요청에 그대로 다시 실어 보내면 됨",
    )
```

- `PlanGenerateRequest`는 변경하지 않는다 (첫 턴에는 피드백이 존재하지 않음).
- 호출자는 응답으로 받은 `feedback_history`를 다음 revise 요청에 그대로 복사해서 넣기만 하면
  된다 — 배열에 append하는 로직을 호출자가 직접 구현할 필요 없음.

### 서비스 로직 (`app/plan_generation/service.py`)

- `generate_plan`: 모든 응답 분기에서 `feedback_history=[]`를 반환한다 (아직 피드백 턴이 없음).
- `revise_plan`: `req.feedback_history + [req.user_message]`를 계산해 모든 응답 분기
  (30일 초과 거절, 확정 처리, 일반 수정 결과)에 동일하게 반영한다. 거절 케이스에서도 누적값을
  끊지 않고 그대로 돌려줘야, 사용자가 다시 요청할 때 맥락이 유지된다.

### 프롬프트 (`app/plan_generation/prompts.py`)

`PLAN_REVISE_SYSTEM`에 규칙을 추가한다:

```
9. feedback_history가 주어지면 이전 턴들에서 사용자가 이미 요청했던 수정 사항들이다.
   이번 user_message만 보고 과거에 이미 반영하기로 했던 내용을 되돌리거나 잊지 않도록
   feedback_history 전체를 함께 고려해 일관되게 반영한다.
```

`feedback_history`는 `PlanReviseRequest`의 필드이므로 `req.model_dump_json(...)`을 통해 이미
LLM 입력에 포함된다. 별도의 코드 변경 없이 프롬프트 규칙만 추가하면 된다.

### 테스트

- `revise_plan` 응답의 `feedback_history`가 `req.feedback_history + [user_message]`와 정확히
  일치하는지 (일반 수정 케이스, 30일 초과 거절 케이스 각각)
- `generate_plan` 응답의 `feedback_history`가 항상 빈 배열인지
- 기존 테스트들(계약 정합성, 30일 상한)이 `PlanTurnResponse`에 새 필드가 추가돼도 깨지지
  않는지 확인 (필드에 기본값이 있으므로 대부분 영향 없음)

## 범위 밖

- 피드백 히스토리에 상한(예: 최근 N개만 유지)을 두는 것은 이번 범위에 포함하지 않는다.
  실사용에서 문제가 확인되면 별도로 다룬다.
- `assistant_message`나 AI 쪽 응답 히스토리는 누적하지 않는다 — 사용자 요청은 "human 피드백
  내용"만 누적하는 것이었다.
