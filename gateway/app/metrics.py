"""Prometheus metrics. Labels stay low-cardinality: backend, outcome, reason, client."""

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry()

REQUESTS = Counter(
    "gateway_requests_total",
    "Backend calls by backend and outcome (ok | error).",
    ["backend", "outcome"],
    registry=REGISTRY,
)
FALLBACKS = Counter(
    "gateway_fallbacks_total",
    "Requests served by the fallback backend, by why the primary failed.",
    ["from_backend", "to_backend", "reason"],
    registry=REGISTRY,
)
LATENCY = Histogram(
    "gateway_backend_latency_seconds",
    "Latency of successful backend calls.",
    ["backend"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64),
    registry=REGISTRY,
)
TOKENS = Counter(
    "gateway_tokens_total",
    "Tokens processed, by backend, direction (input | output) and client.",
    ["backend", "direction", "client"],
    registry=REGISTRY,
)
