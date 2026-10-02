# hungry

Small AI meal-planning app used as a vehicle to build, deploy, scale, observe and
benchmark real cloud infra on AWS. See [`project_plan.md`](./project_plan.md) for the phase
plan and [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the design and concepts.

A **stateless RAG API** on EKS: embed the goal → vector-search recipes in Postgres+pgvector →
prompt an LLM (backend chosen by config) → return a validated JSON meal plan. Postgres (via the
CloudNativePG operator), TEI embeddings and the LLM are each a separate, swappable service.

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

## Phase 1 — AWS EKS

Runs the same app on **AWS EKS**, provisioned by Terraform and deployed with Helm. The cluster is
**ephemeral**: bring it up per session, `terraform destroy` after. The LLM backend is a hosted
OpenAI-compatible API (`LLM_BACKEND=hosted`); self-hosted vLLM on GPU comes in a later phase.

```
deploy/
├── terraform/          # VPC + EKS + EBS CSI (IRSA) + gp3 StorageClass
├── images/             # cnpg-pgvector (Postgres+pgvector for CloudNativePG)
└── hungry/             # Helm umbrella chart: db (CNPG), tei, api (+ ingest Job)
```

### Prereqs
- `terraform`, `aws` CLI, `helm`, `kubectl`
- AWS credentials (`aws configure`) with rights for VPC/EKS/EC2/IAM
- A ghcr.io PAT (`write:packages`) to push images
- The Food.com `RAW_recipes.csv` reachable at a URL for the ingest Job
- A hosted LLM API key

### Bring-up (outline)

```bash
# 1. images -> ghcr.io
docker build -t ghcr.io/<you>/planner-api:latest ./planner-api && docker push ghcr.io/<you>/planner-api:latest
docker build -t ghcr.io/<you>/cnpg-pgvector:17 ./deploy/images/cnpg-pgvector && docker push ghcr.io/<you>/cnpg-pgvector:17

# 2. infra (~15 min)
cd deploy/terraform && terraform init && terraform apply
aws eks update-kubeconfig --name hungry --region us-east-1

# 3. secrets
kubectl create ns hungry
kubectl -n hungry create secret generic hungry-llm --from-literal=HOSTED_API_KEY=<key>

# 4. deploy (CNPG Cluster + TEI + api; ingest Job runs via Helm hook)
helm install hungry ./deploy/hungry -n hungry \
  --set api.ingest.dataUrl=<csv-url>

# 5. smoke test (NLB hostname)
kubectl -n hungry get svc hungry-api
curl -s <nlb-hostname>/health | jq

# 6. teardown at session end
cd deploy/terraform && terraform destroy
```

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for what each piece is and why.
