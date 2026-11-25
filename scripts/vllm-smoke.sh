#!/usr/bin/env bash
# The Phase 2 gate, end to end, with a timeline. Paste the output into
# docs/evidence/phase-2.md.
#   1. deploy vLLM: Karpenter launches a GPU node for it (from zero)
#   2. /v1/models, one completion, single-stream and 4-way throughput,
#      GPU and driver details
#   3. scale vLLM to zero: Karpenter removes the GPU node
# --keep skips step 3 and leaves the GPU node running (and billing).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NS=llm
PORT=18000
KEEP=0; [[ "${1:-}" == "--keep" ]] && KEEP=1

for tool in kubectl jq curl; do command -v "$tool" >/dev/null || { echo "missing: $tool"; exit 1; }; done
if grep -q 'MODEL_REVISION=SET-ME' "$ROOT/k8s/vllm/kustomization.yaml"; then
  echo "Pin the model first: ./scripts/pin-model.sh"; exit 1
fi
kubectl get nodepool gpu >/dev/null 2>&1 || { echo "No gpu NodePool: run ./scripts/k8s-platform.sh up"; exit 1; }
if kubectl -n "$NS" get scaledobject vllm >/dev/null 2>&1; then
  echo "KEDA controls vLLM's replicas (ScaledObject vllm), and this script scales it by hand."
  echo "Use ./scripts/phase3-run.sh, or remove it first: kubectl -n $NS delete scaledobject vllm"
  exit 1
fi

T0=$(date +%s)
ts() { echo "[$(date -u +%H:%M:%SZ) +$(( $(date +%s) - T0 ))s] $*"; }

ts "Deploying vLLM"
kubectl apply -k "$ROOT/k8s/vllm" >/dev/null
kubectl -n "$NS" scale deployment/vllm --replicas=1 >/dev/null

