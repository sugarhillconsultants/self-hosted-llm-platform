"""Phase 3: demand tracking and the cold-start policy (ADR 0004, ADR 0012)."""

import asyncio

import pytest

from app import metrics
from app.config import ConfigError, Settings
from app.demand import DemandTracker
from app.providers.base import Completion, Message, ProviderError, Usage
from app.router import AllBackendsFailed, Router

from .conftest import FakeProvider, auth_header

MSGS = [Message(role="user", content="hi")]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def run(router, **kw):
    return asyncio.run(router.complete(MSGS, max_tokens=16, temperature=0.0, client="t", **kw))


class FlakyProvider:
    """Fails with `reason` for the first `failures` calls, then answers."""

    def __init__(self, name, failures, reason="connect_error"):
        self.name, self.failures, self.reason, self.calls = name, failures, reason, 0

    async def complete(self, messages, *, max_tokens, temperature):
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError(self.reason, "not up yet", retryable=True)
        return Completion("finally", "m", Usage(input_tokens=1, output_tokens=1), "stop")

    async def aclose(self):
        pass


# --- DemandTracker -------------------------------------------------------------

def test_demand_is_peak_concurrency_held_for_the_window():
    clock = Clock()
    d = DemandTracker(window_s=120, clock=clock)
    cms = [d.wanting() for _ in range(3)]
    for cm in cms:
        cm.__enter__()
    assert d.snapshot()["self_hosted_demand"] == 3
    clock.t += 10
    for cm in cms:
        cm.__exit__(None, None, None)
    assert d.snapshot()["wanting_now"] == 0
    assert d.snapshot()["self_hosted_demand"] == 3   # held through think-time gaps
    clock.t += 119
    assert d.snapshot()["self_hosted_demand"] == 3   # 119 s after the drop
    clock.t += 2
    assert d.snapshot()["self_hosted_demand"] == 0   # window has passed


def test_a_level_that_began_before_the_window_still_counts():
    clock = Clock()
    d = DemandTracker(window_s=60, clock=clock)
    cm = d.wanting()
    cm.__enter__()
    clock.t += 300                # one request held for 5 minutes (e.g. waiting)
    assert d.snapshot()["self_hosted_demand"] == 1
    cm.__exit__(None, None, None)
    clock.t += 30
    assert d.snapshot()["self_hosted_demand"] == 1
    clock.t += 31
    assert d.snapshot()["self_hosted_demand"] == 0


def test_fallback_counter_is_informational_and_expires():
    clock = Clock()
    d = DemandTracker(window_s=60, clock=clock)
    for _ in range(50):
        d.missed()                # 50 fast fallbacks...
    assert d.snapshot()["fallbacks_recent"] == 50
    assert d.snapshot()["self_hosted_demand"] == 0   # ...are not 50 replicas of demand
    clock.t += 61
    assert d.snapshot()["fallbacks_recent"] == 0


def test_inflight_releases_even_on_error():
    d = DemandTracker()
    with pytest.raises(RuntimeError):
        with d.inflight():
            raise RuntimeError
    assert d.inflight_count == 0


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        DemandTracker(window_s=0)


# --- Router: demand -----------------------------------------------------------------

def test_request_is_inflight_while_self_hosted_serves_it():
    demand = DemandTracker()
    seen = {}

    class Probe(FakeProvider):
        async def complete(self, messages, *, max_tokens, temperature):
            seen["inflight"] = demand.inflight_count
            return await super().complete(messages, max_tokens=max_tokens, temperature=temperature)

    router = Router({"self_hosted": Probe("self_hosted"), "anthropic": FakeProvider("anthropic")},
                    "self_hosted", demand=demand)
    run(router)
    assert seen["inflight"] == 1
    assert demand.snapshot()["self_hosted_inflight"] == 0
    assert demand.snapshot()["self_hosted_demand"] == 1  # peak held for the window


def test_fallback_policy_records_missed_demand_and_serves_from_claude():
    # The scale-from-zero case: vLLM is at 0 replicas, the gateway answers via
    # Claude, and still reports demand so KEDA starts vLLM.
    demand = DemandTracker()
    down = FakeProvider("self_hosted", error=ProviderError("connect_error", "refused", retryable=True))
    router = Router({"self_hosted": down, "anthropic": FakeProvider("anthropic")}, "self_hosted", demand=demand)
    result = run(router)
    assert result.served_by == "anthropic"
    snap = demand.snapshot()
    assert snap["self_hosted_demand"] == 1 and snap["fallbacks_recent"] == 1
    assert result.total_s >= result.latency_s


