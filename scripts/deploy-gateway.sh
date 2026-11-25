#!/usr/bin/env bash
# Deploy the gateway to EKS in front of vLLM (Phase 3).
#
#   ./scripts/deploy-gateway.sh                 # cold-start policy "fallback"
#   ./scripts/deploy-gateway.sh --policy wait   # requests wait for vLLM to start
#
# The image is the one CI pushed to ECR for this commit (the terraform
# workflow's apply builds it). Credentials: a JWT secret and a client are
# generated once into local/.env.eks (gitignored). ANTHROPIC_API_KEY is taken
# from your environment, or kept from the cluster if already stored.
# shellcheck source-path=SCRIPTDIR source=_common.sh
source "$(dirname "$0")/_common.sh"

POLICY=fallback
if [[ "${1:-}" == "--policy" ]]; then
  POLICY="${2:-}"
  [[ "$POLICY" == "fallback" || "$POLICY" == "wait" ]] || { echo "usage: $0 [--policy fallback|wait]"; exit 2; }
fi
ENV_FILE="$ROOT/local/.env.eks"

tf_init
REPO=$(terraform -chdir="$DEMO_DIR" output -raw gateway_repository_url)
CLUSTER=$(terraform -chdir="$DEMO_DIR" output -raw cluster_name)
TAG=$(git -C "$ROOT" rev-parse --short=12 HEAD)
aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER" >/dev/null

if ! aws ecr describe-images --repository-name "${REPO#*/}" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
  echo "No gateway image $REPO:$TAG in ECR."
  echo "The terraform workflow's apply pushes the image for the commit it ran on."
  echo "Check out that commit (git checkout main && git pull), or run apply again."
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<ENV
JWT_SECRET=$(openssl rand -hex 32)
CLIENT_ID=loadtest
CLIENT_SECRET=$(openssl rand -hex 16)
ENV
  chmod 600 "$ENV_FILE"
fi
# shellcheck disable=SC1090,SC1091
source "$ENV_FILE"

kubectl apply -k "$ROOT/k8s/base" >/dev/null
API_KEY="${ANTHROPIC_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  API_KEY="$(kubectl -n llm get secret gateway-secrets -o jsonpath='{.data.ANTHROPIC_API_KEY}' 2>/dev/null | base64 --decode 2>/dev/null || true)"
fi
[[ -n "$API_KEY" ]] || echo "Note: no ANTHROPIC_API_KEY; requests during a cold start will fail instead of falling back."
kubectl -n llm create secret generic gateway-secrets \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=CLIENTS="$CLIENT_ID:$CLIENT_SECRET" \
  --from-literal=ANTHROPIC_API_KEY="$API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

kubectl kustomize "$ROOT/k8s/overlays/eks" \
  | sed "s|image: gateway:dev|image: $REPO:$TAG|" \
  | kubectl apply -f -
kubectl -n llm set env deployment/gateway COLD_START_POLICY="$POLICY" >/dev/null
kubectl -n llm rollout restart deployment/gateway >/dev/null
kubectl -n llm rollout status deployment/gateway --timeout=180s
echo
echo "Gateway $REPO:$TAG running, cold-start policy: $POLICY"
