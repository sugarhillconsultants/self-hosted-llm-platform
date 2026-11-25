"""Prometheus metrics. Labels stay low-cardinality: backend, outcome, reason, client."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

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
REQUEST_DURATION = Histogram(
    "gateway_request_duration_seconds",
    "What the caller waited, including failed attempts before a fallback.",
    ["served_by", "fallback"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 300, 600),
    registry=REGISTRY,
)
COLD_START_WAITS = Counter(
    "gateway_cold_start_waits_total",
    "Retries while waiting for the self-hosted backend to start (wait policy).",
    registry=REGISTRY,
)
SELF_HOSTED_DEMAND = Gauge(
    "gateway_self_hosted_demand",
    "In-flight self-hosted requests plus recent ones that fell back: KEDA's scaling signal.",
    registry=REGISTRY,
)
SELF_HOSTED_INFLIGHT = Gauge(
    "gateway_self_hosted_inflight",
    "Requests currently being served by, or waiting for, the self-hosted backend.",
    registry=REGISTRY,
)


def bind_demand(tracker) -> None:
    """Make the demand gauges read the tracker live at scrape time."""
    SELF_HOSTED_DEMAND.set_function(lambda: tracker.snapshot()["self_hosted_demand"])
    SELF_HOSTED_INFLIGHT.set_function(lambda: tracker.inflight_count)
