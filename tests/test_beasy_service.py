"""Tests for the ready-to-run Beasy chat service.

These tests prove the wiring between ``beasy_service.make_app`` and the
generic ``flask_server.create_app`` is correct WITHOUT making any HTTP
call to the real backend or burning any LLM credits.

We swap two things:

* the backend HTTP transport, via an ``httpx.MockTransport`` that returns
  a canned ``SearchResponse``;
* the LLM, via the ``ScriptedLLMClient`` from ``conftest.py`` so the
  agent loop is fully deterministic.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from .conftest import ScriptedLLMClient, make_tool_call

pytest.importorskip("flask")

from llm_search_kit.examples.beasy_service import make_app
from llm_search_kit.examples.beasyapp_backend.catalog import BeasyappCatalog
from llm_search_kit.examples.beasyapp_backend.schema import build_schema


def _stub_backend(listings: List[Dict[str, Any]] | None = None,
                  total: int = 0) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "listings":      listings or [],
            "totalElements": total,
            "totalPages":    1 if total else 0,
            "currentPage":   0,
            "facets":        {},
        })
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://stub",
    )


def _build_app(scripted_llm_responses, listings=None, total=0):
    """Build a service that uses a mocked backend AND a scripted LLM."""
    from llm_search_kit.examples.flask_server.app import create_app

    catalog = BeasyappCatalog(base_url="http://stub",
                              client=_stub_backend(listings, total))
    return create_app(
        catalog=catalog,
        schema=build_schema(),
        llm_client=ScriptedLLMClient(scripted_llm_responses),
        system_prompt="test prompt",
    )


def test_make_app_uses_default_url_and_registers_search_skill():
    """``make_app`` should produce a Flask app with the search_catalog skill
    registered and the configured backend URL surfaced in app.config."""
    app = make_app(
        beasy_url="http://example.invalid",
        llm_client=ScriptedLLMClient([]),
    )
    assert "search_catalog" in app.config["LSK_ENGINE"].available_skills
    assert app.config["BEASY_BACKEND_URL"] == "http://example.invalid"


def test_health_endpoint_advertises_search_skill():
    app = _build_app(scripted_llm_responses=["unused"])
    client = app.test_client()

    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "search_catalog" in body["skills"]


def test_chat_returns_products_from_backend_with_pii_scrubbed():
    """End-to-end: LLM emits a tool call -> catalog hits the (mocked) backend ->
    listings come back PII-scrubbed -> Flask response includes them."""
    backend_listings = [{
        "id": 42, "title": "Samsung TV", "price": 80000.0,
        "creator": {
            "id": 1, "username": "alice", "fullName": "Alice",
            "email":    "alice@x.com",
            "password": "$2a$10$secret",
            "phone":    "+228123",
            "addresses": [{"street": "secret st"}],
            "defaultShippingAddress": {"city": "Lomé", "country": "TG"},
        },
    }]
    scripted = [
        [make_tool_call("c1", "search_catalog",
                        {"query": "samsung tv", "max_price": 100000})],
        "Voici un Samsung TV à 80 000 FCFA qui correspond.",
    ]
    app = _build_app(scripted, listings=backend_listings, total=1)
    client = app.test_client()

    resp = client.post("/chat", json={"message": "samsung tv under 100k",
                                       "session_id": "demo"})

    assert resp.status_code == 200
    body = resp.get_json()

    assert body["reply"].startswith("Voici un Samsung TV")
    assert len(body["products"]) == 1
    product = body["products"][0]
    assert product["id"] == 42
    assert product["title"] == "Samsung TV"

    creator = product["creator"]
    assert creator["username"] == "alice"
    assert creator["city"] == "Lomé"
    # The whole point: PII MUST NOT leak through.
    assert "email"     not in creator
    assert "password"  not in creator
    assert "phone"     not in creator
    assert "addresses" not in creator

    # Meta surfaces the filters the LLM asked for + relaxation telemetry.
    assert body["meta"]["total"] == 1
    assert body["meta"]["relaxation_level"] == 0
    assert body["meta"]["filters_used"]["max_price"] == 100000
    assert body["meta"]["tool_calls"] == 1


def test_chat_remembers_history_per_session():
    """Two consecutive calls on the same session_id should accumulate
    history, and the LLM should see turn 1 in turn 2's messages."""
    scripted = ["hi there", "still here"]
    app = _build_app(scripted, listings=[], total=0)
    client = app.test_client()
    engine = app.config["LSK_ENGINE"]

    client.post("/chat", json={"message": "hello", "session_id": "armand"})
    client.post("/chat", json={"message": "still here?", "session_id": "armand"})

    history = list(app.config["LSK_SESSIONS"]["armand"])
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]

    # Second LLM call must include the first user/assistant turn before the
    # new user message -- this is what gives the assistant continuity.
    second_call = engine._llm.calls[1]["messages"]  # type: ignore[attr-defined]
    user_msgs = [m["content"] for m in second_call if m.get("role") == "user"]
    assert user_msgs == ["hello", "still here?"]


def test_chat_rejects_empty_message():
    app = _build_app(scripted_llm_responses=["unused"])
    client = app.test_client()

    resp = client.post("/chat", json={"message": "  ", "session_id": "x"})

    assert resp.status_code == 400
    assert resp.get_json()["error"]


def test_session_reset_clears_history():
    app = _build_app(scripted_llm_responses=["first"], listings=[], total=0)
    client = app.test_client()

    client.post("/chat", json={"message": "hi", "session_id": "bob"})
    assert "bob" in app.config["LSK_SESSIONS"]

    resp = client.post("/sessions/bob/reset")

    assert resp.status_code == 200
    assert "bob" not in app.config["LSK_SESSIONS"]
