"""End-to-end tests for the Flask example server.

We never call a real LLM here -- we inject a ``ScriptedLLMClient`` (from
``conftest.py``) that emits a tool call to ``search_catalog`` and then a
final reply. That exercises the full Flask -> AgentEngine -> Skill ->
catalog -> Flask roundtrip while staying offline.
"""
from __future__ import annotations

import pytest

from .conftest import ScriptedLLMClient, make_tool_call

pytest.importorskip("flask")  # skip the file entirely if Flask is missing.

from llm_search_kit.examples.amazon_products.catalog import InMemoryAmazonCatalog
from llm_search_kit.examples.amazon_products.schema import build_schema
from llm_search_kit.examples.flask_server.app import create_app


def _make_app(scripted_responses):
    return create_app(
        catalog=InMemoryAmazonCatalog(),
        schema=build_schema(),
        llm_client=ScriptedLLMClient(scripted_responses),
        system_prompt="test",
    )


def test_health_endpoint_lists_registered_skills():
    app = _make_app(scripted_responses=["unused"])
    client = app.test_client()

    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "search_catalog" in body["skills"]


def test_chat_returns_reply_and_products():
    scripted = [
        [make_tool_call("c1", "search_catalog", {"category": "shoes", "query": "running"})],
        "Here are some running shoes you might like.",
    ]
    app = _make_app(scripted)
    client = app.test_client()

    resp = client.post("/chat", json={
        "message": "Find me running shoes",
        "session_id": "demo",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["reply"] == "Here are some running shoes you might like."
    assert isinstance(body["products"], list)
    assert body["meta"]["tool_calls"] == 1
    assert body["meta"]["filters_used"].get("category") == "shoes"


def test_chat_rejects_empty_message():
    app = _make_app(scripted_responses=["unused"])
    client = app.test_client()

    resp = client.post("/chat", json={"message": "", "session_id": "x"})

    assert resp.status_code == 400
    assert resp.get_json()["error"]


def test_chat_remembers_history_per_session():
    scripted = [
        "Hi! What are you looking for?",   # turn 1 final reply
        "Got it -- here's something.",      # turn 2 final reply
    ]
    app = _make_app(scripted)
    client = app.test_client()
    engine = app.config["LSK_ENGINE"]

    r1 = client.post("/chat", json={"message": "hello", "session_id": "alice"})
    r2 = client.post("/chat", json={"message": "show me shoes", "session_id": "alice"})

    assert r1.status_code == r2.status_code == 200
    sessions = app.config["LSK_SESSIONS"]
    history = list(sessions["alice"])
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["content"] == "hello"
    assert history[2]["content"] == "show me shoes"

    # The second LLM call must have included turn-1 history before the new user message.
    second_call_messages = engine._llm.calls[1]["messages"]  # type: ignore[attr-defined]
    user_contents = [m["content"] for m in second_call_messages if m.get("role") == "user"]
    assert user_contents == ["hello", "show me shoes"]


def test_session_reset_clears_history():
    scripted = ["first", "second"]
    app = _make_app(scripted)
    client = app.test_client()

    client.post("/chat", json={"message": "hello", "session_id": "bob"})
    assert len(app.config["LSK_SESSIONS"]["bob"]) == 2

    resp = client.post("/sessions/bob/reset")

    assert resp.status_code == 200
    assert "bob" not in app.config["LSK_SESSIONS"]


def test_chat_returns_500_on_engine_failure():
    # ScriptedLLMClient returns None -> engine returns its technical-error reply
    # with 200, NOT 500. So to trigger 500 we monkey-patch the engine.process to raise.
    app = _make_app(scripted_responses=["unused"])
    client = app.test_client()

    async def boom(*a, **kw):
        raise RuntimeError("kaboom")

    app.config["LSK_ENGINE"].process = boom  # type: ignore[assignment]

    resp = client.post("/chat", json={"message": "hi", "session_id": "z"})

    assert resp.status_code == 500
    assert resp.get_json()["error"] == "agent_failure"
