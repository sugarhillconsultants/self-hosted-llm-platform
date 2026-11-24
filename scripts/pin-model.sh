#!/usr/bin/env bash
# Pin the vLLM model to the exact commit of its weights on Hugging Face, so
# every cold start downloads the same bytes. Rerun to move to a newer commit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KUST="$ROOT/k8s/vllm/kustomization.yaml"

model=$(grep -oE 'MODEL=[^ ]+' "$KUST" | head -1 | cut -d= -f2)
sha=$(curl -sf "https://huggingface.co/api/models/$model" | jq -r .sha)
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not read the commit for $model (got: $sha)"; exit 1; }

perl -pi -e "s/MODEL_REVISION=\S+/MODEL_REVISION=$sha/" "$KUST"
echo "Pinned $model to $sha"
grep -n 'MODEL_REVISION' "$KUST"
