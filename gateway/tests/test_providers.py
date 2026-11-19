"""Provider adapters against mocked HTTP: request shape, response parsing, error mapping."""

import asyncio
import json

import httpx
import pytest

from app.config import ConfigError, Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import Message, ProviderError
from app.providers.openai_compat import OpenAICompatProvider

MSGS = [Message(role="system", content="Be brief."), Message(role="user", content="hi")]


def call(provider):
    return asyncio.run(provider.complete(MSGS, max_tokens=32, temperature=0.1))


def transport(handler):
    return httpx.MockTransport(handler)


# --- OpenAI-compatible (vLLM / llama.cpp) ---------------------------------

def test_openai_compat_parses_completion_and_usage():
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "model": "qwen2.5-0.5b",
            "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 2},
        })

    p = OpenAICompatProvider("http://model:8080", "local-model", timeout_s=5, transport=transport(handler))
    c = call(p)
    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "Be brief."}
    assert seen["body"]["max_tokens"] == 32
    assert (c.content, c.usage.input_tokens, c.usage.output_tokens) == ("hello", 12, 2)


@pytest.mark.parametrize("status,reason,retryable", [
    (503, "upstream_5xx", True),
    (429, "rate_limited", True),
    (400, "upstream_4xx", False),
])
def test_openai_compat_maps_http_errors(status, reason, retryable):
    p = OpenAICompatProvider(
        "http://model:8080", "m", timeout_s=5, transport=transport(lambda r: httpx.Response(status, text="x"))
    )
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert (exc.value.reason, exc.value.retryable, exc.value.status) == (reason, retryable, status)


def test_openai_compat_maps_connection_refused():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    p = OpenAICompatProvider("http://model:8080", "m", timeout_s=5, transport=transport(handler))
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.reason == "connect_error" and exc.value.retryable


def test_openai_compat_maps_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    p = OpenAICompatProvider("http://model:8080", "m", timeout_s=5, transport=transport(handler))
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.reason == "timeout"


def test_openai_compat_bad_body():
    p = OpenAICompatProvider(
        "http://model:8080", "m", timeout_s=5, transport=transport(lambda r: httpx.Response(200, json={"oops": 1}))
    )
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.reason == "bad_response"


# --- Anthropic --------------------------------------------------------------

def test_anthropic_moves_system_prompt_and_sends_headers():
    seen = {}

    def handler(req):
        seen["headers"] = req.headers
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": "hi there"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 9, "output_tokens": 4},
        })

    p = AnthropicProvider("sk-test", "claude-haiku-5-5", timeout_s=5, transport=transport(handler))
    c = call(p)
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["system"] == "Be brief."
    assert all(m["role"] != "system" for m in seen["body"]["messages"])
    assert (c.content, c.usage.input_tokens, c.usage.output_tokens) == ("hi there", 9, 4)


def test_anthropic_without_key_is_not_retryable():
    p = AnthropicProvider(None, "m", timeout_s=5, transport=transport(lambda r: httpx.Response(200)))
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.reason == "not_configured" and not exc.value.retryable


def test_anthropic_overloaded_is_retryable():
    p = AnthropicProvider(
        "k", "m", timeout_s=5, transport=transport(lambda r: httpx.Response(529, json={"type": "error"}))
    )
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.reason == "upstream_5xx" and exc.value.retryable


# --- Config -------------------------------------------------------------------

@pytest.mark.parametrize("env", [
    {"CLIENTS": "a:b"},
    {"JWT_SECRET": "short", "CLIENTS": "a:b"},
    {"JWT_SECRET": "x" * 32, "CLIENTS": ""},
    {"JWT_SECRET": "x" * 32, "CLIENTS": "missing-colon"},
    {"JWT_SECRET": "x" * 32, "CLIENTS": "a:b", "PRIMARY_BACKEND": "gpt"},
])
def test_config_fails_loudly(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


# --- Regression tests for incidents #2 and #3 ---------------------------------

def test_anthropic_omits_temperature_by_default():
    # Incident #2: claude-haiku-5-5 answers `temperature` with a 400.
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}})

    call(AnthropicProvider("k", "claude-haiku-5-5", timeout_s=5, transport=transport(handler)))
    assert "temperature" not in seen["body"]


def test_anthropic_sends_temperature_when_enabled():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}})

    call(AnthropicProvider("k", "m", timeout_s=5, send_temperature=True, transport=transport(handler)))
    assert seen["body"]["temperature"] == 0.1


def test_anthropic_4xx_message_is_kept_for_logs():
    body = {"type": "error", "error": {"type": "invalid_request_error",
            "message": "`temperature` is deprecated for this model."}}
    p = AnthropicProvider("k", "m", timeout_s=5, transport=transport(lambda r: httpx.Response(400, json=body)))
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.status == 400 and not exc.value.retryable
    assert "deprecated" in str(exc.value)


def test_openai_compat_connect_timeout_is_its_own_reason():
    # Incident #3: "never connected" must be distinguishable from "slow to generate".
    def handler(req):
        raise httpx.ConnectTimeout("no route", request=req)

    p = OpenAICompatProvider("http://model:8080", "m", timeout_s=30, transport=transport(handler))
    with pytest.raises(ProviderError) as exc:
        call(p)
    assert exc.value.reason == "connect_timeout" and exc.value.retryable


def test_connect_timeout_is_short_and_separate_from_read_timeout():
    p = OpenAICompatProvider("http://model:8080", "m", timeout_s=30, connect_timeout_s=2)
    t = p._client.timeout
    assert (t.connect, t.read) == (2, 30)


def test_config_reads_new_settings():
    s = Settings.from_env({"JWT_SECRET": "x" * 32, "CLIENTS": "a:b",
                           "SELF_HOSTED_CONNECT_TIMEOUT_S": "1.5", "ANTHROPIC_SEND_TEMPERATURE": "true"})
    assert s.self_hosted_connect_timeout_s == 1.5 and s.anthropic_send_temperature
    default = Settings.from_env({"JWT_SECRET": "x" * 32, "CLIENTS": "a:b"})
    assert default.self_hosted_connect_timeout_s == 2.0 and not default.anthropic_send_temperature
