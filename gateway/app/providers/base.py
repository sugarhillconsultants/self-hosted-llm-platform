"""The interface every backend implements, plus the shared request/response shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Completion:
    content: str
    model: str
    usage: Usage
    finish_reason: str | None = None


class ProviderError(Exception):
    """A backend call failed.

    `reason` is a short, low-cardinality label used in metrics and in the
    x-fallback-reason header. `retryable` says whether another backend might
    succeed where this one failed: a timeout or a 5xx is, a malformed request
    (4xx other than 429) is not, because the fallback would reject it too.
    """

    def __init__(self, reason: str, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.status = status


class Provider(Protocol):
    name: str

    async def complete(
        self, messages: list[Message], *, max_tokens: int, temperature: float
    ) -> Completion: ...

    async def aclose(self) -> None: ...


def classify_http_status(status: int) -> tuple[str, bool]:
    """Map an upstream HTTP status to (reason, retryable)."""
    if status == 429:
        return "rate_limited", True
    if status >= 500:
        return "upstream_5xx", True
    return "upstream_4xx", False
