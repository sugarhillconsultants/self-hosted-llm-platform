#!/usr/bin/env bash
# Phase 0: the whole request path on your laptop, no AWS.
# Creates a kind cluster, builds the gateway image, and deploys the gateway
# plus a small CPU model (llama.cpp) behind it.
#
# Optional: export ANTHROPIC_API_KEY=... first to enable the fallback path.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLUSTER=llm-local
ENV_FILE="$ROOT/local/.env.local"

for tool in docker kind kubectl openssl; do
  command -v "$tool" >/dev/null || { echo "missing: $tool (see docs/evidence/phase-0.md)"; exit 1; }
done

if ! kind get clusters | grep -qx "$CLUSTER"; then
  kind create cluster --config "$ROOT/local/kind-config.yaml"
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

# Immutable tag per commit (+ "-dirty" for uncommitted changes), never :latest.
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
git -C "$ROOT" diff --quiet || TAG="$TAG-dirty-$(date +%s)"
docker build -t "gateway:$TAG" "$ROOT/gateway"
kind load docker-image "gateway:$TAG" --name "$CLUSTER"

# Credentials: generated once, kept in a gitignored file so smoke-test.sh
# (and you) can request tokens.
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<ENV
JWT_SECRET=$(openssl rand -hex 32)
CLIENT_ID=local-dev
CLIENT_SECRET=$(openssl rand -hex 16)
ENV
  chmod 600 "$ENV_FILE"
fi
# shellcheck disable=SC1090,SC1091
source "$ENV_FILE"

kubectl apply -k "$ROOT/k8s/base"
# Keep a previously stored API key when this terminal doesn't have one
# exported, rather than silently replacing it with an empty value.
API_KEY="${ANTHROPIC_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  API_KEY="$(kubectl -n llm get secret gateway-secrets \
    -o jsonpath='{.data.ANTHROPIC_API_KEY}' 2>/dev/null | base64 --decode 2>/dev/null || true)"
  [[ -n "$API_KEY" ]] && echo "Using the ANTHROPIC_API_KEY already stored in the cluster."
fi
kubectl -n llm create secret generic gateway-secrets \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=CLIENTS="$CLIENT_ID:$CLIENT_SECRET" \
  --from-literal=ANTHROPIC_API_KEY="$API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl kustomize "$ROOT/k8s/overlays/local" \
  | sed "s|image: gateway:dev|image: gateway:$TAG|" \
  | kubectl apply -f -
# Secret changes don't restart pods on their own.
kubectl -n llm rollout restart deployment/gateway >/dev/null

echo "Waiting for the gateway..."
kubectl -n llm rollout status deployment/gateway --timeout=120s
echo "Waiting for the model (first run downloads ~400 MB; can take several minutes)..."
kubectl -n llm rollout status deployment/local-model --timeout=900s

echo
echo "Ready: gateway on http://localhost:8000 (image gateway:$TAG)"
[[ -z "$API_KEY" ]] && echo "Note: no ANTHROPIC_API_KEY set or stored, so fallback will return 502."
echo "Next: ./local/smoke-test.sh"
