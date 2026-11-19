"""Routing and fallback: try the primary backend, fall back when it fails retryably."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

from . import metrics
from .providers.base import Completion, Message, Provider, ProviderError

BackendChoice = Literal["auto", "self_hosted", "anthropic"]

log = logging.getLogger("gateway")


@dataclass
class RoutedCompletion:
    completion: Completion
    served_by: str
    latency_s: float
    fallback_reason: str | None = None


class AllBackendsFailed(Exception):
    def __init__(self, errors: list[tuple[str, ProviderError]]):
        self.errors = errors
        summary = "; ".join(f"{name}: {err.reason}" for name, err in errors)
        super().__init__(f"all backends failed ({summary})")

    @property
    def status(self) -> int:
        # Only the FIRST backend's verdict can say the client's request was bad.
        # A 400 from the fallback, after the primary failed for its own reasons,
        # means the gateway built a request that backend rejects: a gateway
        # fault, so 502 (incident #2 surfaced as a misleading 400).
        first = self.errors[0][1]
        if not first.retryable and first.status and 400 <= first.status < 500:
            return first.status
        return 502


class Router:
    def __init__(self, providers: dict[str, Provider], primary: str, *, fallback_enabled: bool = True):
        if primary not in providers:
            raise ValueError(f"primary backend {primary!r} has no provider")
        self.providers = providers
        self.primary = primary
        self.fallback_enabled = fallback_enabled

    def _order(self, choice: BackendChoice) -> list[str]:
        if choice != "auto":
            # An explicit choice is honored with no fallback: a caller asking
            # for the self-hosted model (e.g. an eval run) must not silently
            # get an answer from a different model.
            return [choice]
        others = [name for name in self.providers if name != self.primary]
        return [self.primary, *others] if self.fallback_enabled else [self.primary]

    async def complete(
        self,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float,
        client: str,
        choice: BackendChoice = "auto",
    ) -> RoutedCompletion:
        errors: list[tuple[str, ProviderError]] = []
        for name in self._order(choice):
            provider = self.providers[name]
            start = time.perf_counter()
            try:
                completion = await provider.complete(
                    messages, max_tokens=max_tokens, temperature=temperature
                )
            except ProviderError as err:
                metrics.REQUESTS.labels(name, "error").inc()
                # The full upstream message goes to the log; only the short
                # reason goes to metrics and clients (incident #2: the reason
                # "upstream_4xx" alone didn't say what was wrong).
                log.warning(
                    "backend %s failed after %.2fs: reason=%s status=%s retryable=%s: %s",
                    name, time.perf_counter() - start, err.reason, err.status, err.retryable, err,
                )
                errors.append((name, err))
                if not err.retryable:
                    break
                continue

            latency = time.perf_counter() - start
            metrics.REQUESTS.labels(name, "ok").inc()
            metrics.LATENCY.labels(name).observe(latency)
            metrics.TOKENS.labels(name, "input", client).inc(completion.usage.input_tokens)
            metrics.TOKENS.labels(name, "output", client).inc(completion.usage.output_tokens)

            fallback_reason = None
            if errors:
                from_name, first_err = errors[0]
                fallback_reason = first_err.reason
                metrics.FALLBACKS.labels(from_name, name, fallback_reason).inc()
            return RoutedCompletion(completion, name, latency, fallback_reason)

        raise AllBackendsFailed(errors)

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()
