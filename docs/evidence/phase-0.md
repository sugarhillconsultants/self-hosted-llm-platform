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

- Date:
- Machine:
- Gateway image tag:
- Local model: Qwen2.5-0.5B-Instruct (Q4_K_M GGUF) via llama.cpp server

### 1. Self-hosted completion

```
<paste section 1 of smoke-test output>
```

### 2. Fallback with the model scaled to zero

```
<paste section 2 of smoke-test output>
```

### 3. Metrics after the run

```
<paste the gateway_requests_total / gateway_fallbacks_total lines>
```

### Timings worth recording

| What | Seconds |
|---|---|
| `make local-up`, first run (includes model download) | |
| `make local-up`, second run | |
| Model pod start to ready (cached weights) | |
| Self-hosted request latency (`latency_ms`) | |
| Fallback request latency (`latency_ms`) | |

## Pre-deployment checks already done (in a cloud sandbox, not on this machine)

- 41 unit tests passing (`make test`).
- Gateway run under uvicorn against a fake OpenAI-compatible server: 200 with
  `x-served-by: self_hosted`; with the server stopped and no API key, 502 listing
  `self_hosted: connect_error` and `anthropic: not_configured`; metrics counted
  both.
- Local overlay rendered with kustomize 5.5.0 and validated with kubeconform
  against Kubernetes 1.31 schemas: 6 resources, 0 invalid.
- Not yet done: building the Docker image, and anything in a real kind cluster.
