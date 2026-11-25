#!/usr/bin/env bash
# Every 10 s, one CSV row of what the autoscaling stack is doing:
# gateway demand, KEDA's desired replicas, vLLM ready replicas, GPU
# NodeClaims (and how many are being deleted), GPU nodes Ready, vLLM CPU.
#   loadtest/watch.sh out.csv [gateway_url]      (stop with Ctrl-C / kill)
set -uo pipefail
OUT=${1:?usage: watch.sh out.csv [gateway_url]}
GW=${2:-http://localhost:18080}
NS=llm

echo "time_utc,epoch,demand,wanting_now,self_hosted_inflight,fallbacks_recent,hpa_desired,vllm_spec,vllm_ready,gpu_nodeclaims,gpu_nodeclaims_deleting,gpu_nodes_ready,capacity_types,vllm_cpu_m" > "$OUT"
while :; do
  now=$(date +%s)
  s=$(curl -s -m 3 "$GW/scaling" || true)
  num() { jq -r "$1 // \"\"" <<<"$s" 2>/dev/null; }
  claims=$(kubectl get nodeclaims -l karpenter.sh/nodepool=gpu -o json 2>/dev/null || echo '{"items":[]}')
  nc=$(jq '.items | length' <<<"$claims")
  nd=$(jq '[.items[] | select(.metadata.deletionTimestamp)] | length' <<<"$claims")
  ct=$(jq -r '[.items[].metadata.labels["karpenter.sh/capacity-type"] // "?"] | join("+")' <<<"$claims")
  ready_nodes=$(kubectl get nodes -l karpenter.sh/nodepool=gpu -o json 2>/dev/null \
    | jq '[.items[] | select(any(.status.conditions[]; .type=="Ready" and .status=="True"))] | length')
  spec=$(kubectl -n $NS get deploy vllm -o jsonpath='{.spec.replicas}' 2>/dev/null)
  ready=$(kubectl -n $NS get deploy vllm -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
  hpa=$(kubectl -n $NS get hpa keda-hpa-vllm -o jsonpath='{.status.desiredReplicas}' 2>/dev/null)
  cpu=$(kubectl -n $NS top pod -l app=vllm --no-headers 2>/dev/null | awk '{gsub("m","",$2); s+=$2} END {if (NR) print s}')
  echo "$(date -u +%H:%M:%SZ),$now,$(num .self_hosted_demand),$(num .wanting_now),$(num .self_hosted_inflight),$(num .fallbacks_recent),${hpa:-},${spec:-},${ready:-0},$nc,$nd,${ready_nodes:-0},$ct,${cpu:-}" >> "$OUT"
  sleep $(( 10 - ($(date +%s) - now) > 0 ? 10 - ($(date +%s) - now) : 1 ))
done
