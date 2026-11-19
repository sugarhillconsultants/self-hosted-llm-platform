import asyncio

import pytest

from app.providers.base import Message, ProviderError
from app.router import AllBackendsFailed, Router

from .conftest import FakeProvider

MSGS = [Message(role="user", content="hi")]


def run(router, **kw):
    return asyncio.run(router.complete(MSGS, max_tokens=16, temperature=0.0, client="t", **kw))


def test_primary_success_does_not_touch_fallback():
    primary, fallback = FakeProvider("self_hosted"), FakeProvider("anthropic")
    result = run(Router({"self_hosted": primary, "anthropic": fallback}, "self_hosted"))
    assert result.served_by == "self_hosted"
    assert result.fallback_reason is None
    assert fallback.calls == []


def test_non_retryable_error_does_not_fall_back():
    # A 400 from the primary would be a 400 from the fallback too; don't pay for it.
    primary = FakeProvider("self_hosted", error=ProviderError("upstream_4xx", "bad", retryable=False, status=400))
    fallback = FakeProvider("anthropic")
    router = Router({"self_hosted": primary, "anthropic": fallback}, "self_hosted")
    with pytest.raises(AllBackendsFailed) as exc:
        run(router)
    assert exc.value.status == 400
    assert fallback.calls == []


def test_fallback_disabled():
    primary = FakeProvider("self_hosted", error=ProviderError("timeout", "slow", retryable=True))
    fallback = FakeProvider("anthropic")
    router = Router({"self_hosted": primary, "anthropic": fallback}, "self_hosted", fallback_enabled=False)
    with pytest.raises(AllBackendsFailed) as exc:
        run(router)
    assert exc.value.status == 502
    assert fallback.calls == []


def test_anthropic_as_primary():
    primary, other = FakeProvider("anthropic"), FakeProvider("self_hosted")
    result = run(Router({"self_hosted": other, "anthropic": primary}, "anthropic"))
    assert result.served_by == "anthropic"
    assert other.calls == []


def test_unknown_primary_rejected():
    with pytest.raises(ValueError):
        Router({"self_hosted": FakeProvider("self_hosted")}, "anthropic")


def test_fallback_400_after_primary_timeout_is_a_gateway_fault():
    # Incident #2: the client got a 400 for a request that was fine; the 400
    # came from the fallback rejecting a parameter the gateway added.
    primary = FakeProvider("self_hosted", error=ProviderError("timeout", "slow", retryable=True))
    fallback = FakeProvider("anthropic", error=ProviderError("upstream_4xx", "bad param", retryable=False, status=400))
    with pytest.raises(AllBackendsFailed) as exc:
        run(Router({"self_hosted": primary, "anthropic": fallback}, "self_hosted"))
    assert exc.value.status == 502


def test_backend_failure_logs_full_message():
    import logging

    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("gateway")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        primary = FakeProvider("self_hosted", error=ProviderError(
            "upstream_4xx", "anthropic returned 400: `temperature` is deprecated", retryable=False, status=400))
        with pytest.raises(AllBackendsFailed):
            run(Router({"self_hosted": primary, "anthropic": FakeProvider("anthropic")}, "self_hosted"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    message = records[0].getMessage()
    assert "temperature` is deprecated" in message and "status=400" in message
