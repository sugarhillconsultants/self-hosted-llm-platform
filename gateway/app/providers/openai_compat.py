"""Backend for any server exposing the OpenAI chat-completions API.

vLLM (on EKS) and llama.cpp's server (locally, in kind) both do, so the same
adapter covers Phase 0 and Phase 2 with only a URL change.
"""

from __future__ import annotations

import httpx

from .base import Completion, Message, ProviderError, Usage, classify_http_status


class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_s: float,
        connect_timeout_s: float = 2.0,
        name: str = "self_hosted",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.name = name
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=connect_timeout_s),
            transport=transport,
        )

    async def complete(
        self, messages: list[Message], *, max_tokens: int, temperature: float
    ) -> Completion:
        body = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            resp = await self._client.post("/v1/chat/completions", json=body)
        except httpx.ConnectTimeout as exc:
            # Checked before TimeoutException (its parent): "never connected"
            # and "connected but slow to generate" are different failures.
            raise ProviderError("connect_timeout", f"{self.name} connect timed out", retryable=True) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", f"{self.name} timed out", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderError("connect_error", f"{self.name} unreachable: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            reason, retryable = classify_http_status(resp.status_code)
            raise ProviderError(
                reason,
                f"{self.name} returned {resp.status_code}: {resp.text[:300]}",
                retryable=retryable,
                status=resp.status_code,
            )

        try:
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("bad_response", f"{self.name} sent an unexpected body", retryable=True) from exc

        usage = data.get("usage") or {}
        return Completion(
            content=content,
            model=data.get("model", self.model),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
            finish_reason=choice.get("finish_reason"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
