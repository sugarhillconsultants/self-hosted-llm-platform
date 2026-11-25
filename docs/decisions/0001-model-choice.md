# ADR 0001: Qwen2.5-7B-Instruct on one NVIDIA L4 (g6 family)

- **Status:** Accepted
- **Date:** 2026-11-23

## Context
The self-hosted model must fit one 24 GB GPU with room for KV cache, be
licensed for a public demo, need no access approval (so the pod can pull it
with no token), run on vLLM, and be strong enough that the self-hosted vs
Claude API comparison means something.

## Options considered
- A 7–8B instruct model in bf16 on an L4 (24 GB): `g6.xlarge`
- A larger model quantized (AWQ/GPTQ) on the same card
- A 7B model on an A10G (`g5`), older and usually pricier per hour

## Decision
`Qwen/Qwen2.5-7B-Instruct`, bf16, on `g6.xlarge` (1 × L4 24 GB, 4 vCPU,
16 GiB). Apache-2.0, not gated, first-class vLLM support. About 15 GB of
weights leaves about 5 GB of KV cache at `--gpu-memory-utilization=0.90`, so
`--max-model-len=8192`. The weights are pinned to an exact Hugging Face commit
(`scripts/pin-model.sh`). `g6.2xlarge` (same GPU, 32 GiB RAM) and, since
incident #10, `g5.xlarge`/`g5.2xlarge` (NVIDIA A10G, also 24 GB) are allowed
as fallbacks when L4 capacity is short.

## Consequences
- Every cold start downloads ~15 GB from Hugging Face. Measured in Phase 2,
  attacked in Phase 3 (cache or pre-baked volume) if it dominates.
- bf16 keeps quality questions out of the first measurements; quantization
  is a later, measured change with the Phase 5 eval gate in place.
- Swapping models is a two-line change in `k8s/vllm/kustomization.yaml`.
