# Phase 2 evidence: self-hosted model on a GPU node

**Gate (from `docs/BUILD_PLAN.md`):** from zero GPU nodes, deploying vLLM
makes Karpenter launch one; `/v1/models` lists the model; a completion
returns; single-stream and 4-way tokens/s recorded; scaling vLLM to zero
removes the GPU node; instance type, Spot or On-Demand, driver version and the
cold-start timeline recorded.

Paste real output only. Trim account IDs to the last four digits.

## Prerequisite: GPU quota

| Quota | Before | After | When |
|---|---|---|---|
| All G and VT Spot Instance Requests (L-3819A6DF) | 0 vCPU | **8 vCPU** | Requested 2026-11-23 15:49 PT; support case opened and closed; confirmed 8.0 at 22:40 PT the same day |
| Running On-Demand G and VT instances (L-DB2E81BA) | 768 vCPU | unchanged | Already sufficient (a request for 8 was rejected as lower than current) |

## Run

```bash
brew install helm                       # once
export AWS_PROFILE=llm-platform && aws sso login
./scripts/pin-model.sh                  # once: pins the weights' commit; commit the change
gh workflow run terraform.yml -f action=apply    # or: make up
#   (the workflow also runs scripts/k8s-platform.sh up)
aws eks update-kubeconfig --region us-east-1 --name self-hosted-llm-platform-demo
./scripts/vllm-smoke.sh                 # the gate; ~15-30 min, mostly cold start
gh workflow run terraform.yml -f action=destroy  # or: make down
make running
```

## Pre-deployment checks (cloud sandbox, no AWS access)

- `envs/demo` with the Karpenter sub-module validates against the real EKS
  module 21.30.2 and AWS provider 6.73.0 (OpenTofu 1.11).
- NodePool and EC2NodeClass validate against Karpenter v1 schemas; vLLM
  manifests against Kubernetes 1.31 schemas (kubeconform).
- Versions checked at their sources: Karpenter 1.15.3 (the only line that
  supports Kubernetes 1.37), device plugin chart 0.20.2 (its scheduling
  defaults require `nvidia.com/gpu.present=true`, set by the NodePool), vLLM
  v0.34.0 (CUDA 13.0 base, so driver ≥ 580 needed).
- `vllm-smoke.sh` throughput maths tested against a fake OpenAI server;
  `k8s-platform.sh down` tested with stubbed tools in four cases (normal,
  leftover GPU instance with no cluster, AWS call failing, role already
  deleted).
- Not yet done: anything on a real GPU.

## 0. First apply attempt (2026-11-24)

