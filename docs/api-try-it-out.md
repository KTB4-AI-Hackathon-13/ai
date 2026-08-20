# API Try it out 가이드

로컬에서 서버를 띄우고 `/docs`(Swagger UI)에서 순서대로 눌러보기 위한 예시 모음.
하나의 목표("3주 안에 체중 5kg 감량하기")로 이어지는 시나리오라 순서대로 실행하면
`/templates → /plan/generate → /plan/revise → /plan/confirm` 흐름을 따라갈 수 있고,
마지막엔 이미 확정된 계획을 즉시 수정하는 `/plan/reschedule`도 같이 따로 해볼 수 있다.

## 0. 서버 실행

```bash
uvicorn app.main:app --reload
```

브라우저에서 http://127.0.0.1:8000/docs 접속. `BE_BASE_URL`을 설정하지 않고 실행하면
아웃바운드 BE 호출(`notify_conversation`/`submit_final_plan`)은 전부 조용히 스킵되니
BE 서버 없이도 전체 흐름을 끝까지 테스트할 수 있다.

---

## 1. POST /templates

사용자의 첫 메시지로 질문 템플릿을 생성한다. (dennis 담당)

```bash
curl -X POST http://127.0.0.1:8000/templates \
  -H "Content-Type: application/json" \
  -d '{
    "message": "3주 안에 체중 5kg 감량하고 싶어요"
  }'
```

응답의 `payload.questions`에 있는 질문들에 답했다고 가정하고, 다음 단계의
`template_answers`를 채운다. `start_date`/`end_date`는 항상 고정 id로 내려온다.

---

## 2. POST /plan/generate

템플릿 답변 + (BE가 주는) 참고용 캘린더 정보로 초안 계획을 만든다. (jena 담당)

```bash
curl -X POST http://127.0.0.1:8000/plan/generate \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv_demo_001",
    "schedule_id": "schedule_demo_001",
    "goal_summary": "3주 안에 체중 5kg 감량하기",
    "category": "다이어트",
    "template_answers": {
      "start_date": "2026-08-21",
      "end_date": "2026-09-10",
      "현재_체중": "70kg",
      "운동_경험": "초보"
    },
    "busy_dates": [
      {"date": "2026-08-22", "event_count": 2, "all_day": false}
    ],
    "long_term_context": {
      "past_goals": [
        {"category": "다이어트", "goal": "10kg 감량", "period_days": 60, "completion_status": "abandoned"}
      ],
      "preferences": ["아침엔 시간 없음", "헬스장 장비 없음"]
    }
  }'
```

응답의 `plan`을 다음 단계의 `current_plan`에 그대로 넣는다.

---

## 3. POST /plan/revise

대화로 계획을 조정한다. `current_plan`은 직전 응답의 `plan`을 그대로 넣는다.

```bash
curl -X POST http://127.0.0.1:8000/plan/revise \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv_demo_001",
    "schedule_id": "schedule_demo_001",
    "goal_summary": "3주 안에 체중 5kg 감량하기",
    "category": "다이어트",
    "template_answers": {
      "start_date": "2026-08-21",
      "end_date": "2026-09-10",
      "현재_체중": "70kg",
      "운동_경험": "초보"
    },
    "current_plan": {
      "summary": "3주간 유산소와 홈트레이닝을 번갈아 진행하는 감량 계획",
      "daily_tasks": [
        {"scheduled_date": "2026-08-21", "title": "유산소 30분", "description": "가볍게 걷기 또는 실내 자전거로 30분간 유산소 운동을 합니다.", "estimated_min": 30},
        {"scheduled_date": "2026-08-22", "title": "홈트레이닝 20분", "description": "스쿼트, 플랭크 등 맨몸 운동으로 근력 운동을 합니다.", "estimated_min": 20}
      ]
    },
    "user_message": "주말에는 운동량을 좀 줄여주세요"
  }'
```

`ready_to_confirm: true`가 나오고 사용자가 "이대로 확정할게요" 같은 메시지를
`user_message`로 보내면, 응답의 `confirmed: true`/`submitted`와 함께 대화 중 확정도
가능하다(이 경우 BE 전송까지 이 호출 안에서 일어난다).

---

## 4. POST /plan/confirm

대화 없이 UI의 "확정" 버튼 등으로 최종 계획을 바로 확정할 때 쓰는 별도 엔드포인트.

```bash
curl -X POST http://127.0.0.1:8000/plan/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv_demo_001",
    "schedule_id": "schedule_demo_001",
    "plan": {
      "summary": "3주간 유산소와 홈트레이닝을 번갈아 진행하는 감량 계획",
      "daily_tasks": [
        {"scheduled_date": "2026-08-21", "title": "유산소 30분", "description": "가볍게 걷기 또는 실내 자전거로 30분간 유산소 운동을 합니다.", "estimated_min": 30},
        {"scheduled_date": "2026-08-22", "title": "홈트레이닝 20분", "description": "스쿼트, 플랭크 등 맨몸 운동으로 근력 운동을 합니다.", "estimated_min": 20}
      ]
    }
  }'
```

---

## 5. POST /plan/reschedule + POST /plan/reschedule/confirm (신규)

