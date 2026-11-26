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

## Run 2 (2026-11-26): the gate run, fallback policy

Environment from the apply after the incident #10 fix (four zones, g5 and
g6). Fallback policy, profile `60:0,600:4,480:8,900:0`, results folder
`loadtest/results/20261126T120826Z` (gitignored; numbers below transcribed
from `report.py` and `load.py` output). Times are seconds from the first
request; the recorder samples every 10 s, so ±10 s.

### Scaling timeline: 0 → 1 → 2 → 0

| Milestone | +s | Detail |
|---|---|---|
| demand > 0 | 5 | |
| KEDA wants 1 replica | 5 | |
| GPU NodeClaim 1 created | 25 | |
| GPU node 1 Ready | 55 | `g6.xlarge`, On-Demand, us-east-1a |
| vLLM replica 1 Ready | 435 | model load + compile, as in Phase 2 |
| first self-hosted answer | 445 | |
| KEDA wants 2 replicas | 606 | load stepped from 4 to 8 clients at ~600 |
| GPU node 2 Ready | 666 | `g6.2xlarge`, On-Demand, us-east-1a |
| vLLM replica 2 Ready | 1006 | |
| last request finished | 1085 | |
| demand back to 0 | 1206 | |
| KEDA wants 0 replicas | 1797 | |
| GPU NodeClaim deleting | 1938 | |
| GPU NodeClaims gone | 2416 | |

GPU launch attempts (from vLLM pod events): 2 nominated, 2 failed for lack
of capacity (1 of them "no Spot capacity"), then On-Demand succeeded. Spot
`g5`/`g6` was never available in this account during Phase 3.

### What users saw (fallback policy)

| Stage | Clients | Requests | Self-hosted | Claude | Errors | p50 | p95 |
|---|---|---|---|---|---|---|---|
| 1 | 4 | 582 | 79 | 499 | 4 | 1.18 s | 7.52 s |
| 2 | 8 | 441 | 441 | 0 | 0 | 7.62 s | |

Everyone was answered through the 7-minute cold start: Claude took the
first 445 s at a ~1.1 s median, then vLLM took over. The 4 errors were in
stage 1; Phase 4's fault-injection gate is where errors get driven to zero.

**One L4 replica handled 8 concurrent clients with flat latency**: 7.6 s
median at 8 clients against 7.5 s at 4, with throughput rising from about 30
to about 55 requests a minute. So the KEDA target of 4 per replica is too
low; the second GPU was not needed. Not tuned here: the Phase 4 load test
measures real per-replica capacity, and the target follows from it.

### CPU vs demand: why CPU couldn't have scaled this

