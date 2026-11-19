"""Backend for the Claude API (Messages endpoint), called over plain HTTP.

Plain httpx instead of the SDK keeps the error mapping identical to the
self-hosted adapter, so fallback decisions are made on the same terms.
"""

from __future__ import annotations

import httpx

from .base import Completion, Message, ProviderError, Usage, classify_http_status

API_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        timeout_s: float,
        base_url: str = "https://api.anthropic.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.name = "anthropic"
        self.model = model
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout_s), transport=transport
        )

    async def complete(
        self, messages: list[Message], *, max_tokens: int, temperature: float
    ) -> Completion:
        if not self._api_key:
            raise ProviderError("not_configured", "ANTHROPIC_API_KEY is not set", retryable=False)

        # The Messages API takes system prompts as a separate field.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [m.model_dump() for m in messages if m.role != "system"],
        }
        if system:
            body["system"] = system

        headers = {"x-api-key": self._api_key, "anthropic-version": API_VERSION}
        try:
            resp = await self._client.post("/v1/messages", json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "anthropic timed out", retryable=True) from exc
        except httpx.TransportError as exc:
            raise ProviderError("connect_error", f"anthropic unreachable: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            reason, retryable = classify_http_status(resp.status_code)
            raise ProviderError(
                reason,
                f"anthropic returned {resp.status_code}: {resp.text[:300]}",
                retryable=retryable,
                status=resp.status_code,
            )

        try:
            data = resp.json()
            content = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("bad_response", "anthropic sent an unexpected body", retryable=True) from exc

        usage = data.get("usage") or {}
        return Completion(
            content=content,
            model=data.get("model", self.model),
            usage=Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
            finish_reason=data.get("stop_reason"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
