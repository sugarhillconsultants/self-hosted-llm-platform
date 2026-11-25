"""How much work wants the self-hosted model right now: the signal KEDA scales vLLM on.

vLLM's own queue metrics can't be the scale-up signal, because at zero
replicas there is no vLLM to report them. The gateway sees every request, so
it reports demand instead (ADR 0012).

    demand = peak, over the last `window_s` seconds, of the number of requests
             in flight at the gateway that want the self-hosted model,
             whichever backend ends up answering them.

Why concurrency, not a count of requests: a first version counted requests
that fell back to the Claude API. Fallbacks are fast, so 3 concurrent clients
produced ~69 "missed" requests in a 5-second window, which KEDA would read as
18 replicas' worth. Concurrency is what a vLLM replica actually has to carry,
and it doesn't depend on which backend is answering.

Why the peak over a window: a closed-loop client pauses between requests, and
traffic is bursty; the instantaneous count would flap to 0 and let KEDA's
cooldown start ticking while users are still active.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class DemandTracker:
    def __init__(self, window_s: float = 120.0, clock: Callable[[], float] = time.monotonic):
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self.window_s = window_s
        self._clock = clock
        self._wanting = 0  # in flight, wanting self-hosted, any backend serving
        self._inflight = 0  # of those, currently at the self-hosted backend
        self._levels: deque[tuple[float, int]] = deque()  # (time, wanting) at each change
        self._missed: deque[float] = deque()  # times of fallbacks away from self-hosted

    def _set_wanting(self, value: int) -> None:
        now = self._clock()
        # Record the level being left as well as the new one, so a level that
        # started before the window and ended inside it still counts.
        self._levels.append((now, self._wanting))
        self._wanting = value
        self._levels.append((now, value))

    @contextmanager
    def wanting(self) -> Iterator[None]:
        self._set_wanting(self._wanting + 1)
        try:
            yield
        finally:
            self._set_wanting(self._wanting - 1)

    @contextmanager
    def inflight(self) -> Iterator[None]:
        self._inflight += 1
        try:
            yield
        finally:
            self._inflight -= 1

    def missed(self) -> None:
        self._missed.append(self._clock())

    def _prune(self) -> None:
        cutoff = self._clock() - self.window_s
        while self._levels and self._levels[0][0] < cutoff:
            self._levels.popleft()
        while self._missed and self._missed[0] < cutoff:
            self._missed.popleft()

    @property
    def inflight_count(self) -> int:
        return self._inflight

    @property
    def peak(self) -> int:
        self._prune()
        return max([self._wanting, *(level for _, level in self._levels)])

    def snapshot(self) -> dict:
        peak = self.peak  # prunes
        return {
            "self_hosted_demand": peak,
            "wanting_now": self._wanting,
            "self_hosted_inflight": self._inflight,
            "fallbacks_recent": len(self._missed),
            "window_s": self.window_s,
        }
