"""Unit tests for ``OpenAILLMClient``.

Two regressions we explicitly cover here, both reported by Armand
running the kit against a local Ollama:

  1. ``HTTP 400 ... does not support tools``  → must surface as
     ``UnsupportedToolingError`` with an actionable hint, instead of
     returning ``None`` and letting the agent loop forever.
  2. ``RuntimeError: Event loop is closed``   → must NOT happen when
     the client is reused across short-lived event loops (the case
     for Flask + ``asyncio.new_event_loop`` per request).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from llm_search_kit.llm.openai_compat import (
    OpenAILLMClient,
    UnsupportedToolingError,
)


# Snapshot the real httpx.AsyncClient at import time so the monkey-
# patched version (which delegates to it) doesn't recurse.
_REAL_ASYNC_CLIENT = httpx.AsyncClient

_CURRENT_HANDLER: list = [None]


def _client_with_transport(handler) -> OpenAILLMClient:
    """Build an OpenAILLMClient whose every per-call ``AsyncClient`` is
    intercepted by ``handler`` (turned into an ``httpx.MockTransport``).
    The fixture below patches ``openai_compat.httpx.AsyncClient`` to
    inject the mock transport.
    """
    _CURRENT_HANDLER[0] = handler
    return OpenAILLMClient(
        base_url="http://fake.local/v1",
        api_key="",
        model="qwen-test",
        max_retries=1,
    )


@pytest.fixture(autouse=True)
def _patch_async_client(monkeypatch):
    import llm_search_kit.llm.openai_compat as mod

    def _patched(*args, **kwargs):
        handler = _CURRENT_HANDLER[0]
        if handler is not None:
            kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _patched)
    yield
    _CURRENT_HANDLER[0] = None


# --------------------------------------------------------------------- happy path


def test_returns_parsed_response_on_200():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "qwen-test"
        assert body["messages"][0]["content"] == "hi"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello!"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        )

    client = _client_with_transport(handler)
    resp = asyncio.run(client.chat_completion(messages=[{"role": "user", "content": "hi"}]))

    assert resp is not None
    assert resp["choices"][0]["message"]["content"] == "hello!"


# --------------------------------------------------------------- "no tools" path


def test_unsupported_tools_raises_actionable_error():
    """Ollama returns HTTP 400 when the served model lacks tool-calling.

    Before the fix the client just logged and returned ``None``; the
    agent then looped, retrying with the same broken setup. We now
    raise a typed exception with a fix hint.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "registry.ollama.ai/library/llama3:latest does not support tools",
                    "type": "invalid_request_error",
                }
            },
        )

    client = _client_with_transport(handler)
    with pytest.raises(UnsupportedToolingError) as excinfo:
        asyncio.run(client.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        ))

    msg = str(excinfo.value)
    assert "does not support" in msg.lower() or "does not support tools" in msg
    assert "qwen2.5" in msg
    assert "LLM_MODEL=" in msg


def test_unsupported_tools_only_when_tools_field_sent():
    """If the caller didn't ask for tools, a 400 is just a normal 400."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model does not support tools"}})

    client = _client_with_transport(handler)
    out = asyncio.run(client.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        # No tools=...
    ))
    assert out is None


def test_other_400s_do_not_misclassify_as_tooling_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad temperature value"}})

    client = _client_with_transport(handler)
    out = asyncio.run(client.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
    ))
    assert out is None  # graceful ``None``, NOT an UnsupportedToolingError


# ---------------------------------------------------------- event-loop-closed path


def test_can_reuse_client_across_distinct_event_loops():
    """Flask example builds a fresh event loop per request and shares
    one ``OpenAILLMClient`` instance across them. With the previous
    cached-``httpx.AsyncClient`` design the second loop crashed with
    ``RuntimeError: Event loop is closed``. After the fix each call
    opens its own ``AsyncClient`` so this scenario must just work.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = _client_with_transport(handler)

    def _one_request():
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                client.chat_completion(messages=[{"role": "user", "content": "ping"}])
            )
        finally:
            loop.close()

    first = _one_request()
    second = _one_request()
    third = _one_request()

    for r in (first, second, third):
        assert r is not None
        assert r["choices"][0]["message"]["content"] == "ok"


# --------------------------------------------------------------- aclose is a no-op


def test_aclose_is_idempotent_and_safe():
    client = _client_with_transport(lambda r: httpx.Response(200, json={}))
    # Calling aclose() repeatedly must not raise, even though we no
    # longer hold an httpx.AsyncClient instance internally.
    asyncio.run(client.aclose())
    asyncio.run(client.aclose())
