"""Routing and fallback: try the primary backend, fall back when it fails retryably."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal

from . import metrics
from .demand import DemandTracker
from .providers.base import Completion, Message, Provider, ProviderError

BackendChoice = Literal["auto", "self_hosted", "anthropic"]

log = logging.getLogger("gateway")


@dataclass
class RoutedCompletion:
    completion: Completion
    served_by: str
    latency_s: float
    fallback_reason: str | None = None
    total_s: float | None = None


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


# Failures meaning "the self-hosted backend isn't running (yet)", as opposed to
# "it's running and this request failed". Only these are worth waiting out
# under the "wait" cold-start policy.
NOT_RUNNING = frozenset({"connect_error", "connect_timeout"})

ColdStartPolicy = Literal["fallback", "wait"]


class Router:
    def __init__(
        self,
        providers: dict[str, Provider],
        primary: str,
        *,
        fallback_enabled: bool = True,
        demand: DemandTracker | None = None,
        tracked_backend: str = "self_hosted",
        cold_start_policy: ColdStartPolicy = "fallback",
        wait_s: float = 600.0,
        retry_interval_s: float = 5.0,
    ):
        if primary not in providers:
            raise ValueError(f"primary backend {primary!r} has no provider")
        if cold_start_policy not in ("fallback", "wait"):
            raise ValueError("cold_start_policy must be fallback or wait")
        self.providers = providers
        self.primary = primary
        self.fallback_enabled = fallback_enabled
        self.demand = demand or DemandTracker()
        self.tracked_backend = tracked_backend
        self.cold_start_policy = cold_start_policy
        self.wait_s = wait_s
        self.retry_interval_s = retry_interval_s

    async def _attempt(self, name: str, provider: Provider, messages, max_tokens, temperature):
        """One backend call. For the tracked (self-hosted) backend: counted as
        in-flight demand while it runs, and under the "wait" policy, retried
        while the backend isn't running, until wait_s has passed."""
        if name != self.tracked_backend:
            return await provider.complete(messages, max_tokens=max_tokens, temperature=temperature)
        deadline = time.monotonic() + self.wait_s
        with self.demand.inflight():
            while True:
                try:
                    return await provider.complete(messages, max_tokens=max_tokens, temperature=temperature)
                except ProviderError as err:
                    if (
                        self.cold_start_policy != "wait"
                        or err.reason not in NOT_RUNNING
                        or time.monotonic() + self.retry_interval_s > deadline
                    ):
                        raise
                    metrics.COLD_START_WAITS.inc()
                    await asyncio.sleep(self.retry_interval_s)

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
        order = self._order(choice)
        if self.tracked_backend in order:
            # Counted as self-hosted demand for its whole life, even if the
            # Claude API ends up answering it (ADR 0012).
            with self.demand.wanting():
                return await self._complete(order, messages, max_tokens, temperature, client)
        return await self._complete(order, messages, max_tokens, temperature, client)

    async def _complete(self, order, messages, max_tokens, temperature, client) -> RoutedCompletion:
        errors: list[tuple[str, ProviderError]] = []
        request_start = time.perf_counter()
        for name in order:
            provider = self.providers[name]
            start = time.perf_counter()
            try:
                completion = await self._attempt(name, provider, messages, max_tokens, temperature)
            except ProviderError as err:
                if name == self.tracked_backend and err.retryable:
                    self.demand.missed()  # for visibility; demand is concurrency
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
            # What the caller waited, failed attempts included: Phase 0 showed
            # backend latency alone hides the cost of a fallback.
            total = time.perf_counter() - request_start
            metrics.REQUEST_DURATION.labels(name, "yes" if errors else "no").observe(total)
            return RoutedCompletion(completion, name, latency, fallback_reason, total)

        raise AllBackendsFailed(errors)

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()
