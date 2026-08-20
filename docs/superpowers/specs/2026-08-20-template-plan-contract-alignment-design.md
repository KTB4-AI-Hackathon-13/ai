# template_generation ↔ plan_generation 계약 정렬 설계

## 배경

`dev` 브랜치에 dennis의 `template_generation`(목표 온보딩 템플릿 생성)과 내
`plan_generation`(계획 생성/수정/확정)이 합쳐졌다. 두 모듈이 실제로 이어 붙는지
점검한 결과, 세 지점에서 계약이 어긋나 있었다:

1. **category 형식 불일치**: `template_generation`은 `category`를 영문 자유
   문자열(`fitness`, `study` 등)로 생성하는데, `plan_generation`의
   `PlanGenerateRequest.category`는 `Literal["운동", "공부", "습관", "기타"]`로
   고정돼 있어 dennis 쪽 값을 그대로 넘기면 즉시 pydantic 검증 에러가 난다
   (`category="fitness"` 재현 확인).
2. **필드명 불일치**: `template_generation`은 목표를 `goal_summary`라는 이름으로
   담는데, `plan_generation`의 요청 스키마는 같은 값을 `goal`이라는 이름으로
   받는다.
3. **날짜 키 보장 없음**: `plan_generation`은 `template_answers`에 정확히
   `start_date`/`end_date` 키가 있어야만 동작하는데, `template_generation`
   프롬프트는 "시작 날짜"와 "목표 기간"을 수집하라고만 되어 있어 `end_date`가
   아예 안 나올 수 있다.

추가로, 계획 전체 기간이 30일을 넘지 못하게 하는 비즈니스 규칙이 서버 쪽에도
필요하다는 요구가 있었다 — FE가 최초 생성 시점엔 날짜 선택 UI로 막아주지만,
`/plan/revise`에서는 사용자가 자연어로 기간 연장을 요청할 수 있어 FE 제어를
우회할 수 있다.

## 원칙

이번 정렬은 **dennis가 만든 `template_generation` 구조를 최대한 따라간다** —
스키마 구조는 그대로 두고 프롬프트 내용만 조정하며, 이름이 다른 필드는 내 쪽
(`plan_generation`)을 dennis 쪽 이름에 맞춘다.

## 1. `template_generation` 프롬프트 변경 (`app/template_generation/service.py`)

`SYSTEM_PROMPT`만 수정한다. 스키마(`TemplatePayload`, `TemplateQuestion`,
`TemplateResponse`)는 변경하지 않는다 — 이미 `category: str`, 자유 `questions`
구조라 그대로 유지 가능.

- 규칙 3 (category 지침): 영문 예시(`fitness, singing, study, language, social,
  habit, career`)를 한글 자유 텍스트 예시(`운동, 노래, 공부, 어학, 인간관계, 습관,
  커리어` 등)로 교체한다. 여전히 "간결한 카테고리를 자유롭게 생성" 방식이며 고정
  목록으로 제한하지 않는다.
- 규칙 7 (필수 수집 정보): "시작 날짜 / 목표 기간"을 "시작 날짜 / 종료 날짜"로
  바꾼다. "목표 기간"은 시작·종료 날짜와 내용이 중복되므로 제거한다.
- 새 규칙 추가: 시작 날짜 질문은 `id`를 반드시 `start_date`로, 종료 날짜 질문은
  `id`를 반드시 `end_date`로, 둘 다 `type`을 `date`로 고정한다. (다른 질문들의
  `id`는 기존 규칙대로 자유 snake_case 유지.)

## 2. `plan_generation` 스키마 정렬 (`app/plan_generation/schemas.py`)

- `Category = Literal["운동", "공부", "습관", "기타"]` 정의를 제거한다.
- `PastGoalSummary.category`, `PlanGenerateRequest.category`,
  `PlanReviseRequest.category` 세 곳 모두 타입을 `str`(빈 문자열 방지를 위해
  `Field(min_length=1)`)로 바꾼다. 카테고리 개수를 고정하지 않는다는 요구사항에
  따라 별도 영→한 매핑 테이블은 두지 않는다 — dennis 프롬프트가 이미 한글을
  생성하므로 그대로 신뢰한다.
- `PlanGenerateRequest.goal` → `goal_summary`로 이름 변경.
- `PlanReviseRequest.goal` → `goal_summary`로 이름 변경 (dennis 템플릿에서 온 같은
  값을 두 요청 모두에서 쓰므로 일관성을 위해 함께 변경).

## 3. `plan_generation` 서비스 로직 변경 (`app/plan_generation/service.py`)

### 3-1. 필드명 반영
`req.goal` → `req.goal_summary`로 참조 변경 (`generate_plan`의
`be_client.notify_conversation` 호출부).

### 3-2. 30일 상한 강제

`MAX_PLAN_DURATION_DAYS = 30` 모듈 상수를 추가한다. generate와 revise는 "언제
기간이 확정되는지"가 다르므로 체크 시점과 방식이 다르다.

