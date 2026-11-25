# Phase 3 evidence: scale-to-zero on the right signal

**Gate (from `docs/BUILD_PLAN.md`):** one recorded run showing (1) vLLM CPU
against demand while replicas change, (2) KEDA scaling 0 → 1 → 2 → 0 with
node launch, model ready and first self-hosted answer timestamped, (3) users
answered throughout the cold start (fallback policy), (4) the wait policy's
first-request latency measured once, and scale-down explained stage by stage.

Paste real output only. Trim account IDs to the last four digits.

## Run

```bash
export AWS_PROFILE=llm-platform && aws sso login
source .venv/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...     # fallback during cold starts
git checkout main && git pull           # the apply builds the image for this commit

gh workflow run terraform.yml -f action=apply     # approve; wait for success
gh run watch
aws eks update-kubeconfig --region us-east-1 --name self-hosted-llm-platform-demo
./scripts/deploy-gateway.sh             # fallback policy
./scripts/phase3-run.sh                 # ~34 min load + up to 25 min scale-down

# (4) wait policy, one client, from zero (~25 min, mostly cooldown):
./scripts/deploy-gateway.sh --policy wait
./scripts/phase3-run.sh --profile 30:0,600:1,900:0

gh workflow run terraform.yml -f action=destroy   # approve; separately
gh run watch && make running
```

Expected cost (estimate): cluster ~1.5–2 h (~$0.40), GPU ~1.2 h On-Demand
(~$1), plus a few hundred short Claude API requests during cold starts
(`max_tokens` 128; check the Console's usage page afterwards).

## Pre-deployment checks (cloud sandbox, no AWS access)

- Gateway: 58 tests, including demand-as-concurrency (50 fallbacks are not
  50 replicas' worth of demand), the peak held through think time and
  expiring after the window, the wait policy retrying until vLLM is up,
  giving up at its deadline, and not waiting on a running-but-slow vLLM.
- Local end to end: real gateway, nothing listening at the vLLM address,
  fake Claude API, then a fake vLLM started mid-test. All requests answered;
  traffic moved to self-hosted within ~2 s of it coming up; `/scaling`
  read 3 with 3 clients and 6 with 6, then 0 after the window. (The first
  version of the demand formula read 69 with 3 clients; ADR 0012.)
- Manifests: ScaledObject validates against KEDA's schema (a misspelled
  field is rejected); all overlays against Kubernetes schemas; the
  vllm-autoscaled overlay starts vLLM at 0 replicas.
- Versions: KEDA 2.21.1 (tested on Kubernetes 1.34–1.36; cluster is 1.37,
  so `k8s-platform.sh up` checks its metrics API is Available),
  metrics-server chart 3.14.0.
- `report.py` checked against a synthetic run with a known timeline;
  `watch.sh` against stubbed `kubectl`.
- Not yet done: anything on EKS.

## 1. Platform and gateway

```
<k8s-platform.sh up: KEDA, metrics-server; deploy-gateway.sh output>
```

## 2. Scaling timeline (fallback policy)

```
<report.py: "Scaling timeline">
```

## 3. What users saw, per minute

```
<report.py: "What users saw, per minute">
```

## 4. CPU vs demand

```
<report.py: "vLLM CPU vs demand">
```

## 5. Scale-down, stage by stage

```
<report.py: "Scale-down, stage by stage">, plus the relevant Karpenter log lines
```

## 6. Wait policy: first-request latency from zero

```
<report.py for the --policy wait run>
```

## 7. Teardown

```
<destroy run, make running>
```

## Cost of this phase

| Item | Window (UTC) | Hours | Rate | Est. cost |
|---|---|---|---|---|
| Cluster | | | ~$0.23/h | |
| GPU nodes (type, Spot/On-Demand) | | | | |
| Claude API during cold starts | | | | |
