from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    goal: str = Field(..., description="Free-text: dietary goal, cuisine, constraints")
    days: int = Field(3, ge=1, le=7)
    meals_per_day: int = Field(3, ge=1, le=5)


class Meal(BaseModel):
    slot: str = Field(..., description="e.g. breakfast / lunch / dinner")
    recipe_id: int | None = Field(None, description="id from the candidate list, if used")
    title: str
    why: str = Field(..., description="one line: why this fits the goal")


class DayPlan(BaseModel):
    day: int
    meals: list[Meal]


class MealPlan(BaseModel):
    days: list[DayPlan]
    notes: str = ""


class Candidate(BaseModel):
    id: int
    name: str
    tags: str | None = None
    minutes: int | None = None
