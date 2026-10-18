# Build Plan

Seven phases. Each one ends with a **verification gate**: a specific thing
that must be run against real infrastructure and pasted into
`docs/evidence/` before the next phase starts. "It applied cleanly" is not a
gate; "I called it and here is what it returned" is.

Rule carried over from log-anomaly-platform incident #7: **nothing counts as
fixed until it is committed.** Every fix found in a shell session gets a
commit before the session ends.

Cost rule: AWS phases are run in timed sessions. `scripts/down.sh` runs at the
end of every session, and the budget alarm from Phase 1 is in place before any
GPU node ever exists.

---

## Phase 0 — Local skeleton (no AWS, ~$0)

**Goal:** the whole request path works on a laptop before any money is spent.

- `local/`: kind cluster; a small CPU-quantized model served by vLLM's CPU
  backend or a llama.cpp server exposing the same OpenAI-compatible API.
- `gateway/`: FastAPI app with JWT auth, one `/v1/chat` endpoint, a provider
  interface with `vllm` and `anthropic` adapters, and `/metrics`.
- `gateway/tests/`: provider adapters mocked; routing and fallback logic
  tested directly.
- Makefile targets: `local-up`, `local-deploy`, `test`.

**Gate:** `curl` through the gateway in kind returns a real completion from the
local model; killing the model pod makes the same call return a Claude API
completion with a `x-served-by: anthropic` header.

## Phase 1 — Terraform foundation on AWS (~$ small, no GPU yet)

**Goal:** credential-free infrastructure with cost guardrails first.

- `bootstrap/`: S3 state bucket, DynamoDB lock table, GitHub OIDC provider,
  deploy role whose trust policy is scoped to this repo and `main` /
  `environment:production`. Applied once, by hand; everything after goes
  through CI.
- `modules/budget`: monthly AWS Budget with email alerts at 50/80/100%.
- `modules/vpc`, `modules/eks`, `modules/ecr`, `modules/iam-irsa`; CPU-only
  system node group.
- `.github/workflows/terraform.yml`: `plan` on PR (posted as a comment),
  `apply` on merge, OIDC only, no stored AWS keys.

**Gate:** a PR shows a real `terraform plan` comment; merge applies it;
`kubectl get nodes` from CI shows the system nodes; the repo has zero AWS
secrets in Settings → Secrets.

## Phase 2 — Self-hosted model on a GPU node

**Goal:** a real open-weight model served on EKS.

- `modules/gpu-nodegroup`: spot GPU instances (start with a single 24 GB
  card class), `min_size = 0`, taint `nvidia.com/gpu=true:NoSchedule`.
- NVIDIA device plugin (via the EKS-optimized GPU AMI or the GPU operator —
  record the choice as an ADR).
- `k8s/vllm/`: Deployment pinned to an exact image digest, model weights
  pulled from the Hub at a pinned revision, readiness probe on `/health`,
  generous startup probe (model load is slow — expect this to be an incident).
- Pick a model that fits one card with headroom (7–8B instruct class) and
  record why in an ADR.

**Gate:** pod scheduled on the GPU node; `/v1/models` lists the model; one
completion returns; tokens/s from vLLM's own metrics recorded in evidence.

## Phase 3 — Scale-to-zero autoscaling on the right signal

**Goal:** prove why CPU-based autoscaling is wrong for LLM serving, then do it
right.

- Install KEDA. `k8s/keda/`: ScaledObject on vLLM's waiting-requests metric
  (via Prometheus), `minReplicaCount: 0`, cooldown tuned to model load time.
- Cluster autoscaling for the GPU node group so a pod needing a GPU brings
  up a node, and an idle node goes away.
- Gateway behavior during cold start: queue with timeout, or fall back to
  Claude immediately — make it a config flag and measure both.

**Gate:** evidence shows (1) a CPU-HPA run where replicas didn't move while
latency climbed, (2) the KEDA run scaling 0→1→N→0 under `loadtest/`, with
timestamps for node spin-up, model load, and first token.

## Phase 4 — Gateway: routing, fallback, quotas, cost

