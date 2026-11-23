# Self-Hosted LLM Platform

Self-hosted open-weight LLM serving on AWS EKS (Terraform, vLLM, KEDA scale-to-zero), with an LLM gateway for routing, fallback and cost control, and a CI eval gate that blocks regressions.

<!-- Badges: fill in once each claim is true, not before. -->
![Status](https://img.shields.io/badge/Status-Phases_0_and_1_verified-yellow?style=flat-square)
![Incidents](https://img.shields.io/badge/Incidents-6_documented-orange?style=flat-square)
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
| `infra/terraform/bootstrap/` | $50/month budget alarm, S3 state bucket (native locking), GitHub OIDC provider, `plan` and `apply` roles. Applied once, by hand. |
| `infra/terraform/envs/demo/` | VPC, EKS with 2 CPU nodes and access entries, ECR repo. Created per session, destroyed after (~$0.23/hour). |
| `infra/terraform/modules/budget` | AWS Budget with actual and forecast alerts; the cost guardrail is infrastructure, not a promise |
| `infra/terraform/modules/github-oidc` | OIDC provider + two roles, each trusted by exactly one kind of workflow run |
| `infra/terraform/modules/ecr` | Image repository with immutable tags and a lifecycle policy |
| `infra/terraform/modules/cluster-admins` | Who gets EKS cluster-admin besides the applier; pure logic with `terraform test` cases |
| `infra/terraform/modules/gpu-nodegroup` | Phase 2: GPU node group on spot instances, min size 0 |
| `infra/terraform/modules/iam-irsa` | Phase 4: pod-level IAM (gateway reads secrets; nothing else gets AWS access) |
| `k8s/vllm/` | vLLM Deployment/Service, model + adapter config, GPU tolerations |
| `k8s/keda/` | ScaledObject: scale vLLM on waiting-request queue depth, not CPU; to zero when idle |
| `k8s/gateway/` | Gateway Deployment and Service (Ingress and HPA come in Phase 4) |
| `k8s/local-model/` | Phase 0 stand-in for vLLM: llama.cpp server on CPU, same OpenAI-compatible API |
| `k8s/overlays/local/` | kind overlay: base + gateway + local model + NodePort on localhost:8000 |
| `k8s/observability/` | Prometheus scrape config, Grafana dashboards (JSON), OTel collector |
| `gateway/app/` | FastAPI gateway: client-credentials JWT auth, routing, fallback, Prometheus metrics (quotas, cost metering and OTel in Phases 4 and 6) |
| `gateway/app/providers/` | One adapter per backend behind a common interface: `openai_compat.py` (vLLM or llama.cpp) and `anthropic.py` |
| `gateway/tests/` | Router, API and provider tests with mocked backends (41 tests) |
| `evals/golden/` | Versioned golden eval sets (JSONL), one per capability |
| `evals/scorers/` | Exact-match, groundedness, refusal-correctness, and LLM-as-judge scorers |
| `evals/baselines/` | Last accepted scores per model/prompt version — what the CI gate compares against |
| `prompts/` | Versioned prompt templates; a change here triggers the eval gate |
| `loadtest/` | Load scripts that produce the latency/cost numbers in this README |
| `local/` | `kind-up.sh`, `kind-down.sh`, `smoke-test.sh`: the Phase 0 request path on a laptop, no GPU, no AWS bill |
| `scripts/` | `up.sh` / `down.sh` (create/destroy `envs/demo` from your Mac), `whats-running.sh` (anything still billing?) |
| `.github/workflows/` | `test.yml` (gateway tests + image build); `terraform.yml` (plan on PR, manual apply/destroy); `eval-gate.yml`, `deploy.yml` in later phases |
| `docs/` | Build plan, architecture, ADRs, incidents, evidence (screenshots, raw outputs) |

## Verified results

> Nothing below is filled in until it has actually happened. Paste real
> output, not expected output. If a number is from a single run, say so.

Phase 0, local (kind on an Apple Silicon Mac, 2026-11-19). Full output:
[`docs/evidence/phase-0.md`](docs/evidence/phase-0.md).

```
POST /v1/chat (local Qwen2.5-0.5B, CPU) → 200, x-served-by: self_hosted, 0.25s
POST /v1/chat (model scaled to zero)    → 200, x-served-by: anthropic,
                                           x-fallback-reason: connect_timeout, 3.08s
                                           (was ~30s then HTTP 400 before incidents #2, #3)
gateway_fallbacks_total{reason="connect_timeout"} → 1
```

Phase 1, AWS foundation (us-east-1, 2026-11-23). Full output:
[`docs/evidence/phase-1.md`](docs/evidence/phase-1.md).

```
PR plan (read-only OIDC role)          → Plan: 56 to add, posted as a PR comment
terraform apply (manual, aws-demo env) → Apply complete! Resources: 56 added (17 min run)
kubectl get nodes (from CI and Mac)    → 2 × Ready, v1.37.1, private subnets, one per AZ
terraform destroy + make running       → Verified: nothing billable by the hour
AWS access keys stored in GitHub       → none (two role ARNs, as secrets)
Cost of the phase                      → ~$0.30 estimated (77 cluster-minutes)
```

AWS (Phases 2–7), not yet run:

```
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
Six incidents so far, documented in full in [`docs/incidents.md`](docs/incidents.md):

- Request models defined inside the FastAPI app factory were silently read
  as missing query parameters, because of postponed annotations. Caught by
  the test suite before anything was deployed.
- The first real fallback test failed with a 400: the Claude API now rejects
  `temperature` for the fallback model. Mocked tests couldn't see it. It also
  showed the gateway discarding the upstream error text and blaming the
  client for a gateway fault; both fixed.
- With the model gone, requests hung for the full 30-second timeout before
  failing over, because one timeout covered both "can't connect" and "still
  generating." Split into a 2-second connect timeout and a separate generation
  timeout.
- The first PR plan couldn't sign in to AWS: GitHub now issues immutable
  OIDC subjects (`repo:owner@id/repo@id:…`), and the trust policy expected
  the older name-based form. Found by comparing CloudTrail's rejected
  attempts with the role's trust policy; fixed by trusting the immutable
  form, which also blocks repo-name squatting.
- The first apply failed creating the SSO role's cluster access: I had
  stripped the role's IAM path, a rule for the old `aws-auth` ConfigMap that
  is wrong for access entries. My mocked tests asserted the same wrong rule,
  so they passed.
- The cost-check script said "nothing billable" while every AWS call behind
  it was failing on an expired SSO token. It now verifies credentials first,
  and a failed check can never read as "none."

## Running it

```bash
# Local (no GPU, no AWS bill). Needs Docker Desktop, kind, kubectl, jq.
export ANTHROPIC_API_KEY=sk-ant-...   # optional: enables the fallback path
make test          # gateway unit tests
make local-up      # kind cluster + gateway + small CPU model
make smoke         # the Phase 0 gate: self-hosted answer, then fallback
make local-down

# AWS (costs ~$0.23/hour while up). First time: infra/terraform/README.md
export AWS_PROFILE=llm-platform
make up            # VPC + EKS + ECR in us-east-1
make down          # always; then lists anything still billing
make running       # double-check
```

## What I'd add next

<!-- Fill from real limitations found during the build, the same way
     incident #11 in log-anomaly-platform became a "next" item. -->
- **Measure what the caller waits, not just the backend that answered.**
  On the Phase 0 fallback run, `latency_ms` said 1.07 s while the caller
  waited 3.08 s: the 2.00 s lost on the failed self-hosted attempt shows up
  nowhere. Add an end-to-end request duration (response field + histogram,
  labeled with whether a fallback happened) in Phase 4.
