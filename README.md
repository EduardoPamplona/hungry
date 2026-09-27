# hungry

Small AI meal-planning app used as a vehicle to build, deploy, scale, observe and
benchmark real infra. See [`project_plan.md`](./project_plan.md) for the full phase plan.

## Phase 0 — local dev loop

Runs the whole app on your machine via Docker Compose: Postgres+pgvector, a TEI
embedding server, a llama.cpp LLM server, and the FastAPI `planner-api`. The LLM
backend is a config switch (`LLM_BACKEND=llama|hosted`) so the same client can later
point at cloud vLLM or a hosted API.

### Prereqs
- Docker Engine + compose v2 (`docker.io` + `docker-compose-v2` on Ubuntu)
- ~4 GB free RAM, ~5 GB disk (model + images)

### Steps

```bash
cd ~/workspace/hungry

# 1. config
cp .env.example .env

# 2. local model (~2 GB) -> ./models
./scripts/download-model.sh

# 3. dataset -> ./data/RAW_recipes.csv (Kaggle; see script header for manual path)
./scripts/download-data.sh

# 4. bring up db + tei + llama + api (first run pulls images + builds api)
docker compose up -d --build

# 5. load a slice of recipes (embed -> pgvector)
docker compose run --rm api python -m app.ingest /data/RAW_recipes.csv 2000

# 6. smoke test
curl -s localhost:8088/health | jq
curl -s localhost:8088/plan -H 'content-type: application/json' \
  -d '{"goal":"high-protein vegetarian dinners, under 30 min","days":2,"meals_per_day":3}' | jq
```

`/plan` returns a structured `MealPlan` JSON: days -> meals (slot, recipe_id, title, why).

### Switching the LLM backend
Set in `.env`, then `docker compose up -d api`:
- `LLM_BACKEND=llama` (default) — local llama.cpp
- `LLM_BACKEND=hosted` — fill `HOSTED_BASE_URL` / `HOSTED_MODEL` / `HOSTED_API_KEY`

### Ports
| Service | Host port |
|---|---|
| planner-api | 8088 |
| llama.cpp | 8000 |
| TEI | 8081 |
| Postgres | 5432 |
