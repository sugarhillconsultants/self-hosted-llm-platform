# Self-Hosted LLM Platform

Self-hosted open-weight LLM serving on AWS EKS (Terraform, vLLM, KEDA scale-to-zero), with an LLM gateway for routing, fallback and cost control, and a CI eval gate that blocks regressions.

<!-- Badges: fill in once each claim is true, not before. -->
![Status](https://img.shields.io/badge/Status-In_Progress-yellow?style=flat-square)
![Incidents](https://img.shields.io/badge/Incidents-1_documented-orange?style=flat-square)
![EKS](https://img.shields.io/badge/AWS-EKS-FF9900?style=flat-square&logo=amazonaws&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-IaC-7B42BC?style=flat-square&logo=terraform&logoColor=white)
![vLLM](https://img.shields.io/badge/vLLM-self--hosted-blue?style=flat-square)
![KEDA](https://img.shields.io/badge/KEDA-queue--depth_autoscaling-326CE5?style=flat-square)

**Status: `<NOT YET VERIFIED>`** — update this line only when every job in
`.github/workflows/` has actually run and passed against real infrastructure.
Target wording once true: *"fully verified end-to-end: Terraform-provisioned
EKS, a self-hosted open-weight LLM on a GPU node that scales to zero, a gateway
routing between it and the Claude API with live fallback, and a CI eval gate
that has actually blocked a regressing change."* Full account of what broke
along the way: [`docs/incidents.md`](docs/incidents.md).

This project closes the four honest gaps in the rest of this portfolio:
Kubernetes and Terraform were in my stack badges but in no deployed project;
AWS was a certification but not a deployment; every LLM call went to a hosted
API rather than a model I served myself; and drift monitoring covered a
classifier, but nothing watched prompt/model regressions, token cost, or
latency for an LLM.

## How it connects to the rest of the portfolio

- **[Reproducible Fine-Tuning Pipeline](https://github.com/sugarhillconsultants/reproducible-finetuning-pipeline)** →
  its LoRA-trained adapter is served here alongside the base model, so the
  registry's F1 gate and this repo's eval gate cover the same artifact twice.
- **[Multi-Cloud MLOps Showcase](https://github.com/sugarhillconsultants/multi-cloud-mlops-showcase)** →
  the credential-free OIDC pattern, now applied to AWS (IAM role trust on the
  GitHub OIDC provider) instead of Azure federated credentials.
- **[Enterprise RAG Platform](https://github.com/sugarhillconsultants/enterprise-rag-platform)** and
  **[Multi-Agent Security Platform](https://github.com/sugarhillconsultants/multi-agent-security-platform)** →
  become real clients of this gateway, so its cost and latency numbers come
  from real callers, not only a load script.
- **[AI Red-Teaming Platform](https://github.com/sugarhillconsultants/ai-redteam-platform)** →
  gets a new target: a self-hosted model with no provider-side safety layer,
  which is exactly where its findings matter most.
- **[Model Observability Dashboard](https://github.com/sugarhillconsultants/model-observability-dashboard)** →
  covered classical drift; this repo covers the LLM equivalent (eval-score
  drift, cost drift, latency drift).

## Architecture

```
            ┌───────────────────── GitHub Actions (OIDC → AWS IAM role) ─────────────────────┐
            │ terraform plan/apply │ build+push to ECR │ eval gate │ deploy (immutable SHA tag) │
            └────────────────────────────────────────────────────────────────────────────────┘
                                                │
  clients (RAG platform, multi-agent platform, loadtest)
                │  JWT
                ▼
     ┌──────────────────────┐   primary    ┌─────────────────────────────┐
     │  LLM Gateway (FastAPI)│────────────▶│ vLLM (open-weight model      │
     │  routing · fallback   │             │ + LoRA adapter) on GPU node  │
     │  quotas · cost meter  │   fallback  │ group, scale-to-zero via KEDA│
     │  OTel spans           │────────┐    └─────────────────────────────┘
     └──────────────────────┘        │                ▲ queue-depth metric
                │                     └──▶ Claude API  │
                ▼                                      │
   Prometheus ◀── /metrics (gateway + vLLM) ───────────┘
   Grafana: p50/p95 latency · tokens/s · $/1K tokens · eval score over time
   Traces: OpenTelemetry → Tempo (gateway → model → retrieval)
```

Design decisions are recorded as ADRs in [`docs/decisions/`](docs/decisions/).

## What's actually in this repo

| Path | What it does |
|---|---|
| `infra/terraform/bootstrap/` | Remote state bucket + lock table, GitHub OIDC provider, deploy role. Applied once, by hand. |
| `infra/terraform/modules/vpc` | VPC with private subnets for nodes, public subnets for the load balancer |
| `infra/terraform/modules/eks` | EKS control plane, system (CPU) node group, cluster add-ons |
| `infra/terraform/modules/gpu-nodegroup` | GPU node group on spot instances, min size 0, tainted so only inference pods land there |
| `infra/terraform/modules/ecr` | Image repository with immutable tags |
| `infra/terraform/modules/iam-irsa` | Pod-level IAM roles (gateway reads secrets; nothing else gets AWS access) |
| `infra/terraform/modules/budget` | AWS Budget alarm — the cost guardrail is infrastructure, not a promise |
| `infra/terraform/envs/demo` | The one environment, composed from the modules |
| `k8s/vllm/` | vLLM Deployment/Service, model + adapter config, GPU tolerations |
| `k8s/keda/` | ScaledObject: scale vLLM on waiting-request queue depth, not CPU; to zero when idle |
| `k8s/gateway/` | Gateway Deployment and Service (Ingress and HPA come in Phase 4) |
| `k8s/local-model/` | Phase 0 stand-in for vLLM: llama.cpp server on CPU, same OpenAI-compatible API |
| `k8s/overlays/local/` | kind overlay: base + gateway + local model + NodePort on localhost:8000 |
| `k8s/observability/` | Prometheus scrape config, Grafana dashboards (JSON), OTel collector |
| `gateway/app/` | FastAPI gateway: client-credentials JWT auth, routing, fallback, Prometheus metrics (quotas, cost metering and OTel in Phases 4 and 6) |
| `gateway/app/providers/` | One adapter per backend behind a common interface: `openai_compat.py` (vLLM or llama.cpp) and `anthropic.py` |
| `gateway/tests/` | Router, API and provider tests with mocked backends (33 tests) |
| `evals/golden/` | Versioned golden eval sets (JSONL), one per capability |
| `evals/scorers/` | Exact-match, groundedness, refusal-correctness, and LLM-as-judge scorers |
| `evals/baselines/` | Last accepted scores per model/prompt version — what the CI gate compares against |
| `prompts/` | Versioned prompt templates; a change here triggers the eval gate |
| `loadtest/` | Load scripts that produce the latency/cost numbers in this README |
| `local/` | `kind-up.sh`, `kind-down.sh`, `smoke-test.sh`: the Phase 0 request path on a laptop, no GPU, no AWS bill |
| `scripts/` | `up.sh` / `down.sh` / `cost-report.sh` |
| `.github/workflows/` | `test.yml` (gateway tests + image build) now; `terraform.yml`, `eval-gate.yml`, `deploy.yml` in later phases |
| `docs/` | Build plan, architecture, ADRs, incidents, evidence (screenshots, raw outputs) |

## Verified results

> Nothing below is filled in until it has actually happened. Paste real
> output, not expected output. If a number is from a single run, say so.

```
terraform apply (envs/demo)            → <resources created, duration>
kubectl get nodes (GPU group at 0)     → <output>
first request after idle (cold start)  → <seconds to first token, node spin-up time>
POST /v1/chat (self-hosted)            → <response, latency, tokens>
POST /v1/chat (vLLM killed mid-test)   → <fallback to Claude API, latency delta>
quota exceeded for client X            → <429 + header>
eval gate on a deliberately bad prompt → <PR blocked, scores vs baseline>
KEDA scale-up under load               → <replicas over time>
```

### Self-hosted vs API: the actual numbers

| Metric | Self-hosted (vLLM, `<model>`, `<instance>`) | Claude API (`<model>`) |
|---|---|---|
| p50 latency | | |
| p95 latency | | |
| Throughput (tokens/s) | | |
| Cost per 1K output tokens | | |
| Cold start | | n/a |
| Eval score (golden set) | | |

Methodology and raw outputs: [`docs/evidence/`](docs/evidence/). The
break-even point (requests/day at which self-hosting becomes cheaper) is
computed in `scripts/cost-report.sh`, not estimated.

### What this actually cost to build

| Item | Amount |
|---|---|
| GPU node hours | |
| EKS control plane hours | |
| NAT / load balancer / data transfer | |
| Claude API (fallback + LLM-as-judge) | |
| **Total** | |

## Honestly, what it took to get here

<!-- One bullet per incident once they exist, linking to docs/incidents.md.
     Group them by category the way the throughline section does. -->
One incident so far, documented in full in [`docs/incidents.md`](docs/incidents.md):

- Request models defined inside the FastAPI app factory were silently read
  as missing query parameters, because of postponed annotations. Caught by
  the test suite before anything was deployed.

## Running it

```bash
# Local (no GPU, no AWS bill). Needs Docker Desktop, kind, kubectl, jq.
export ANTHROPIC_API_KEY=sk-ant-...   # optional: enables the fallback path
make test          # gateway unit tests
make local-up      # kind cluster + gateway + small CPU model
make smoke         # the Phase 0 gate: self-hosted answer, then fallback
make local-down

# AWS (costs money — see the table above)
cd infra/terraform/bootstrap && terraform apply   # once
./scripts/up.sh
make loadtest && make eval
./scripts/down.sh                                  # always
```

## What I'd add next

<!-- Fill from real limitations found during the build, the same way
     incident #11 in log-anomaly-platform became a "next" item. -->
- 
