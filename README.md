# AI 서비스

목표 달성 코치 챗봇의 AI 마이크로서비스. 상태 없는 순수 추론 서버로, DB/세션 없이 BE(SpringBoot)가 매 요청에 필요한 컨텍스트를 실어 보낸다.

- `app/template_generation` — 목표 텍스트를 받아 정보수집 템플릿(질문지)을 만든다. (dennis 담당)
- `app/plan_generation` — 템플릿 답변을 받아 실제 날짜 기준 일별 계획표를 만들고, 대화로 조정한 뒤 확정되면 BE로 전송한다. (jena 담당)

## 로컬 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 값 채워넣기
uvicorn app.main:app --reload
```

## plan_generation API

| Method | Path | 설명 |
| --- | --- | --- |
| POST | `/plan/generate` | 목표+템플릿 답변(+참고용 캘린더 정보) → 첫 계획 초안 + 챗봇 소개 멘트 |
| POST | `/plan/revise` | 계획에 대한 사용자 피드백 → 수정된 계획 + 챗봇 설명 멘트 |
| POST | `/plan/confirm` | 사용자가 최종 확정한 계획 → BE로 전송 |

캘린더 충돌(하루 작업 개수 상한 등)의 최종 검증은 BE가 담당한다 — 이 서비스는 `busy_dates`를 참고용 힌트로만 사용하고, 문제가 있으면 `/plan/revise` 대화로 조정하는 것을 전제로 한다.

`BE_BASE_URL`을 비워두면 BE로의 대화 기록/최종 계획 전송을 건너뛴다(로컬 단독 테스트용).

## 테스트

```bash
pytest              # 단위 테스트만 (LLM mock, 네트워크 호출 없음)
pytest -m live      # 실제 LLM 프로바이더 호출까지 확인 (.env에 채운 키 순서대로 Gemini→Cerebras→Groq)
```

`GEMINI_API_KEY`를 비워두면 `pytest -m live`도 Cerebras/Groq로 폴백한다 — 해커톤 기간 중 기본으로 쓰는 조합.