seen_claim=0; seen_node=0; seen_sched=0; node=""
while :; do
  if (( ! seen_claim )); then
    claim=$(kubectl get nodeclaims -l karpenter.sh/nodepool=gpu -o json | jq -r '.items[0] // empty')
    if [[ -n "$claim" ]]; then
      seen_claim=1
      ts "NodeClaim created: $(jq -r '.metadata.name' <<<"$claim")"
    fi
  fi
  if (( seen_claim && ! seen_node )); then
    node=$(kubectl get nodes -l karpenter.sh/nodepool=gpu -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [[ -n "$node" ]] && kubectl get node "$node" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' | grep -q True; then
      seen_node=1
      ts "GPU node Ready: $node, $(kubectl get node "$node" -o jsonpath='{.metadata.labels.node\.kubernetes\.io/instance-type} {.metadata.labels.karpenter\.sh/capacity-type} {.metadata.labels.topology\.kubernetes\.io/zone}')"
    fi
  fi
  pod=$(kubectl -n "$NS" get pod -l app=vllm -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if (( ! seen_sched )) && [[ -n "$pod" ]] && [[ -n "$(kubectl -n "$NS" get pod "$pod" -o jsonpath='{.spec.nodeName}')" ]]; then
    seen_sched=1; ts "Pod scheduled: $pod"
  fi
  if [[ -n "$pod" ]] && [[ "$(kubectl -n "$NS" get pod "$pod" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')" == "True" ]]; then
    ts "vLLM Ready (model loaded)"; break
  fi
  # Fail fast on a crash loop instead of waiting out the timeout with a GPU
  # billing (incident #8 waited 30 minutes through 8 identical crashes).
  restarts=$(kubectl -n "$NS" get pod "$pod" -o jsonpath='{.status.containerStatuses[0].restartCount}' 2>/dev/null)
  if [[ "${restarts:-0}" -ge 2 ]]; then
    ts "vLLM crashed $restarts times. Last error:"
    kubectl -n "$NS" logs "$pod" --previous --tail=200 2>/dev/null \
      | grep -E 'Error|ERROR|raise|Exception' | grep -v 'File "' | tail -8 | sed 's/^/  /'
    echo "Scale down to stop the GPU billing: kubectl -n $NS scale deployment/vllm --replicas=0"
    exit 1
  fi
  if (( $(date +%s) - T0 > 1800 )); then
    ts "Gave up after 30 minutes. Diagnose with:"
    echo "  kubectl -n $NS describe pod $pod | tail -30"
    echo "  kubectl -n $NS logs $pod --tail=50"
    echo "  kubectl get nodeclaims -o wide; kubectl -n kube-system logs deploy/karpenter --tail=50"
    exit 1
  fi
  sleep 5
done

echo
echo "-- Image pull and container start (pod events):"
kubectl -n "$NS" get events --field-selector "involvedObject.name=$pod" -o json \
  | jq -r '.items[] | select(.reason=="Pulled" or .reason=="Started") | "  \(.reason): \(.message)"'
echo "-- GPU:"
kubectl -n "$NS" exec "$pod" -- nvidia-smi --query-gpu=name,driver_version,memory.used,memory.total --format=csv,noheader \
  | sed 's/^/  /'

kubectl -n "$NS" port-forward svc/vllm "$PORT:8000" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null' EXIT
sleep 3
API="http://localhost:$PORT"
MODEL=$(curl -sf "$API/v1/models" | jq -r '.data[0].id')

echo
echo "== /v1/models"
curl -sf "$API/v1/models" | jq -c '.data[] | {id, root, max_model_len}'

now() { perl -MTime::HiRes=time -e 'printf "%.3f\n", time'; }
calc() { awk "BEGIN { printf \"%.1f\", $1 }"; }

chat() { # $1 prompt, $2 max_tokens -> "elapsed_s completion_tokens content"
  local body out resp secs
  body=$(jq -nc --arg m "$MODEL" --arg p "$1" --argjson n "$2" \
    '{model:$m, messages:[{role:"user",content:$p}], max_tokens:$n, temperature:0}')
  # curl's own timer: portable, and excludes shell overhead.
  out=$(curl -sf -w '\n%{time_total}' "$API/v1/chat/completions" -H 'content-type: application/json' -d "$body")
  secs=${out##*$'\n'}
  resp=${out%$'\n'*}
  echo "$secs $(jq -r '.usage.completion_tokens' <<<"$resp") $(jq -c '.choices[0].message.content' <<<"$resp")"
}

echo
echo "== One completion"
read -r secs toks text <<<"$(chat 'In one sentence, what does a Kubernetes readiness probe do?' 80)"
echo "  ${secs}s, $toks tokens: $text"

echo
echo "== Single-stream throughput (512 tokens, temperature 0)"
read -r secs toks _ <<<"$(chat 'Explain, in detail and with examples, how a GPU executes a transformer forward pass.' 512)"
echo "  $toks tokens in ${secs}s = $(calc "$toks / $secs") tokens/s (includes prefill)"

echo
echo "== 4 concurrent requests (batching)"
export -f chat; export API MODEL
start=$(now)
total=$(seq 1 4 | xargs -P4 -I{} bash -c "chat 'Explain topic {} of distributed systems in depth.' 512" | awk '{s+=$2} END {print s}')
wall=$(calc "$(now) - $start")
echo "  $total tokens in ${wall}s = $(calc "$total / $wall") tokens/s aggregate"

echo
echo "== vLLM metrics"
curl -sf "$API/metrics" | grep -E '^vllm:(prompt_tokens_total|generation_tokens_total|kv_cache_usage_perc|gpu_cache_usage_perc)' | sed 's/^/  /'

if (( KEEP )); then
  echo; ts "--keep: GPU node left running (and billing). Scale down later with:"
  echo "  kubectl -n $NS scale deployment/vllm --replicas=0"
  exit 0
fi

echo
T0=$(date +%s)
ts "Scaling vLLM to zero"
kubectl -n "$NS" scale deployment/vllm --replicas=0 >/dev/null
while [[ -n "$(kubectl get nodeclaims -l karpenter.sh/nodepool=gpu -o name 2>/dev/null)" ]]; do
  if (( $(date +%s) - T0 > 900 )); then ts "GPU node still present after 15 minutes: check kubectl get nodeclaims"; exit 1; fi
  sleep 10
done
ts "GPU node removed by Karpenter"
