#!/usr/bin/env bash
# The Phase 0 gate, end to end. Paste its output into docs/evidence/phase-0.md.
#   1. a real completion from the local model, through the gateway
#   2. the same call with the model scaled to zero -> served by the Claude API
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
source "$ROOT/local/.env.local"
URL="${GATEWAY_URL:-http://localhost:8000}"
command -v jq >/dev/null || { echo "missing: jq"; exit 1; }

TOKEN=$(curl -sf "$URL/token" -H 'content-type: application/json' \
  -d "{\"client_id\":\"$CLIENT_ID\",\"client_secret\":\"$CLIENT_SECRET\"}" | jq -r .access_token)

ask() {
  curl -s -D /tmp/gw-headers -o /tmp/gw-body -w '%{http_code} %{time_total}' "$URL/v1/chat" \
    -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
    -d '{"messages":[{"role":"user","content":"In one sentence, what does a Kubernetes readiness probe do?"}],"max_tokens":80}'
}

echo "== 1. Self-hosted model =="
date -u +%FT%TZ
read -r code secs <<< "$(ask)"; echo "HTTP $code in ${secs}s"
grep -iE '^x-(served-by|fallback-reason)' /tmp/gw-headers || true
jq . /tmp/gw-body

echo
echo "== 2. Model scaled to zero (fallback) =="
kubectl -n llm scale deployment/local-model --replicas=0
kubectl -n llm wait --for=delete pod -l app=local-model --timeout=60s || true
date -u +%FT%TZ
read -r code secs <<< "$(ask)"; echo "HTTP $code in ${secs}s (fallback should take ~2s at most)"
grep -iE '^x-(served-by|fallback-reason)' /tmp/gw-headers || true
jq . /tmp/gw-body
echo "-- gateway log for this request:"
kubectl -n llm logs deploy/gateway --since=60s | grep -E 'WARNING|served_by=anthropic' | tail -3

echo
echo "== Restoring the model =="
kubectl -n llm scale deployment/local-model --replicas=1
kubectl -n llm rollout status deployment/local-model --timeout=600s

echo
echo "== Gateway metrics =="
kubectl -n llm exec deploy/gateway -- python -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/metrics').read().decode())" \
  | grep -E '^gateway_(requests|fallbacks)_total'