def test_non_retryable_failure_is_not_counted_as_a_fallback():
    demand = DemandTracker()
    bad = FakeProvider("self_hosted", error=ProviderError("upstream_4xx", "bad", retryable=False, status=400))
    with pytest.raises(AllBackendsFailed):
        run(Router({"self_hosted": bad, "anthropic": FakeProvider("anthropic")}, "self_hosted", demand=demand))
    assert demand.snapshot()["fallbacks_recent"] == 0
    assert demand.snapshot()["wanting_now"] == 0


def test_claude_only_requests_are_not_self_hosted_demand():
    demand = DemandTracker()
    router = Router({"self_hosted": FakeProvider("self_hosted"), "anthropic": FakeProvider("anthropic")},
                    "self_hosted", demand=demand)
    run(router, choice="anthropic")
    assert demand.snapshot()["self_hosted_demand"] == 0


# --- Router: wait policy ------------------------------------------------------------

def test_wait_policy_retries_until_self_hosted_is_up():
    before = metrics.REGISTRY.get_sample_value("gateway_cold_start_waits_total") or 0
    flaky, claude = FlakyProvider("self_hosted", failures=2), FakeProvider("anthropic")
    router = Router({"self_hosted": flaky, "anthropic": claude}, "self_hosted",
                    cold_start_policy="wait", wait_s=5, retry_interval_s=0.01)
    result = run(router)
    assert result.served_by == "self_hosted" and flaky.calls == 3
    assert claude.calls == []
    assert metrics.REGISTRY.get_sample_value("gateway_cold_start_waits_total") == before + 2


def test_wait_policy_falls_back_after_the_deadline():
    demand = DemandTracker()
    never = FlakyProvider("self_hosted", failures=10**6)
    router = Router({"self_hosted": never, "anthropic": FakeProvider("anthropic")}, "self_hosted",
                    demand=demand, cold_start_policy="wait", wait_s=0.05, retry_interval_s=0.01)
    result = run(router)
    assert result.served_by == "anthropic"
    assert 2 <= never.calls <= 6
    assert demand.snapshot()["fallbacks_recent"] == 1


def test_wait_policy_does_not_wait_on_a_running_backend_that_is_slow():
    # A read timeout means vLLM is up but slow; waiting for it to "start" is wrong.
    slow = FlakyProvider("self_hosted", failures=10**6, reason="timeout")
    router = Router({"self_hosted": slow, "anthropic": FakeProvider("anthropic")}, "self_hosted",
                    cold_start_policy="wait", wait_s=5, retry_interval_s=0.01)
    assert run(router).served_by == "anthropic"
    assert slow.calls == 1


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        Router({"self_hosted": FakeProvider("self_hosted")}, "self_hosted", cold_start_policy="maybe")


def test_config_policy_settings():
    base = {"JWT_SECRET": "x" * 32, "CLIENTS": "a:b"}
    s = Settings.from_env({**base, "COLD_START_POLICY": "wait", "SELF_HOSTED_WAIT_S": "30", "DEMAND_WINDOW_S": "90"})
    assert (s.cold_start_policy, s.self_hosted_wait_s, s.demand_window_s) == ("wait", 30.0, 90.0)
    assert Settings.from_env(base).cold_start_policy == "fallback"
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "COLD_START_POLICY": "sometimes"})


# --- API ------------------------------------------------------------------------------

def test_scaling_endpoint_reports_concurrency_not_request_count(make_client):
    down = FakeProvider("self_hosted", error=ProviderError("connect_timeout", "slow", retryable=True))
    client = make_client(down, FakeProvider("anthropic"))
    chat = {"messages": [{"role": "user", "content": "hi"}]}
    for _ in range(3):
        assert client.post("/v1/chat", json=chat, headers=auth_header(client)).status_code == 200
    body = client.get("/scaling").json()
    # Three requests one after another: concurrency 1, three fallbacks.
    assert body["self_hosted_demand"] == 1 and body["fallbacks_recent"] == 3
    assert "gateway_self_hosted_demand 1.0" in client.get("/metrics").text


def test_concurrent_requests_set_the_demand():
    demand = DemandTracker()

    class Slow(FakeProvider):
        async def complete(self, messages, *, max_tokens, temperature):
            await asyncio.sleep(0.05)
            return await super().complete(messages, max_tokens=max_tokens, temperature=temperature)

    router = Router({"self_hosted": Slow("self_hosted"), "anthropic": FakeProvider("anthropic")},
                    "self_hosted", demand=demand)

    async def burst():
        await asyncio.gather(*(router.complete(MSGS, max_tokens=8, temperature=0, client="t") for _ in range(5)))

    asyncio.run(burst())
    assert demand.snapshot()["self_hosted_demand"] == 5
    assert demand.snapshot()["wanting_now"] == 0


def test_response_reports_total_latency(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    body = client.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]},
                       headers=auth_header(client)).json()
    assert body["total_latency_ms"] >= body["latency_ms"]
