# Phase 0 evidence: local request path

**Gate (from `docs/BUILD_PLAN.md`):** a request through the gateway in kind
returns a real completion from the local model; with the model scaled to zero,
the same request returns a Claude API completion with `x-served-by: anthropic`.

Paste real output only. Note the date, your machine (e.g. Apple M-series,
Docker Desktop version), and anything that took more than one attempt (that
goes in `docs/incidents.md` too).

## Prerequisites

```bash
brew install kind kubectl jq      # plus Docker Desktop, running
export ANTHROPIC_API_KEY=sk-ant-... # optional; without it, step 2 returns 502
```

## Run

```bash
make test        # unit tests
make local-up    # kind cluster + gateway + local model
make smoke       # the gate
make local-down  # when finished
```

## Results

**Gate passed on 2026-11-19**, on the second attempt. The first run passed the
self-hosted half but the fallback failed (incidents #2 and #3); the run below
is after the fix in commit `2ef4d5c`.

- Date: 2026-11-19 (requests at 14:50:50Z and 14:50:51Z)
- Machine: MacBook Pro, Apple Silicon (`aarch64`), Docker Desktop engine 29.1.3, kind
- Gateway: built from commit `2ef4d5c`
- Local model: Qwen2.5-0.5B-Instruct (Q4_K_M GGUF) via llama.cpp server, CPU only
- Fallback model: `claude-haiku-5-5`

### 1. Self-hosted completion

```
== 1. Self-hosted model ==
2026-11-19T14:50:50Z
HTTP 200 in 0.247389s
x-served-by: self_hosted
{
  "id": "014d1b3361c84b4a8a78373e8e72bd2e",
  "content": "A Kubernetes readiness probe checks the readiness of a containerized application to ensure it is running and available before it is scheduled to start.",
  "model": "local-model",
  "served_by": "self_hosted",
  "usage": {
    "input_tokens": 41,
    "output_tokens": 27
  },
  "latency_ms": 217,
  "fallback_reason": null,
  "finish_reason": "stop"
}
```

The answer is served by the gateway, but it is wrong: readiness gates traffic,
not scheduling. That's expected from a 0.5B model, and it is exactly what the
Phase 5 eval gate exists to measure. Phase 0 tests the request path, not answer
quality.

### 2. Fallback with the model scaled to zero

```
== 2. Model scaled to zero (fallback) ==
deployment.apps/local-model scaled
pod/local-model-75c7764955-v9bkl condition met
2026-11-19T14:50:51Z
HTTP 200 in 3.077049s
x-served-by: anthropic
x-fallback-reason: connect_timeout
{
  "id": "f5b407eed79a4a1d803d624fed8f4bf2",
  "content": "A Kubernetes readiness probe checks whether a container is ready to accept traffic, and if it isn't, Kubernetes removes the pod from service endpoints until it passes again, without restarting the container.",
  "model": "claude-haiku-5-5",
  "served_by": "anthropic",
  "usage": {
    "input_tokens": 30,
    "output_tokens": 67
  },
  "latency_ms": 1070,
  "fallback_reason": "connect_timeout",
  "finish_reason": "end_turn"
}
-- gateway log for this request:
2026-11-19 14:50:53,437 WARNING gateway backend self_hosted failed after 2.00s: reason=connect_timeout status=None retryable=True: self_hosted connect timed out
2026-11-19 14:50:54,508 INFO gateway request f5b407eed79a4a1d803d624fed8f4bf2 client=local-dev served_by=anthropic latency_ms=1070 fallback=connect_timeout
```

### 3. Metrics after the run

```
gateway_requests_total{backend="self_hosted",outcome="ok"} 1.0
gateway_requests_total{backend="self_hosted",outcome="error"} 1.0
gateway_requests_total{backend="anthropic",outcome="ok"} 1.0
gateway_fallbacks_total{from_backend="self_hosted",reason="connect_timeout",to_backend="anthropic"} 1.0
```

### Timings

| What | Seconds | Source |
|---|---|---|
| Self-hosted request, end to end (curl) | 0.25 | `time_total` |
| Self-hosted backend call (`latency_ms`) | 0.22 | response body |
| Fallback request, end to end (curl) | 3.08 | `time_total` |
| Time lost on the failed self-hosted attempt | 2.00 | gateway log (connect timeout) |
| Claude API call (`latency_ms`) | 1.07 | response body |
| Fallback request before the fix (first run) | ~30, then HTTP 400 | incidents #2 and #3 |

Not recorded on this run: `make local-up` duration and model pod start-to-ready
time. Capture them on the next fresh `make local-up`.

**Gap this run exposed:** `latency_ms` and the `gateway_backend_latency_seconds`
metric count only the backend that succeeded. The 2.00 s spent on the failed
attempt appears in neither, so a dashboard built on them would show fallback
requests as faster than callers experience (1.07 s vs 3.08 s). Tracked in the
README's "What I'd add next."

## Pre-deployment checks already done (in a cloud sandbox, not on this machine)

- 41 unit tests passing (`make test`).
- Gateway run under uvicorn against a fake OpenAI-compatible server: 200 with
  `x-served-by: self_hosted`; with the server stopped and no API key, 502 listing
  `self_hosted: connect_error` and `anthropic: not_configured`; metrics counted
  both.
- Local overlay rendered with kustomize 5.5.0 and validated with kubeconform
  against Kubernetes 1.31 schemas: 6 resources, 0 invalid.
- Superseded by the Mac run above, which built the image and ran it in a real kind cluster.
