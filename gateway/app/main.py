"""LLM gateway: one authenticated chat endpoint in front of several backends."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import metrics
from .auth import current_client, issue_token, verify_client
from .config import Settings
from .providers.anthropic import AnthropicProvider
from .providers.base import Message, Usage
from .providers.openai_compat import OpenAICompatProvider
from .router import AllBackendsFailed, BackendChoice, Router

log = logging.getLogger("gateway")


# Request/response models live at module level on purpose: with postponed
# annotations, FastAPI cannot resolve classes defined inside create_app() and
# silently treats the body as a missing query parameter (found by the tests).
class TokenRequest(BaseModel):
    client_id: str
    client_secret: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    max_tokens: int = Field(256, ge=1)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    backend: BackendChoice = "auto"


class ChatResponse(BaseModel):
    id: str
    content: str
    model: str
    served_by: str
    usage: Usage
    latency_ms: int
    fallback_reason: str | None = None
    finish_reason: str | None = None


def build_router(settings: Settings) -> Router:
    providers = {
        "self_hosted": OpenAICompatProvider(
            settings.self_hosted_url,
            settings.self_hosted_model,
            timeout_s=settings.self_hosted_timeout_s,
        ),
        "anthropic": AnthropicProvider(
            settings.anthropic_api_key,
            settings.anthropic_model,
            timeout_s=settings.anthropic_timeout_s,
            base_url=settings.anthropic_url,
        ),
    }
    return Router(providers, settings.primary_backend, fallback_enabled=settings.fallback_enabled)


def create_app(settings: Settings | None = None, router: Router | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Uvicorn configures only its own loggers; without this, the gateway's
        # per-request INFO lines are silently dropped.
        if not log.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
            log.addHandler(handler)
            log.setLevel(logging.INFO)
            log.propagate = False
        app.state.settings = settings or Settings.from_env()
        app.state.router = router or build_router(app.state.settings)
        yield
        await app.state.router.aclose()

    app = FastAPI(title="Self-Hosted LLM Gateway", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/metrics")
    async def prometheus_metrics():
        # Unauthenticated by design: scraped from inside the cluster only.
        # The Service for it is ClusterIP; never expose this path on the ingress.
        return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.post("/token", response_model=TokenResponse)
    async def token(body: TokenRequest, request: Request):
        settings: Settings = request.app.state.settings
        if not verify_client(settings, body.client_id, body.client_secret):
            raise HTTPException(401, "invalid client credentials")
        return TokenResponse(
            access_token=issue_token(settings, body.client_id), expires_in=settings.jwt_ttl_s
        )

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest, request: Request, response: Response, client: str = Depends(current_client)
    ):
        settings: Settings = request.app.state.settings
        if body.max_tokens > settings.max_tokens_limit:
            raise HTTPException(422, f"max_tokens exceeds limit of {settings.max_tokens_limit}")

        request_id = uuid.uuid4().hex
        try:
            routed = await request.app.state.router.complete(
                body.messages,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
                client=client,
                choice=body.backend,
            )
        except AllBackendsFailed as exc:
            log.warning("request %s failed: %s", request_id, exc)
            return JSONResponse(
                status_code=exc.status,
                content={
                    "id": request_id,
                    "detail": "no backend could serve the request",
                    "errors": [{"backend": n, "reason": e.reason} for n, e in exc.errors],
                },
            )

        response.headers["x-served-by"] = routed.served_by
        response.headers["x-request-id"] = request_id
        if routed.fallback_reason:
            response.headers["x-fallback-reason"] = routed.fallback_reason
        log.info(
            "request %s client=%s served_by=%s latency_ms=%d fallback=%s",
            request_id, client, routed.served_by, routed.latency_s * 1000, routed.fallback_reason,
        )
        c = routed.completion
        return ChatResponse(
            id=request_id,
            content=c.content,
            model=c.model,
            served_by=routed.served_by,
            usage=c.usage,
            latency_ms=int(routed.latency_s * 1000),
            fallback_reason=routed.fallback_reason,
            finish_reason=c.finish_reason,
        )

    return app


app = create_app()
