"""Routing and fallback: try the primary backend, fall back when it fails retryably."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from . import metrics
from .providers.base import Completion, Message, Provider, ProviderError

BackendChoice = Literal["auto", "self_hosted", "anthropic"]


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
        # Pass a non-retryable client error (bad request) through as-is;
        # anything else means the gateway couldn't reach a working backend.
        last = self.errors[-1][1]
        if not last.retryable and last.status and 400 <= last.status < 500:
            return last.status
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