**`generate_plan`** — 전체 기간이 `template_answers.start_date`~`end_date`로
요청 시점에 이미 확정돼 있다. 기존 `_require_date_range` 검증(형식·순서) 직후,
`_days_between_inclusive(...)`로 구한 일수가 30을 넘으면:
- LLM(`generate_structured`)을 호출하지 않는다.
- `be_client.notify_conversation`으로 사용자/어시스턴트 메시지를 그대로 기록한다
  (기존 흐름과 동일하게 대화 이력은 남긴다).
- 안내 메시지를 담은 `PlanTurnResponse`를 즉시 반환한다:
  `assistant_message`는 "목표 기간은 최대 30일까지 설정할 수 있어요. 요청하신
  기간은 N일이에요. 시작일과 종료일을 다시 알려주시겠어요?" 형태, `plan`은 빈
  `SchedulePlan(summary="", daily_tasks=[])`, `ready_to_confirm=False`.
- **400 에러를 던지지 않는다** — 이는 `InvalidDateRange`(형식 오류)와는 다른
  경로다. 형식이 잘못된 날짜는 여전히 400으로 처리(기존 동작 유지), 형식은
  맞지만 30일을 초과하는 경우만 이 새 흐름을 탄다.

**`revise_plan`** — 사용자가 자연어로 기간 연장을 요청하면 새 기간은 LLM이
대화를 해석해 정하므로, 요청 시점엔 알 수 없다. 따라서 LLM 호출은 기존대로
수행하고, **응답을 받은 후** 검증한다: `template_answers.start_date`부터
반환된 `daily_tasks` 중 가장 늦은 `scheduled_date`까지의 일수를 계산해 30을
넘으면 (단, `daily_tasks`가 빈 배열이면 — 남은 구간의 모든 과제가 이미 완료돼
더 배치할 게 없는 경우 — 비교 대상이 없으므로 이 체크를 건너뛰고 기존 로직을
그대로 진행한다)
- LLM이 만든 `plan`(및 `user_confirmed`로 인한 BE 제출)을 폐기한다.
- `assistant_message`를 "전체 계획 기간은 최대 30일까지만 가능해요. 요청하신
  대로 하면 N일이 되어 반영하지 못했어요. 다른 방식으로 조정해주시겠어요?"로
  교체한다.
- 응답의 `plan`은 `req.current_plan`(변경 전 계획)을 그대로 사용,
  `ready_to_confirm=False`, `confirmed=False`.
- `user_confirmed=true`였더라도(사용자가 초과 상태를 확정하려 한 경우) 이 체크가
  우선하므로 BE로 아무것도 전송하지 않는다.
- `be_client.notify_conversation`은 기존처럼 사용자 메시지 → (교체된) 어시스턴트
  메시지 순으로 기록한다.

두 체크 모두 `router.py`의 에러 처리 경로(`InvalidDateRange` → 400,
`GenerationFailed` → 502)와 무관하게 정상 `200` 응답의 `PlanTurnResponse`로
처리된다. `router.py`는 변경하지 않는다.

## 4. 안전망 테스트

### 4-1. 계약 정합성 테스트 (신규, `tests/plan_generation/test_contract.py`)
dennis `TemplateResponse` 형태의 더미 데이터(한글 `category`, `goal_summary`,
`start_date`/`end_date`를 포함한 `questions`)를 만들어, 그 값들을
`PlanGenerateRequest`에 매핑했을 때 검증 에러 없이 통과하는지 확인한다. 이번에
발견한 세 불일치(영문 category, `goal` vs `goal_summary`, 날짜 키 누락 가능성)가
재발하면 이 테스트가 실패하도록 한다.

### 4-2. 30일 상한 테스트 (`tests/plan_generation/test_service.py`에 추가)
- `generate_plan`: `start_date`~`end_date`가 31일 → `generate_structured`가
  호출되지 않고 안내 메시지가 담긴 응답이 오는지 확인. 정확히 30일 → 기존처럼
  정상 진행(경계값).
- `generate_plan`: 형식은 맞지만 30일 초과인 경우와, 형식 자체가 틀린 경우
  (`InvalidDateRange`)가 서로 다른 경로로 처리되는지 구분 확인.
- `revise_plan`: LLM이 30일을 넘는 `daily_tasks`(마지막 `scheduled_date`가
  `start_date`+30일 이후)를 반환하면, 그 결과를 버리고 `current_plan`을 유지한
  채 안내 메시지로 교체되는지, `be_client.create_plan_tasks`/`update_plan_tasks`가
  호출되지 않는지 확인.
- `revise_plan`: 30일 이내로 정상 반환되는 기존 케이스는 회귀 없이 통과하는지
  확인.

## 범위 밖

- `template_generation` 모듈 자체의 유닛 테스트(Gemini 클라이언트 모킹)는 이번
  범위에 포함하지 않는다 — 안전망은 "계약 정합성"에 집중한다.
- BE가 `template_answers`를 어떻게 조립해 보내는지(FE에서 수집한 답변을 어떤
  형태로 매핑하는지)는 이 서비스의 범위 밖이며, dennis가 생성하는 질문 `id`와
  BE가 보내는 `template_answers`의 키가 일치한다는 전제를 그대로 따른다.
- category를 완전히 고정된 한글 목록으로 제한하는 것은 하지 않는다(요구사항에
  따라 개수 비고정 유지).
