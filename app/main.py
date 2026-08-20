from dotenv import load_dotenv
from fastapi import FastAPI

from app.plan_generation.router import router as plan_generation_router

# from app.template_generation.router import router as template_generation_router  # dennis 담당

load_dotenv()

app = FastAPI()

app.include_router(plan_generation_router)  # jena 담당
# app.include_router(template_generation_router)  # dennis 담당


@app.get("/health")
def health():
    return {"status": "ok"}
