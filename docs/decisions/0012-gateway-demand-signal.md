# ADR 0012: The gateway reports demand; KEDA reads it with metrics-api

- **Status:** Accepted
- **Date:** 2026-11-25

## Context
Scaling from zero needs a signal that exists while the workload doesn't.
Every request already passes through the gateway, which knows which ones
wanted the self-hosted model and how many are in flight.

## Options considered
- Prometheus server scraping the gateway, KEDA's prometheus scaler: standard,
  but a stateful component the cluster doesn't otherwise need yet (Phase 6).
- KEDA's HTTP add-on (an interceptor proxy that holds requests during scale
  from zero): another hop in the request path, and holding requests is the
  "wait" policy, which isn't the default (ADR 0004).
- **Gateway `/scaling` JSON + KEDA `metrics-api` scaler** with
  `aggregateFromKubeServiceEndpoints: true` and `aggregationType: sum`, so
  KEDA queries every gateway pod and adds them up.

## Decision
The gateway exposes `GET /scaling` (cluster-internal, counts only) with
`self_hosted_demand` = peak, over the last 120 s, of requests in flight at
the gateway that want the self-hosted model, whichever backend answers them.
The same value is the `gateway_self_hosted_demand` Prometheus gauge.

**Concurrency, not request counts.** A first version counted requests that
had fallen back. Fallbacks are fast, so in a local test 3 clients produced 69
in a 5-second window, which KEDA would have turned into the maximum replica
count. Caught in the local end-to-end run before reaching AWS; the tests now
assert that 50 fallbacks are not 50 replicas' worth of demand.

## Consequences
- No Prometheus server in Phase 3; one is added in Phase 6 for dashboards,
  and could replace this path then without changing the gateway.
- The peak-over-window keeps demand steady through closed-loop clients'
  think time, and delays scale-down by up to 120 s after the last request,
  on top of KEDA's cooldown.
