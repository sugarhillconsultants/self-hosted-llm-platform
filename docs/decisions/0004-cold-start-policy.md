# ADR 0004: During a cold start, answer from the Claude API by default

- **Status:** Accepted (both options measured in Phase 3)
- **Date:** 2026-11-25

## Context
With vLLM scaled to zero, the first self-hosted answer arrives a full cold
start later: 7 m 21 s in Phase 2 (node, 10 GB image, 15 GB of weights, load).
Something has to happen to the requests that arrive in that window.

## Options considered
- **fallback:** answer from the Claude API immediately; the request still
  counts as self-hosted demand, so vLLM starts. Users see normal latency;
  the cost is API tokens during the cold start.
- **wait:** hold the request, retrying the self-hosted backend every 5 s,
  up to `SELF_HOSTED_WAIT_S` (600 s), then fall back. No API cost; the
  first users wait minutes.
- **A minimum of one replica during working hours** (KEDA cron trigger):
  no cold start in the day, a GPU billing all day. A later option once usage
  patterns exist.

## Decision
`COLD_START_POLICY=fallback` by default; `wait` is one setting away
(`scripts/deploy-gateway.sh --policy wait`). Only "not running" failures
(`connect_error`, `connect_timeout`) are waited out; a running-but-slow
vLLM (read timeout) falls back at once, because waiting for it to "start"
would be wrong.

## Consequences
- With fallback, the cold start costs API tokens instead of user time.
  Phase 3 records how many requests the API served during each cold start.
- With wait, first-request latency ≈ the cold start, which is acceptable
  only for batch or offline callers that set long timeouts.
- An explicit `"backend": "self_hosted"` request (for example an eval run)
  never falls back, but does wait under the wait policy.
