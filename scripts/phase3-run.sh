#!/usr/bin/env bash
# The Phase 3 gate: KEDA scaling vLLM 0 -> 1 -> 2 -> 0 on gateway demand.
#
#   ./scripts/phase3-run.sh [--profile 60:0,600:4,480:8,900:0]
#
# Needs: the environment up (apply), the gateway deployed
# (scripts/deploy-gateway.sh), and Python with httpx (the project .venv).
# Default profile, ~34 min of load then up to 25 min watching scale-down:
#   1 min idle | 10 min at 4 clients (cold start; KEDA -> 1 replica)
#   8 min at 8 clients (KEDA -> 2 replicas) | 15 min idle (back to 0)
# Results land in loadtest/results/<timestamp>-*.{csv,txt}.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NS=llm
PROFILE="60:0,600:4,480:8,900:0"
[[ "${1:-}" == "--profile" ]] && PROFILE="${2:?profile}"
RUN="$ROOT/loadtest/results/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$ROOT/loadtest/results"
PY=${PYTHON:-python}

for tool in kubectl jq curl "$PY"; do command -v "$tool" >/dev/null || { echo "missing: $tool"; exit 1; }; done
"$PY" -c 'import httpx' 2>/dev/null || { echo "Python needs httpx: source .venv/bin/activate"; exit 1; }
kubectl get apiservice v1beta1.external.metrics.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null \
  | grep -q True || { echo "KEDA's metrics API isn't Available: run ./scripts/k8s-platform.sh up"; exit 1; }
kubectl -n "$NS" rollout status deploy/gateway --timeout=10s >/dev/null 2>&1 \
  || { echo "Gateway not running: ./scripts/deploy-gateway.sh"; exit 1; }

echo "== vLLM under KEDA (starts at 0 replicas)"
kubectl apply -k "$ROOT/k8s/overlays/vllm-autoscaled" >/dev/null
for _ in $(seq 1 30); do
  [[ "$(kubectl -n $NS get deploy vllm -o jsonpath='{.spec.replicas}')" == "0" ]] \
    && [[ -z "$(kubectl get nodeclaims -l karpenter.sh/nodepool=gpu -o name)" ]] && break
  sleep 10
done
kubectl -n $NS get scaledobject vllm

# Port-forward to the gateway, restarted if it drops.
( while :; do kubectl -n $NS port-forward svc/gateway 18080:8000 >/dev/null 2>&1; sleep 1; done ) &
PF=$!
"$ROOT/loadtest/watch.sh" "$RUN-watch.csv" http://localhost:18080 &
WATCH=$!
trap 'kill $WATCH $PF 2>/dev/null; pkill -P $PF 2>/dev/null' EXIT
sleep 5

echo "== Load: $PROFILE"
"$PY" "$ROOT/loadtest/load.py" --profile "$PROFILE" --url http://localhost:18080 --out "$RUN-requests.csv" \
  | tee "$RUN-load.txt"

echo "== Waiting for scale to zero (up to 25 min)"
for _ in $(seq 1 150); do
  [[ "$(kubectl -n $NS get deploy vllm -o jsonpath='{.spec.replicas}')" == "0" ]] \
    && [[ -z "$(kubectl get nodeclaims -l karpenter.sh/nodepool=gpu -o name)" ]] && break
  sleep 10
done
sleep 15   # one more recorder sample at zero

kubectl -n kube-system logs deploy/karpenter --since=2h 2>/dev/null \
  | grep -E 'disrupting|launched nodeclaim|registered nodeclaim|initialized nodeclaim|deleted node|terminat|UnfulfillableCapacity|InsufficientInstanceCapacity' \
  > "$RUN-karpenter.log" || true
kubectl -n keda logs deploy/keda-operator --since=2h 2>/dev/null | grep -iE 'error|vllm' | tail -50 > "$RUN-keda.log" || true

echo
"$PY" "$ROOT/loadtest/report.py" "$RUN-watch.csv" "$RUN-requests.csv" | tee "$RUN-report.txt"
echo
echo "Files: $RUN-{watch,requests}.csv, $RUN-{load,report}.txt, $RUN-{karpenter,keda}.log"