**Goal:** the part platform teams actually own.

- Routing policy: by client, by task tag, or by request size; fallback on
  timeout / 5xx / cold start.
- Per-client token quotas (Redis or in-cluster store) returning `429` with
  `Retry-After`.
- Cost metering: per-request input/output tokens × a price table (API) or
  GPU-hour amortized over tokens served (self-hosted). Exposed as Prometheus
  counters, labeled by client and backend.
- LoRA adapter from the fine-tuning pipeline served as a second "model"
  name through vLLM's adapter support.
- Point the RAG platform and multi-agent platform at the gateway.

**Gate:** a fault-injection run (delete the vLLM pod mid-load) shows zero
client-visible errors and the fallback ratio in Grafana; a quota test shows
the 429; at least one real request from each portfolio client appears in the
gateway's logs.

## Phase 5 — Eval gate in CI

**Goal:** a prompt or model change cannot merge if it makes answers worse.

- `evals/golden/`: start small and honest (e.g. 50–100 items per capability:
  factual Q&A, RAG groundedness, refusal-correctness, structured-output
  validity). Version the files; record how each item was sourced.
- `evals/scorers/`: deterministic scorers first; LLM-as-judge only where
  needed, with the judge prompt versioned and its agreement with a hand-label
  sample measured and reported.
- `evals/baselines/`: accepted scores per (model, adapter, prompt) version.
- `eval-gate.yml`: runs on changes to `prompts/`, `k8s/vllm/` model config, or
  `evals/`; posts a score table on the PR; fails if any capability drops
  beyond its threshold.

**Gate:** a deliberately degraded prompt in a real PR gets blocked by CI, with
the PR comment saved to evidence. Then a genuine improvement passes and
updates the baseline.

## Phase 6 — Observability

**Goal:** one dashboard that answers "is it fast, is it cheap, is it still
good."

- Prometheus scraping gateway + vLLM; Grafana dashboards committed as JSON.
- Panels: p50/p95 latency by backend, time-to-first-token, tokens/s, queue
  depth, replica count, fallback rate, $ per 1K tokens, eval score per
  baseline over time.
- OpenTelemetry spans: gateway → provider → (for RAG clients) retrieval.
- One alert that actually fires during a test (e.g. fallback rate > X%).

**Gate:** dashboard screenshot under real load, a trace screenshot showing the
full span tree, and the alert firing captured in evidence.

## Phase 7 — Red-team, write-up, teardown

**Goal:** close the loop with the rest of the portfolio and publish honest
numbers.

- Run the AI Red-Teaming Platform against the self-hosted endpoint through
  the gateway; record findings and any guardrail added at the gateway layer.
- Fill in the README's results and cost tables from evidence only.
- Compute the self-hosted vs API break-even with `scripts/cost-report.sh`.
- `scripts/down.sh`; confirm in the console and on the bill that nothing is
  left running. Record the final spend.
- Update the portfolio profile README: badges, one-paragraph summary,
  incident count.

**Gate:** `terraform state list` is empty for `envs/demo` (bootstrap kept);
README status line updated to "verified" with a link to every piece of
evidence it cites.

---

## Things I expect to break (so I notice when they do)

Not a substitute for the incident log — a list to check against afterward,
to see which predictions were right and which failures were genuinely new.

- Startup/readiness probes killing vLLM while it's still loading weights.
- GPU node coming up without the device plugin ready; pod stuck `Pending`.
- Spot capacity unavailable for the chosen instance type in the chosen AZs.
- KEDA scaling to zero and the first request timing out at the load balancer
  before a node is even provisioned.
- OIDC trust-policy `sub` claim mismatch (the same class of bug as the Azure
  `AADSTS700213` incident, on a different cloud).
- A mutable image tag silently not rolling out (log-anomaly incident #5) —
  pre-empted by immutable ECR tags + SHA deploys; verify it actually holds.
- Hugging Face gated-model access token not available to the pod.
- Token counts differing between the gateway's estimate and the provider's
  reported usage, skewing cost metrics.
- LLM-as-judge disagreeing with hand labels more than expected.
