import json

from openai import OpenAI

from .config import get_settings
from .schema import Candidate, MealPlan, PlanRequest

_SYSTEM = """You are a meal planner. Build a plan using ONLY the candidate recipes provided.
Return STRICT JSON matching this shape (no prose, no markdown):
{
  "days": [
    {"day": 1, "meals": [
      {"slot": "breakfast", "recipe_id": 123, "title": "...", "why": "..."}
    ]}
  ],
  "notes": "..."
}
Every meal's recipe_id MUST be one of the candidate ids. Match the requested number
of days and meals_per_day exactly."""


def _client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.resolved_base_url, api_key=s.resolved_api_key)


def _prompt(req: PlanRequest, candidates: list[Candidate]) -> str:
    lines = [f"- id={c.id} | {c.name} | tags={c.tags} | minutes={c.minutes}" for c in candidates]
    return (
        f"Goal: {req.goal}\n"
        f"Days: {req.days}\n"
        f"Meals per day: {req.meals_per_day}\n\n"
        f"Candidate recipes:\n" + "\n".join(lines)
    )


def generate_plan(req: PlanRequest, candidates: list[Candidate]) -> MealPlan:
    client = _client()
    model = get_settings().resolved_model
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _prompt(req, candidates)},
    ]

    last_err: Exception | None = None
    for _ in range(2):  # one retry on malformed JSON
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        raw = resp.choices[0].message.content or ""
        try:
            return MealPlan.model_validate(json.loads(raw))
        except Exception as e:  # noqa: BLE001 - retry on any parse/validation failure
            last_err = e
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {"role": "user", "content": f"That was not valid. Error: {e}. Return valid JSON only."}
            )
    raise ValueError(f"LLM did not return a valid plan: {last_err}")
