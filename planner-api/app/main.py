from fastapi import FastAPI, HTTPException

from .config import get_settings
from .llm import generate_plan
from .rag import retrieve
from .schema import MealPlan, PlanRequest

app = FastAPI(title="hungry planner-api")


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "llm_backend": s.llm_backend, "model": s.resolved_model}


@app.post("/plan", response_model=MealPlan)
def plan(req: PlanRequest) -> MealPlan:
    candidates = retrieve(req.goal, k=max(12, req.days * req.meals_per_day * 2))
    if not candidates:
        raise HTTPException(status_code=503, detail="No recipes in DB — run ingestion first.")
    try:
        return generate_plan(req, candidates)
    except ValueError as e:
        raise HTTPException(status_code=502, detail=str(e))
