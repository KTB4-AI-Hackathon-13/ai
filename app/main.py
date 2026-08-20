from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI

from app.template_generation.router import router as template_generation_router

app = FastAPI(title="AI Goal Service")

app.include_router(template_generation_router)
# plan_generation 라우터는 준비되면 여기 추가:
# app.include_router(plan_generation_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}