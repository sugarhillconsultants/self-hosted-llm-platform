"""Gateway configuration, read once from environment variables.

Everything is explicit and fails loudly at startup: a gateway that starts with
a missing JWT secret or an unparseable client list is worse than one that
refuses to start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _parse_clients(raw: str) -> dict[str, str]:
    """Parse CLIENTS="id1:secret1,id2:secret2" into {id: secret}."""
    clients: dict[str, str] = {}
    for entry in filter(None, (e.strip() for e in raw.split(","))):
        client_id, sep, secret = entry.partition(":")
        if not sep or not client_id or not secret:
            raise ConfigError(f"CLIENTS entry {entry!r} must look like id:secret")
        clients[client_id] = secret
    return clients


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    clients: dict[str, str]
    jwt_ttl_s: int = 3600

    # Self-hosted backend: anything speaking the OpenAI chat-completions API
    # (vLLM on EKS, llama.cpp server locally).
    self_hosted_url: str = "http://localhost:8080"
    self_hosted_model: str = "local-model"
    self_hosted_timeout_s: float = 30.0

    # Fallback backend.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"
    anthropic_url: str = "https://api.anthropic.com"
    anthropic_timeout_s: float = 60.0

    # Which backend "auto" routing tries first.
    primary_backend: str = "self_hosted"
    fallback_enabled: bool = True

    max_tokens_limit: int = 2048

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)

        jwt_secret = env.get("JWT_SECRET", "")
        if len(jwt_secret) < 32:
            raise ConfigError("JWT_SECRET must be set and at least 32 characters")

        clients = _parse_clients(env.get("CLIENTS", ""))
        if not clients:
            raise ConfigError("CLIENTS must list at least one id:secret pair")

        primary = env.get("PRIMARY_BACKEND", "self_hosted")
        if primary not in ("self_hosted", "anthropic"):
            raise ConfigError("PRIMARY_BACKEND must be self_hosted or anthropic")

        return cls(
            jwt_secret=jwt_secret,
            clients=clients,
            jwt_ttl_s=int(env.get("JWT_TTL_S", "3600")),
            self_hosted_url=env.get("SELF_HOSTED_URL", cls.self_hosted_url).rstrip("/"),
            self_hosted_model=env.get("SELF_HOSTED_MODEL", cls.self_hosted_model),
            self_hosted_timeout_s=float(env.get("SELF_HOSTED_TIMEOUT_S", "30")),
            anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
            anthropic_model=env.get("ANTHROPIC_MODEL", cls.anthropic_model),
            anthropic_url=env.get("ANTHROPIC_URL", cls.anthropic_url).rstrip("/"),
            anthropic_timeout_s=float(env.get("ANTHROPIC_TIMEOUT_S", "60")),
            primary_backend=primary,
            fallback_enabled=env.get("FALLBACK_ENABLED", "true").lower() == "true",
            max_tokens_limit=int(env.get("MAX_TOKENS_LIMIT", "2048")),
        )
