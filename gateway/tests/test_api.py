import time

from app.auth import issue_token
from app.metrics import REGISTRY
from app.providers.base import ProviderError

from .conftest import FakeProvider, auth_header

CHAT = {"messages": [{"role": "user", "content": "What is KEDA?"}]}


def test_health_needs_no_auth(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    assert client.get("/health").json() == {"status": "ok"}


def test_token_rejects_wrong_secret(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    resp = client.post("/token", json={"client_id": "rag-platform", "client_secret": "nope"})
    assert resp.status_code == 401


def test_token_rejects_unknown_client(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    resp = client.post("/token", json={"client_id": "stranger", "client_secret": "s3cret"})
    assert resp.status_code == 401


def test_chat_requires_token(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    assert client.post("/v1/chat", json=CHAT).status_code == 401


def test_chat_rejects_expired_token(make_client, settings):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    old = issue_token(settings, "rag-platform", now=time.time() - settings.jwt_ttl_s - 10)
    resp = client.post("/v1/chat", json=CHAT, headers={"Authorization": f"Bearer {old}"})
    assert resp.status_code == 401


def test_chat_served_by_self_hosted(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    resp = client.post("/v1/chat", json=CHAT, headers=auth_header(client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["served_by"] == "self_hosted"
    assert body["content"] == "answer from self_hosted"
    assert body["usage"] == {"input_tokens": 7, "output_tokens": 3}
    assert resp.headers["x-served-by"] == "self_hosted"
    assert "x-fallback-reason" not in resp.headers


def test_chat_falls_back_when_self_hosted_down(make_client):
    down = FakeProvider("self_hosted", error=ProviderError("connect_error", "refused", retryable=True))
    client = make_client(down, FakeProvider("anthropic"))
    resp = client.post("/v1/chat", json=CHAT, headers=auth_header(client))
    assert resp.status_code == 200
    assert resp.json()["served_by"] == "anthropic"
    assert resp.headers["x-served-by"] == "anthropic"
    assert resp.headers["x-fallback-reason"] == "connect_error"


def test_chat_returns_502_with_reasons_when_everything_fails(make_client):
    client = make_client(
        FakeProvider("self_hosted", error=ProviderError("timeout", "slow", retryable=True)),
        FakeProvider("anthropic", error=ProviderError("not_configured", "no key", retryable=False)),
    )
    resp = client.post("/v1/chat", json=CHAT, headers=auth_header(client))
    assert resp.status_code == 502
    assert resp.json()["errors"] == [
        {"backend": "self_hosted", "reason": "timeout"},
        {"backend": "anthropic", "reason": "not_configured"},
    ]


def test_explicit_backend_skips_fallback(make_client):
    anthropic = FakeProvider("anthropic")
    client = make_client(
        FakeProvider("self_hosted", error=ProviderError("timeout", "slow", retryable=True)), anthropic
    )
    resp = client.post("/v1/chat", json={**CHAT, "backend": "self_hosted"}, headers=auth_header(client))
    assert resp.status_code == 502
    assert anthropic.calls == []


def test_max_tokens_limit_enforced(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    resp = client.post("/v1/chat", json={**CHAT, "max_tokens": 4096}, headers=auth_header(client))
    assert resp.status_code == 422


def test_invalid_role_rejected(make_client):
    client = make_client(FakeProvider("self_hosted"), FakeProvider("anthropic"))
    bad = {"messages": [{"role": "tool", "content": "hi"}]}
    assert client.post("/v1/chat", json=bad, headers=auth_header(client)).status_code == 422


def test_metrics_count_fallbacks_and_tokens(make_client):
    before = REGISTRY.get_sample_value(
        "gateway_fallbacks_total",
        {"from_backend": "self_hosted", "to_backend": "anthropic", "reason": "upstream_5xx"},
    ) or 0
    down = FakeProvider("self_hosted", error=ProviderError("upstream_5xx", "503", retryable=True, status=503))
    client = make_client(down, FakeProvider("anthropic"))
    client.post("/v1/chat", json=CHAT, headers=auth_header(client, "loadtest", "other"))

    after = REGISTRY.get_sample_value(
        "gateway_fallbacks_total",
        {"from_backend": "self_hosted", "to_backend": "anthropic", "reason": "upstream_5xx"},
    )
    assert after == before + 1
    assert REGISTRY.get_sample_value(
        "gateway_tokens_total", {"backend": "anthropic", "direction": "output", "client": "loadtest"}
    ) >= 3
    text = client.get("/metrics").text
    assert "gateway_requests_total" in text


def test_lifespan_closes_providers(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.router import Router

    a, b = FakeProvider("self_hosted"), FakeProvider("anthropic")
    with TestClient(create_app(settings=settings, router=Router({"self_hosted": a, "anthropic": b}, "self_hosted"))):
        pass
    assert a.closed and b.closed
