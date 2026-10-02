# Architecture & concepts

How Hungry is built, and the AI-infra concepts behind each piece. The goal of this doc is that
after reading it you can explain the stack — and the general patterns — in an interview.

---

## 1. The one-sentence shape

A **stateless RAG API** on EKS: embed the user's goal → vector-search recipes in Postgres → put
them in an LLM prompt → return a validated JSON meal plan. The DB, embeddings and LLM are each a
**separate, swappable service**.

## 2. Request lifecycle (read path)

```
client ── POST /plan {goal, days, meals_per_day}
   │
   ▼
 NLB ──► planner-api (FastAPI, stateless)
            1. embed(goal)                         ──► TEI            (text → 384-dim vector)
            2. SELECT ... ORDER BY embedding <=> v ──► Postgres+pgvector (ANN → top-k recipes)
            3. chat.completions(system + candidates)──► hosted LLM    (OpenAI-compatible)
            4. validate JSON against MealPlan (retry once on bad JSON)
            ▼
         MealPlan JSON  (days → meals: slot, recipe_id, title, why)
```

There is also a **write path**: the `ingest` Job (CSV → embed in batches → insert into pgvector →
build the ANN index). It is offline and occasional. Keeping read and write paths as separate
workloads is a core data-systems instinct — they have different scaling, resource and failure
profiles.

**RAG (retrieval-augmented generation)** is the central pattern: the model only sees recipes we
retrieved, and the prompt forces it to reference their real `recipe_id`s. That grounds the LLM in
real data and prevents it inventing recipes — the most important pattern in applied AI today.

---

## 3. The app layer (what runs)

| Component | What it is | Why a separate service |
|---|---|---|
| **planner-api** | FastAPI, stateless HTTP | Stateless ⇒ horizontally scalable (HPA), disposable, 12-factor. Holds no data; only orchestrates. |
| **TEI** | HF text-embeddings-inference (CPU) | CPU/batch-bound — a different scaling profile than the API. Swappable embedding model. Keeps the API light. |
| **Postgres + pgvector** | Relational store *and* vector index in one DB | One datastore instead of app-DB + a separate vector DB. SQL-native, simple, fine at this scale. |
| **LLM (hosted)** | Any OpenAI-compatible endpoint | **The key abstraction** — the backend is chosen by config (`LLM_BACKEND` + base URL), so hosted vs self-hosted vLLM becomes an A/B, not a rewrite. |

Why **pgvector** and not Pinecone/Weaviate: fewer moving parts, one connection story, and it
teaches embeddings + approximate-nearest-neighbour (ivfflat) directly. At millions of vectors with
heavy metadata filtering you'd reconsider — that trade-off is the point to be able to articulate.

---

## 4. Kubernetes in 90 seconds (and who runs each part on EKS)

A cluster is made of a **control plane** (the brain) and **nodes** (the muscle).

**Control plane**
- `kube-apiserver` — the REST API everything talks to.
- `etcd` — key-value DB holding all cluster state. Lose it, lose the cluster.
- `kube-scheduler` — decides which node a new pod runs on.
- `kube-controller-manager` — control loops driving actual state toward desired state.

**Node components** (on every worker)
- `kubelet` — agent that makes the container runtime run the pods it's told to.
- container runtime (containerd) — pulls images, runs containers.
- `kube-proxy` — programs the routing rules that make a Service's virtual IP reach the right pods.

**Add-ons** (needed for a usable cluster, not part of the core)
- **CNI** — gives each pod an IP and lets pods talk. On EKS this is the **Amazon VPC CNI**: pods
  get *real VPC IPs* from your subnets, so security groups and flow logs apply directly.
- **CoreDNS** — in-cluster DNS (`svc.namespace.svc.cluster.local`).

**On EKS, AWS runs the entire control plane** (apiserver, etcd, scheduler, controllers) across 3
AZs, patched and backed up, hidden from you. You never SSH into it. You own the **nodes**
(EC2 in a managed node group) and everything you deploy.

| Concern | You (on EKS) | AWS (on EKS) |
|---|---|---|
| apiserver / etcd / scheduler / controllers | — | Managed, multi-AZ |
| Worker nodes | Managed node group (EC2) — you pick size/count | Provisions & rolls the AMI |
| OS / kernel / runtime | — | EKS-optimized AMI |
| CNI, storage driver, DNS | You enable/configure (addons) | Provides the addons |
| Kubernetes upgrades | One API call for the control plane, then roll nodes | Executes it |
| Cost | ~$0.10/h control plane + EC2 + NAT + LB | — |

This is why managed k8s exists: almost all the fragile bootstrap work disappears; you focus on
workloads. Knowing *what disappeared* (and why it mattered) is the interview signal.

---

## 5. The platform pieces in this project

```
AWS account
└─ VPC (10.0.0.0/16, 2 AZ)                         ← network boundary
   ├─ public subnets  → NLB                        ← the only internet-facing thing
   └─ private subnets → EKS managed node group (EC2)
                          ├─ planner-api pod        (stateless)
                          ├─ tei pod + EBS PVC      (model cache)
                          ├─ CNPG postgres pod + EBS PVC  (recipes)
                          └─ ingest Job             (on demand)
   IRSA (OIDC) → pods assume IAM roles, no static keys
```

- **VPC + subnets** — the network. Nodes sit in **private** subnets (no direct inbound); the
  **NLB** sits in **public** subnets and is the single entrypoint. One NAT gateway gives private
  nodes outbound internet (image pulls, the hosted LLM call). *You plan CIDRs so ranges don't
  overlap* — pod, service and VPC ranges must be distinct.
