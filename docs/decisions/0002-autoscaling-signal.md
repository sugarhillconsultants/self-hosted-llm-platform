# ADR 0002: Scale vLLM on concurrent demand, not CPU

- **Status:** Accepted (to be confirmed by Phase 3 evidence)
- **Date:** 2026-11-25

## Context
Kubernetes' default autoscaling signal is CPU. LLM serving is GPU-bound and
batched: one vLLM replica serves many concurrent streams, and its CPU use is
dominated by a scheduling loop whose cost barely depends on load. A CPU-based
HPA would neither add replicas when requests queue nor, more importantly for
cost, remove the last one when traffic stops. It also can't scale from zero:
there's no CPU to measure when nothing is running.

## Options considered
- **CPU HPA:** the default. Can't go to zero; expected to be flat under load.
- **vLLM's own queue metrics** (`vllm:num_requests_waiting`) through
  Prometheus + KEDA's prometheus scaler: the right signal for 1 → N, but
  absent at 0 replicas, and needs a Prometheus server.
- **Gateway-reported demand** (ADR 0012) through KEDA's `metrics-api`
  scaler: exists at zero, needs no Prometheus server.

## Decision
KEDA 2.21.1 scales the vLLM Deployment on the gateway's `/scaling`
`self_hosted_demand` (peak concurrent requests wanting the self-hosted model
over the last 120 s), summed across gateway pods: target 4 per replica,
activation above 0, 0–2 replicas, 10-minute cooldown. Karpenter follows with
GPU nodes. Phase 3 records vLLM CPU against demand to show, rather than
assert, that CPU wouldn't have worked.

## Consequences
- Scaling reacts to what users are doing (requests), within one polling
  interval (15 s), including from zero.
- KEDA 2.21's tested window is Kubernetes 1.34–1.36; the cluster is on 1.37.
  `k8s-platform.sh up` checks KEDA's external metrics API is Available.
- "4 per replica" is a demo setting that makes the 1 → 2 step happen at 8
  clients; one L4 served 4 streams at 3.9× single-stream throughput in
  Phase 2, and the real per-replica capacity is a Phase 4 load-test number.
