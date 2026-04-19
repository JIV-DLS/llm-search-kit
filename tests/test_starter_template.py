"""Smoke tests for the starter template.

The starter is the file we point new users at. If it ever stops booting
or wires the wrong skills, integration with new projects breaks
silently. These tests guard against both failure modes.

Coverage
--------
1. ``service.make_app`` returns a Flask app with the demo skills auto-discovered.
2. ``GET /health`` lists the discovered skills.
3. The default search skill is **off** in the starter (because the demo
   has no catalog) — regression guard.
4. ``POST /chat`` works end-to-end with a stubbed LLM that triggers
   ``convert_currency``.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from llm_search_kit import BaseLLMClient
from llm_search_kit.examples.starter.service import make_app


# =============================================================================
# Stub LLM
# =============================================================================


class _ScriptedLLM(BaseLLMClient):
    """Returns a pre-canned sequence of LLM responses, one per call."""

    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    async def chat_completion(
        self,
        messages,
        tools=None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ):
        self.calls.append({"messages": list(messages), "tools": tools})
        return self._responses.pop(0)


def _tool_call_response(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"choices": [{"message": {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }],
    }}]}


def _final_text(text: str) -> Dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


# =============================================================================
# Tests
# =============================================================================


def test_starter_app_auto_discovers_demo_skills() -> None:
    app = make_app(llm_client=_ScriptedLLM([_final_text("ok")]))

    skills = app.config["LSK_ENGINE"].available_skills

    assert "convert_currency" in skills
    assert "greet_user" in skills


def test_starter_does_not_register_default_search_skill() -> None:
    """Regression: the starter has no catalog, so search_catalog must be off."""
    app = make_app(llm_client=_ScriptedLLM([_final_text("ok")]))

    assert "search_catalog" not in app.config["LSK_ENGINE"].available_skills


def test_starter_health_endpoint_lists_discovered_skills() -> None:
    app = make_app(llm_client=_ScriptedLLM([_final_text("ok")]))
    client = app.test_client()

    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert "convert_currency" in body["skills"]
    assert "greet_user" in body["skills"]


def test_starter_chat_endpoint_routes_to_convert_currency() -> None:
    llm = _ScriptedLLM([
        _tool_call_response("convert_currency", {
            "amount": 100, "from_ccy": "EUR", "to_ccy": "XOF",
        }),
        _final_text("100 EUR is roughly 65 596 XOF."),
    ])
    app = make_app(llm_client=llm)
    client = app.test_client()

    resp = client.post("/chat", json={
        "message": "convert 100 EUR to XOF", "session_id": "t1",
    })

    assert resp.status_code == 200
    body = resp.get_json()
    assert "65 596" in body["reply"] or "65596" in body["reply"]
    assert body["meta"]["tool_calls"] == 1
