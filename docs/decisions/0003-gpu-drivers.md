# ADR 0003: EKS-optimized AL2023 NVIDIA AMI + NVIDIA device plugin

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
A GPU node needs the NVIDIA driver, the container toolkit, and a device
plugin so Kubernetes can schedule `nvidia.com/gpu`.

## Options considered
- **EKS-optimized Amazon Linux 2023, NVIDIA variant** (driver + toolkit
  baked in) plus the NVIDIA device plugin Helm chart
- **NVIDIA GPU Operator**: installs driver, toolkit, plugin, DCGM and more as
  containers on a plain AMI; portable, but many more moving parts and a slower
  first boot (the driver compiles or downloads at node start)
- **Bottlerocket NVIDIA**: driver and device plugin built in; least to manage,
  but a different OS from the system nodes and less familiar to debug

## Decision
AL2023 NVIDIA AMI (Karpenter's `al2023@latest` alias picks the NVIDIA variant
for GPU instance types) plus device plugin chart 0.20.2. The chart only
schedules onto nodes labelled `nvidia.com/gpu.present=true` (or carrying
Node Feature Discovery labels); the `gpu` NodePool sets that label, so no NFD
is needed.

## Consequences
- The driver version is whatever AWS ships in the AMI. vLLM v0.34.0 is built
  on CUDA 13.0 and needs driver ≥ 580; `scripts/vllm-smoke.sh` prints the
  driver version. If it's older, pin an older vLLM rather than switch AMIs.
- `al2023@latest` means a new node may get a newer AMI than the last session.
  Acceptable for a demo; pin `al2023@vYYYYMMDD` once a known-good one is found.
