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

## Run 1 (2026-11-25): no GPU capacity; KEDA and the fallback worked

Environment from apply run 45680159979. Gateway image
`…/self-hosted-llm-platform/gateway:3c2a23931c53`, fallback policy. Load
20:14:03Z–20:33:03Z (`60:0,600:4,480:8,900:0`).

```
stage conc  reqs  ok  self_hosted  claude  errors  p50_s  p95_s  max_s
    1    4   678 670            0     670       8   1.21   3.14   4.30
    2    8   916 916            0     916       0   2.28   3.27   3.45

== Scaling timeline (recorder samples every 10 s, so +/-10 s)
  first request                20:15:03Z  +     0s
  demand > 0                   20:15:07Z  +     4s
  KEDA wants 1 replica         20:15:17Z  +    14s
  GPU NodeClaim 1 created      —
  KEDA wants 2 replicas        20:25:19Z  +   616s
  last request finished        20:33:06Z  +  1083s
  demand back to 0             20:35:10Z  +  1207s
  KEDA wants 0 replicas        20:45:00Z  +  1797s

== Scale-down, stage by stage
  last request -> demand 0 (gateway window)           124s
  demand 0 -> KEDA wants 0 (cooldown)                 590s
```

(The load generator's clock and the recorder's differ by about a minute
in the "first request" line; the KEDA operator log below is authoritative.)

KEDA (operator log and ScaledObject events):

```
2026-11-25T20:14:16Z scaleexecutor Successfully updated ScaleTarget {"Original Replicas Count": 0, "New Replicas Count": 1}
2026-11-25T20:44:01Z scaleexecutor Successfully set ScaleTarget replicas count to ScaledObject minReplicaCount {"Original Replicas Count": 2, "New Replicas Count": 0}
Normal  KEDAScaleTargetActivated    Scaled apps/v1.Deployment llm/vllm from 0 to 1, triggered by s0-metric-api-self_hosted_demand
Normal  KEDAScaleTargetDeactivated  Deactivated apps/v1.Deployment llm/vllm from 2 to 0
```

vLLM pod events (last hour; earlier ones had expired):

```
Normal    Nominated                  Pod should schedule on: nodeclaim/gpu-dhsl9
Warning   InsufficientCapacityError  NodeClaim gpu-vdmpl ... UnfulfillableCapacity: Unable to fulfill capacity due to your request configuration.
Warning   FailedScheduling           Failed to schedule pod, nodepool requirements filtered out all available instance types
Warning   InsufficientCapacityError  NodeClaim gpu-brhsx ... InsufficientInstanceCapacity: There is no Spot capacity available that matches your request.; UnfulfillableCapacity ...
Normal    ScalingReplicaSet          Scaled down replica set vllm-697bdc49bb from 2 to 0
```

GPU offerings in this account (`describe-instance-type-offerings`):
`g5.xlarge`, `g5.2xlarge`, `g6.xlarge`, `g6.2xlarge` in us-east-1a, b, c, d
and f. The VPC's private subnets were in us-east-1a and b only. Incident #10.

What this run proves: demand → KEDA → Deployment works from zero and back
(including on Kubernetes 1.37, outside KEDA's tested window), and the fallback
policy kept users answered through 18 minutes without any GPU. What it
doesn't: anything about vLLM under KEDA. Run 2, after the incident #10 fix.

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