**이미 캘린더에 확정되어 올라간 계획**을 사용자가 다시 고치고 싶을 때 쓰는 두 단계 엔드포인트.
`/plan/revise`처럼 여러 턴 대화는 안 하지만, **제안(reschedule) → 승인(confirm)** 두 번의
호출로 나뉜다. 전체 계획을 다시 보내는 게 아니라, **실제로 바뀐 태스크만 diff로 다룬다.**

`tasks`엔 이 스케줄(목표 하나)에 속한 **완료 + 미완료 태스크 전체**를 넣는다(BE의
`GET /schedules/{scheduleId}` 응답을 그대로 매핑하면 됨). `completed`는 BE의
`completedAt != null`과 동일 — completed=true인 태스크는 AI가 절대 건드리지 않고
문맥 파악용으로만 참고한다.

### 5-1. POST /plan/reschedule — 제안만 받기 (BE에 아직 반영 안 됨)

```bash
curl -X POST http://127.0.0.1:8000/plan/reschedule \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv_demo_001",
    "schedule_id": "6509",
    "goal_summary": "AI 확정 학습 계획",
    "category": "학습",
    "template_answers": {
      "start_date": "2026-08-15",
      "end_date": "2026-08-31"
    },
    "tasks": [
      {"id": 110317, "scheduled_date": "2026-08-19", "title": "핵심 개념 학습 완료", "description": "핵심 개념 정리", "estimated_min": 45, "completed": true},
      {"id": 110322, "scheduled_date": "2026-08-23", "title": "미니 프로젝트 구현", "description": "미니 프로젝트 구현", "estimated_min": 90, "completed": false},
      {"id": 110323, "scheduled_date": "2026-08-23", "title": "달력 컴포넌트 연결", "description": "달력 컴포넌트 연결", "estimated_min": 50, "completed": false}
    ],
    "user_message": "8월 23일에 두 개가 몰려있어. 달력 컴포넌트 연결을 8월 24일로 옮겨줘."
  }'
```

응답 예시:

```json
{
  "assistant_message": "달력 컴포넌트 연결 일정을 8월 24일로 옮길게요.",
  "updated_tasks": [
    {"id": 110323, "scheduled_date": "2026-08-24", "title": "달력 컴포넌트 연결", "description": "달력 컴포넌트 연결", "estimated_min": 50}
  ],
  "ready_to_confirm": true
}
```

- `updated_tasks`엔 **실제로 바뀔 태스크만** 담긴다 — 안 바뀐 나머지(예: 미니 프로젝트
  구현)는 응답에 아예 안 나온다. 바뀐 게 없으면 빈 배열.
- 순수 날짜 이동만 요청하면 `title`/`description`/`estimated_min`은 원래 값 그대로 유지된 채
  `scheduled_date`만 바뀐다. 난이도 조정처럼 내용 자체를 바꿔달라고 하면 그 값들도 같이 바뀐다.
- `id`는 항상 요청 `tasks`에 있던 기존 id를 그대로 사용한다 — 새 태스크를 만들어내지 않는다.
- 이 호출만으로는 **BE에 아무것도 전송되지 않는다.** `ready_to_confirm: false`면 30일 상한
  초과 등으로 이 제안 자체가 확정 불가능하다는 뜻(`updated_tasks`도 빈 배열).

### 5-2. POST /plan/reschedule/confirm — 승인된 제안을 실제로 반영

사용자가 위 `updated_tasks`를 보고 승인하면, **받았던 그 값을 그대로** 다시 실어 보낸다.

```bash
curl -X POST http://127.0.0.1:8000/plan/reschedule/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "schedule_id": "6509",
    "updated_tasks": [
      {"id": 110323, "scheduled_date": "2026-08-24", "title": "달력 컴포넌트 연결", "description": "달력 컴포넌트 연결", "estimated_min": 50}
    ]
  }'
```

```json
{ "submitted": true, "schedule_id": "6509" }
```

이 호출이 실제로 BE(`PATCH /internal/ai/schedules/{schedule_id}/plan/tasks`)에 변경분을
전송한다. 실패하면 502로 에러가 나서(다른 confirm류 엔드포인트와 동일하게 예외를 그대로
올림) FE가 재시도를 안내할 수 있다. 이 서비스는 상태가 없어서 직전 제안을 기억하지 않으니,
5-1에서 받은 `updated_tasks`를 호출자가 들고 있다가 그대로 다시 보내야 한다.

---

## 참고: 30일 상한 케이스도 테스트해보려면

`template_answers.start_date`/`end_date` 간격을 30일 넘게 잡아서 `/plan/generate`를
호출하면 400 에러가 아니라 `ready_to_confirm: false` + `daily_tasks: []` + 안내 메시지가
담긴 200 응답이 온다. `/plan/revise`는 `current_plan`에 남아있는 태스크의 가장 늦은
`scheduled_date` 기준으로 같은 규칙이 적용된다(이 경우 `current_plan`이 그대로 유지된
채 응답된다). `/plan/reschedule`은 `tasks` 중 completed=false인 것들의 (수정 반영 후)
가장 늦은 날짜 기준으로 같은 규칙이 적용되고, 초과 시 `updated_tasks: []` +
`ready_to_confirm: false`로 돌아온다(이 제안은 confirm으로 넘길 수 없다).
