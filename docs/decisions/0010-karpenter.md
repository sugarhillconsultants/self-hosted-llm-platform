# ADR 0010: Karpenter for GPU nodes, instead of a managed node group + Cluster Autoscaler

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
The plan had a `gpu-nodegroup` module: an EKS managed node group of Spot GPU
instances with `min_size = 0`, scaled by Cluster Autoscaler. Requirements:
scale from zero when a GPU pod is pending, back to zero when idle, Spot first
with On-Demand fallback (the account has 8 vCPUs of G-family Spot quota and
768 On-Demand), and never more than one GPU.

## Options considered
- Managed node group (Spot) + Cluster Autoscaler. Scaling from zero needs ASG
  tags describing the node's labels, taints and GPU count, because there's no
  node to inspect. Spot → On-Demand fallback needs a second node group and the
  priority expander.
- **Karpenter**: provisions nodes directly from pending pods' requirements.
  One NodePool allows both capacity types and prefers the cheaper (Spot);
  `limits: nvidia.com/gpu: 1` is a hard cap; consolidation removes empty nodes.

## Decision
Karpenter 1.15.3 (the only line supporting Kubernetes 1.37), with one `gpu`
NodePool (g6 xlarge/2xlarge, Spot or On-Demand, GPU taint, cap of 1 GPU,
consolidate after 2 minutes empty). The system node group stays a managed
node group, so Karpenter itself never runs on a node it manages.

## Consequences
- GPU nodes are not in Terraform state. Destroying with one running would
  leave it billing and block VPC deletion, so teardown always runs
  `scripts/k8s-platform.sh down` first: it deletes the NodePool, waits for
  nodes to terminate, and as a failsafe terminates any instance tagged for
  this cluster's NodePools and removes leftover instance profiles.
- Phase 3's question shifts from "how do nodes scale" (solved here) to "what
  scales the vLLM pods": KEDA on queue depth.