Failed creating the Karpenter controller policy:
`LimitExceeded: Cannot exceed quota for PolicySize: 6144` (incident #7). The
partly built environment was destroyed straight after. PR plan before the
attempt: **Plan: 78 to add, 0 to change, 0 to destroy** (Phase 1's 56 plus
22 for Karpenter). Model pinned to `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`.

## 0b. First smoke test (2026-11-24): GPU worked, vLLM crash-looped

The second apply (with the incident #7 fix) succeeded and installed the
platform (`nodepool.karpenter.sh/gpu  NODES 0  READY True`). Then:

```
[17:20:13Z +0s] Deploying vLLM
[17:20:30Z +17s] NodeClaim created: gpu-c6k27
[17:24:14Z +241s] GPU node Ready: ip-10-40-17-166.ec2.internal, g6.xlarge on-demand us-east-1a
[17:24:28Z +255s] Pod scheduled: vllm-86cc8bcdc-b69w4
Successfully pulled image "vllm/vllm-openai:v0.34.0" in 2m48.205s. Image size: 10036574238 bytes.
[17:50:18Z +1805s] Gave up after 30 minutes.
```

From the crashed container's log, everything up to the last step worked:

```
Loading weights took 36.59 seconds
Model loading took 14.29 GiB memory and 39.998897 seconds
Available KV cache memory: 4.31 GiB
Capturing CUDA graphs (PIECEWISE): 100% 51/51 ... (FULL): 100% 35/35
ValueError: VLLM_PORT 'tcp://172.20.253.250:8000' appears to be a URI.   <- incident #8
```

- **Driver:** CUDA graphs captured, so the AMI's NVIDIA driver runs vLLM's
  CUDA 13.0 build (the ADR 0003 risk did not happen).
- **Spot:** none available. Karpenter launched On-Demand, then tried every 5
  minutes to consolidate onto Spot (`savings: $0.28`); each `CreateFleet`
  returned `UnfulfillableCapacity` for `g6.xlarge` Spot in us-east-1.
- GPU node scaled away after the logs were saved (`replicas=0`).

Teardown after this session (2026-11-24, run 45456030010): the Karpenter
cleanup step passed, then `terraform destroy` failed after 35 m 40 s on a
subnet and security group held by one leaked VPC CNI interface,
`eni-08e3a2e1bc1c42a18` (`available`, `aws-K8S-i-01353f90111fa957b`), incident #9.
`make running` showed nothing billable throughout. After deleting the
interface, run 45471188269 finished the destroy in 42 s and its
"Verify nothing is left billing" step passed.

## 1. Platform install (from the apply run)

Run 45492365744, apply, 15 m 6 s, including the "Install Karpenter, NVIDIA
device plugin, GPU NodePool" step. From the Mac afterwards:

```
NAME                        NODECLASS   NODES   READY   AGE
nodepool.karpenter.sh/gpu   gpu         0       True    33s

NAME                                 READY   AGE
ec2nodeclass.karpenter.k8s.aws/gpu   True    33s
```

(An earlier attempt, run 45481002997, applied fine but a destroy queued
behind it in the workflow's concurrency group, 45481162719, ran as soon as it
was approved, so the cluster was gone before the smoke test. Lesson: start
apply and destroy as separate steps, never from one pasted block.)

## 2. Cold start: zero GPU nodes to model answering

2026-11-24, vLLM v0.34.0, `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`.

```
[21:51:12Z +0s] Deploying vLLM
[21:51:29Z +17s] NodeClaim created: gpu-vjz6f
[21:52:00Z +48s] GPU node Ready: ip-10-40-26-213.ec2.internal, g6.xlarge on-demand us-east-1a
[21:52:15Z +63s] Pod scheduled: vllm-697bdc49bb-27f49
[21:58:33Z +441s] vLLM Ready (model loaded)

-- Image pull and container start (pod events):
  Pulled: Successfully pulled image "vllm/vllm-openai:v0.34.0" in 2m48.634s (2m48.634s including waiting). Image size: 10036574238 bytes.
  Started: Container started
```

| Step | Seconds from deploy |
|---|---|
| NodeClaim created | 17 |
| GPU node Ready (`g6.xlarge`, On-Demand, us-east-1a) | 48 |
| Pod scheduled | 63 |
| Image pulled (10.04 GB in 169 s) | ~232 |
| vLLM Ready (weights downloaded and loaded, CUDA graphs captured) | **441** |

About 209 s of the 441 came after the image pull: downloading ~15 GB of
weights, loading them (36.6 s on the earlier run), compiling and capturing
CUDA graphs. Node launch varied a lot between sessions: 48 s here, 224 s
(NodeClaim to Ready) in the morning run.

## 3. GPU and driver

```
NVIDIA L4, 580.178.04, 19462 MiB, 23034 MiB
```

Driver 580.178.04 meets vLLM v0.34.0's CUDA 13.0 requirement (≥ 580), which
closes the ADR 0003 risk. 19.0 of 22.5 GiB in use matches
`--gpu-memory-utilization=0.90` (weights ~14.3 GiB + KV cache + graphs).

## 4. Serving

```
== /v1/models
{"id":"qwen2.5-7b-instruct","root":"Qwen/Qwen2.5-7B-Instruct","max_model_len":8192}

== One completion
  2.067289s, 33 tokens: "A Kubernetes readiness probe checks if a container is ready to start accepting traffic, ensuring that only healthy instances of a pod are considered ready and can receive workloads."

== Single-stream throughput (512 tokens, temperature 0)
  512 tokens in 29.030324s = 17.6 tokens/s (includes prefill)

== 4 concurrent requests (batching)
  2048 tokens in 29.7s = 69.0 tokens/s aggregate

== vLLM metrics
  vllm:kv_cache_usage_perc{engine="0",model_name="qwen2.5-7b-instruct"} 0.0
  vllm:prompt_tokens_total{engine="0",model_name="qwen2.5-7b-instruct"} 248.0
  vllm:generation_tokens_total{engine="0",model_name="qwen2.5-7b-instruct"} 2593.0
```

- **17.6 tokens/s single-stream is close to the hardware ceiling.** Decoding
  reads all ~15 GB of bf16 weights per token, and the L4's memory bandwidth is
  ~300 GB/s, so the ceiling is ~20 tokens/s; this is ~88% of it.
- **4 concurrent requests: 69.0 tokens/s, 3.9× single-stream** in about the
  same wall time. Continuous batching makes extra concurrent users nearly
  free until KV cache or compute runs out: the core cost argument for
  self-hosting under load, to be priced in Phase 7.
- Unlike the Phase 0 0.5B model (which got readiness probes wrong), this
  answer is correct.

## 5. Scale to zero

```
[21:59:39Z +0s] Scaling vLLM to zero
[22:09:00Z +561s] GPU node removed by Karpenter
```

Removal took 9 m 21 s against `consolidateAfter: 2m`. Not yet explained;
measure in Phase 3 where scale-to-zero timing matters (the node bills the
whole time). Spot capacity was again unavailable, so On-Demand both sessions.

## 6. Teardown

- Run 45498859255 (destroy): "Remove Karpenter nodes and add-ons" passed;
  stage 1 of the staged destroy failed after 28 m 39 s on
  `DeleteSecurityGroup (sg-0a6052d1…) DependencyViolation`. Incident #9b.
  `make running` showed the NAT gateway `nat-056a829728137eb6f` still billing.
- Leaked interface deleted by hand; run 45505239084 (destroy) finished in
  2 m 12 s and its "Verify nothing is left billing" step passed:

```
Checking us-east-1 as romeopeay

ok EKS clusters: none
ok NAT gateways: none
ok Running EC2 instances: none
ok Load balancers: none
ok Unattached EBS volumes: none
ok Unassociated Elastic IPs: none

Verified: nothing billable by the hour in us-east-1.
```

## Cost of this phase

Estimated from run and log times (UTC, 2026-11-24) at ~$0.23/h for the
cluster (EKS + NAT + 2 × t3.medium; the NAT alone ~$0.045/h when it outlived
the cluster) and ~$0.80/h for an On-Demand `g6.xlarge`.

| Session | What happened | Cluster hours | GPU hours | Est. cost |
|---|---|---|---|---|
| A, ~16:20–16:41 | Apply failed on the policy size limit (#7), destroyed | 0.35 | 0 | $0.08 |
| B, ~17:00–19:36 | Platform up; vLLM crash loop (#8); stuck destroy (#9) | 2.4 | ~0.75 | $1.15 |
| C, ~20:40–21:28 | Apply, then a queued destroy removed it before use | 0.8 | 0 | $0.18 |
| D, ~21:35–22:57 | **Gate passed**; destroy stuck again (#9b), NAT until 22:57 | 1.4 | 0.29 | $0.55 |
| **Total** | | **~5.0** | **~1.0** | **~$2.00** |

The passing run itself (GPU from 21:51:29 to 22:09:00) used about 18 minutes
of GPU, roughly $0.23. Everything else was the cost of finding incidents
#7, #8, #9 and #9b. To do: replace the estimate with Cost Explorer
(`Project = self-hosted-llm-platform`) once billing data lands.

## Phase 2 result

**Gate passed on 2026-11-24.** From zero GPU nodes, Karpenter launched a
`g6.xlarge` (On-Demand; no Spot capacity) and vLLM served
Qwen2.5-7B-Instruct after a 7 m 21 s cold start, at 17.6 tokens/s single-stream
and 69.0 tokens/s with 4 concurrent requests; scaling to zero removed the GPU
node. Four incidents found on the way: #7 (IAM policy size), #8 (Service-link
environment variable vs vLLM's own setting), #9 and #9b (leaked VPC CNI
interfaces blocking teardown, and the first fix's wrong staging).
