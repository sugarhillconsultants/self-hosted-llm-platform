from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.base import Completion, Message, ProviderError, Usage
from app.router import Router

JWT_SECRET = "test-secret-that-is-at-least-32-characters-long"


class FakeProvider:
    """A backend that returns a canned answer or raises a given ProviderError."""

    def __init__(self, name: str, *, error: ProviderError | None = None, content: str | None = None):
        self.name = name
        self.error = error
        self.content = content or f"answer from {name}"
        self.calls: list[list[Message]] = []
        self.closed = False

    async def complete(self, messages, *, max_tokens, temperature):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return Completion(self.content, f"{self.name}-model", Usage(input_tokens=7, output_tokens=3), "stop")

    async def aclose(self):
        self.closed = True


@pytest.fixture
def settings() -> Settings:
    return Settings.from_env(
        {"JWT_SECRET": JWT_SECRET, "CLIENTS": "rag-platform:s3cret,loadtest:other", "MAX_TOKENS_LIMIT": "512"}
    )


@pytest.fixture
def make_client(settings):
    """Build a TestClient around a router with the given fake providers.

    Used as a context manager so FastAPI's lifespan actually runs
    (log-anomaly-platform incident #6: without it, startup never happened).
    """
    clients = []

    def _make(self_hosted: FakeProvider, anthropic: FakeProvider, *, fallback_enabled: bool = True):
        router = Router(
            {"self_hosted": self_hosted, "anthropic": anthropic},
            "self_hosted",
            fallback_enabled=fallback_enabled,
        )
        client = TestClient(create_app(settings=settings, router=router))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def auth_header(client: TestClient, client_id: str = "rag-platform", secret: str = "s3cret") -> dict:
    resp = client.post("/token", json={"client_id": client_id, "client_secret": secret})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