| Demand | vLLM CPU per replica (millicores) |
|---|---|
| 0 (idle, model loaded) | ~14 |
| 4 | mean 134 (62–973) |
| 8 | mean 359 (14–4245; the peak is replica 2's startup compile) |

At zero replicas there is no CPU to measure, so CPU can never start the
0 → 1. When vLLM is running, its CPU is a fraction of one core whether it
is idle or saturated with work (the work is on the GPU), and the largest
spike in the run is a replica compiling at startup, not demand. An HPA on
CPU would have scaled on the wrong event, or not at all. ADR 0002 holds.

### Scale-down, stage by stage

| Stage | Run 2 | Cause |
|---|---|---|
| last request → demand 0 | 121 s | gateway's 120 s peak window (ADR 0012) |
| demand 0 → KEDA wants 0 | 591 s | KEDA `cooldownPeriod: 600` |
| KEDA wants 0 → NodeClaim deleting | 141 s | Karpenter `consolidateAfter: 2m` + its decision loop |
| NodeClaim deleting → gone | 478 s | drain, then EC2 terminating a GPU instance |
| **total: last request → no GPU** | **1331 s (22 m 11 s)** | |

This explains Phase 2's unexplained 9 m 21 s too: that run had no gateway
window and no KEDA cooldown, only the last two stages (~2 + ~7 min).

About 12 of the 22 minutes are choices (window and cooldown) that trade GPU
cost against re-cold-starting for a user who comes back. The last ~8 minutes
are Karpenter and EC2; run 3's Karpenter log (below) shows that nearly all of
it is EC2 terminating the GPU instance, with nothing left to drain. Not
something this project can tune. Whether EC2 bills those minutes is a
question for Cost Explorer.

## Run 3 (2026-11-26): wait policy, first request from zero

`./scripts/deploy-gateway.sh --policy wait`, then
`./scripts/phase3-run.sh --profile 30:0,600:1,900:0` (one client), results
folder `loadtest/results/20261126T131455Z`.

| | Wait policy (this run) |
|---|---|
| GPU node Ready | +64 s |
| vLLM Ready | +394 s |
| **first request answered** | **403.04 s, by vLLM** |
| requests | 24, all self-hosted |
| Claude requests | 0 |
| errors | 0 |
| p50 after warm-up | 7.31 s |
| launch attempts | 1 nominated, 1 failed (no Spot), On-Demand succeeded |

Scale-down as first printed: 54 s / 670 s / 130 s / 420 s = 1274 s. The
54 s is wrong: the window is 120 s, and 54 + 670 = 724 ≈ 120 + 600. One
`/scaling` sample came back blank (port-forward blip) and the report read it
as demand 0. Fixed: `report.py` now skips blank samples and says how many it
skipped. The recorder rows around it:

```
time_utc,demand,wanting_now
13:25:36Z,1,1
13:25:46Z,1,0          <- last request done; the 120 s peak window starts
13:26:29Z,1,0
13:26:58Z,,            <- failed sample, read as 0 before the fix
13:27:02Z,1,0
13:27:35Z,1,0
13:27:43Z,0,0          <- real end of the window, ~120 s after 13:25:4x
```

Corrected split: ~120 s window, ~600 s cooldown, then Karpenter (below);
the total, 1274 s, was right all along.

Karpenter's own log for the final GPU node:

```
13:38:54.326Z  disrupting node(s)   command: Empty/...
13:38:54.420Z  tainted node         ip-10-40-27-101.ec2.internal
13:45:48.511Z  deleted node         ip-10-40-27-101.ec2.internal
13:45:48.747Z  deleted nodeclaim    gpu-hn97l
```

The node was **Empty** (vLLM already gone), so there was nothing to drain:
the 6 m 54 s between taint and "deleted node" is Karpenter waiting for EC2
to finish terminating the GPU instance before it releases the node. That is
the "drain + terminate" stage in both runs, and it is EC2, not Kubernetes.

`load.py` also printed "first self-hosted answer: 0s", measured
from the request's start rather than its answer; fixed to start + duration.

### Fallback vs wait (ADR 0004, measured)

| Cold-start policy | During the cold start | Claude requests | Errors |
|---|---|---|---|
| **fallback** (run 2) | every user answered, ~1.1 s median, by Claude | 499 | 4 |
| **wait** (run 3) | first user waited 6 m 43 s; nobody answered until vLLM was up | 0 | 0 |

Fallback is the default and stays the default for interactive clients.
Wait suits batch clients, or data that must not leave the cluster. That
makes it a per-client setting, not a global one: Phase 4's routing work.

## Teardown

```
gh run watch  → ✓ Run terraform (45833920591) completed with 'success'
                ✓ Remove Karpenter nodes and add-ons
                ✓ destroy
                ✓ Verify nothing is left billing   (15m1s)

make running
Checking us-east-1 as romeopeay

ok EKS clusters: none
ok NAT gateways: none
ok Running EC2 instances: none
ok Load balancers: none
ok Unattached EBS volumes: none
ok Unassociated Elastic IPs: none

Verified: nothing billable by the hour in us-east-1.
```

The staged destroy (incidents #9, #9b) went through first time.

## Cost of this phase

Estimate from the timelines above at ~$0.23/h for the cluster, $0.805/h
On-Demand `g6.xlarge`, $0.978/h `g6.2xlarge`. Window edges are approximate.

| Session | What happened | Cluster h | GPU h | Est. cost |
|---|---|---|---|---|
| 2026-11-25 | Run 1: no GPU capacity (#10), destroyed | ~2 | 0 | ~$0.46 |
| 2026-11-26 | Runs 2 and 3, destroy | ~2.5 | ~0.65 g6.xl + ~0.5 g6.2xl + ~0.4 g6.xl | ~$1.95 |
| **Total AWS** | | **~4.5** | **~1.55** | **~$2.40** |

Plus Claude API usage for about 2,100 short fallback answers (1,586 in run 1,
499 in run 2; `max_tokens` 128): read from the Console's usage page. To do:
replace the estimate with Cost Explorer (`Project = self-hosted-llm-platform`).

## Phase 3 result

**Gate passed on 2026-11-26.** On queued demand from the gateway, not CPU,
KEDA scaled vLLM 0 → 1 → 2 → 0, and Karpenter followed with GPU nodes: first
self-hosted answer 445 s after the first request, every user answered by
the Claude fallback in the meantime, and no GPU 22 m 11 s after the last
request, each stage of which is accounted for. CPU was shown to be unusable
as the signal (nothing to measure at zero; under a core whether idle or
busy). The wait policy's cost was measured once: 403 s for the first user,
zero API calls. One incident (#10, GPU capacity) and two report bugs found
on the way. Carried into Phase 4: the per-replica target (one L4 handled 8
clients flat) and per-client cold-start policy.
