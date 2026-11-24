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

```
<kubectl get nodepool,ec2nodeclass from the job summary>
```

## 2. Cold start: zero GPU nodes to model answering

```
<vllm-smoke.sh timeline: NodeClaim created, GPU node Ready (type, spot/on-demand, AZ),
 pod scheduled, image Pulled (duration), vLLM Ready>
```

| Step | Seconds from deploy |
|---|---|
| NodeClaim created | |
| GPU node Ready | |
| Image pulled (and pull duration) | |
| vLLM Ready (weights downloaded and loaded) | |

## 3. GPU and driver

```
<nvidia-smi line: name, driver_version, memory.used, memory.total>
```

## 4. Serving

```
<"/v1/models", one completion, single-stream tokens/s, 4-way aggregate tokens/s, vLLM metrics>
```

## 5. Scale to zero

```
<"Scaling vLLM to zero" ... "GPU node removed by Karpenter" with times>
```

## 6. Teardown

```
<destroy run: "Remove Karpenter nodes and add-ons" step, Destroy complete, whats-running>
```

## Cost of this phase

| Item | Window (UTC) | Hours | Rate | Est. cost |
|---|---|---|---|---|
| Cluster (EKS + NAT + 2 × t3.medium) | | | ~$0.23/h | |
| GPU node (type, Spot/On-Demand) | | | | |