- **EKS managed node group** — EC2 instances registered as k8s nodes; AWS handles registration and
  AMI updates. Here: 2× t3.large, on-demand.
- **EBS CSI driver + gp3 StorageClass** — the storage contract. A `PersistentVolumeClaim` triggers
  the CSI driver to create a real **EBS** volume and attach it to the node running the pod. Without
  a StorageClass, PVCs stay `Pending`. Stateful pods (Postgres, TEI cache) depend on this.
- **IRSA (IAM Roles for Service Accounts)** — a pod's ServiceAccount is bound, via the cluster's
  **OIDC** provider, to an IAM role. The pod gets short-lived AWS credentials with exactly the
  permissions it needs (the EBS CSI controller uses this to create volumes) — **no long-lived
  access keys anywhere**. This is *the* AWS+k8s security pattern; expect it in every EKS interview.
- **NLB via `Service type=LoadBalancer`** — EKS's cloud integration provisions a Network Load
  Balancer (L4) and points it at the api pods. Contrast with an **ALB** (L7, path/host routing) you'd
  use via an Ingress once you have multiple services behind one hostname.
- **CloudNativePG operator** — the **operator pattern**. You write one custom resource (`Cluster`);
  the operator's reconcile loop creates and maintains the StatefulSet, PVCs, primary/replica
  Services, the generated credentials Secret, and backups. Operators are how serious stateful
  software (databases, queues) runs on k8s: encode the human ops knowledge into a controller.

---

## 6. Infrastructure as Code — Terraform

All of section 5 is declared in `deploy/terraform/` using the community `vpc` and `eks` modules.

- **Declarative + state** — you describe desired infra; Terraform diffs it against a state file and
  makes reality match. Code-reviewed infra, not console clicks.
- **Modules** — `terraform-aws-modules/vpc` and `/eks` encapsulate hundreds of resources behind a
  few inputs. Standing on proven building blocks.
- **Ephemeral posture** — `terraform apply` at session start, `terraform destroy` at the end. The
  whole stack is rebuildable from zero, which both proves the IaC is real and keeps spend near zero.
  Trade-off: the DB doesn't survive a destroy, so we re-ingest each session (fine — public data,
  re-runnable Job).

---

## 7. Packaging — Helm

`deploy/hungry/` is an **umbrella chart** with a **subchart per service** (db, tei, api).

- **Templates + values** — k8s manifests parameterised by `values.yaml`. One chart, one
  `helm install`, shared config (`global.storageClass`, `global.registry`, the LLM switch).
- **Secret/config injection** — the api reads `DATABASE_URL` from the CNPG-generated
  `hungry-db-app` Secret and the LLM key from a `hungry-llm` Secret. Nothing sensitive is baked
  into the image or git.
- **Hooks** — the ingest Job carries `helm.sh/hook: post-install,post-upgrade` with
  `before-hook-creation` delete policy, so every `helm upgrade` re-runs ingestion cleanly (Jobs are
  immutable, so the old one is deleted first).

---

## 8. Design principles (name these in interviews)

1. **Stateless vs stateful split** — the API scales freely and is disposable; the DB gets an
   operator + persistent disk. Never conflate the two.
2. **Read path vs write path** — synchronous serving vs offline batch ingestion are different
   lifecycles and different workloads.
3. **Provider abstraction** — the OpenAI-compatible switch turns "which LLM?" into config, enabling
   a real cost/latency/quality benchmark (make vs buy).
4. **Secrets over static keys** — IRSA for AWS, k8s Secrets for app creds, generated DB creds. No
   long-lived keys.
5. **Declarative everything** — Terraform for infra, Helm + CRDs for workloads. Desired state,
   reconciled by controllers.

## 9. Honest trade-offs (knowing these = seniority)

- **Ephemeral kills persistence** → re-ingest per session. Prod would use RDS or S3 snapshot/restore.
- **pgvector, not a dedicated vector DB** → simplest; reconsider at large scale with heavy filtering.
- **Single NAT, single DB instance, public API endpoint** → cost/simplicity over HA. Correct for a
  learning stack, wrong for production, and being able to say *why* is the point.
- **Hosted LLM first** → no serving infra to run yet; the interesting serving story (vLLM,
  continuous batching, KV-cache, TTFT) arrives in the GPU phase.

## 10. Vocabulary quick-reference

| Term | Meaning |
|---|---|
| RAG | Retrieval-augmented generation — ground the LLM in retrieved data. |
| Embedding | A vector representing text's meaning; similar text → nearby vectors. |
| ANN / ivfflat | Approximate nearest-neighbour search; pgvector's index for fast vector queries. |
| Operator / CRD | A controller + custom resource that manages complex software on k8s. |
| StatefulSet | Workload type for stateful pods (stable identity + storage). |
| PVC / StorageClass / CSI | The dynamic-persistent-volume contract; CSI drivers fulfil it with cloud disks. |
| IRSA / OIDC | Pod → IAM role via the cluster's OIDC provider; short-lived AWS creds, no static keys. |
| CNI | Cluster networking plugin; VPC CNI gives pods real VPC IPs. |
| NLB / ALB | L4 / L7 AWS load balancers; entrypoints for `Service`/`Ingress`. |
| HPA / KEDA | Autoscalers — on CPU/memory (HPA) or external metrics like queue depth (KEDA). |
| TTFT | Time to first token — a key LLM-serving latency metric. |
