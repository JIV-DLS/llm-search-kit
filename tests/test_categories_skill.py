"""Unit tests for the worked-example ``CategoriesSkill``.

This is the second tool plugged into the Beasy agent (alongside
``SearchCatalogSkill``). The point of this test file is also pedagogic:
it shows how to test any new skill in isolation by injecting a
pre-baked ``httpx.AsyncClient`` over ``MockTransport``.
"""
from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from llm_search_kit.examples.beasyapp_backend.categories_skill import CategoriesSkill


def _client_returning(payload: Any, *, status: int = 200) -> httpx.AsyncClient:
    """Build an httpx client whose every call returns ``payload``."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.dumps(payload).encode() if not isinstance(payload, (bytes, str)) else payload
        return httpx.Response(
            status,
            content=body,
            headers={"content-type": "application/json"},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_returns_normalised_categories_from_envelope():
    payload = {
        "categories": [
            {"id": 1, "nameEn": "Electronics", "nameFr": "Électronique"},
            {"id": 2, "nameEn": "Fashion",     "nameFr": "Mode"},
        ]
    }
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=_client_returning(payload),
    )

    result = await skill.execute()

    assert result.success is True
    assert result.data["total"] == 2
    assert result.data["categories"][0]["nameEn"] == "Electronics"
    assert result.data["categories"][0]["nameFr"] == "Électronique"
    assert "Found 2 categor" in result.message


@pytest.mark.asyncio
async def test_accepts_bare_list_payload():
    """Spring controllers sometimes return a bare JSON array — support both."""
    payload = [
        {"id": 1, "nameEn": "Electronics"},
        {"id": 2, "nameEn": "Fashion"},
    ]
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=_client_returning(payload),
    )

    result = await skill.execute()

    assert result.success is True
    assert [c["id"] for c in result.data["categories"]] == [1, 2]


@pytest.mark.asyncio
async def test_extracts_parent_id_from_nested_parent():
    payload = [{"id": 10, "nameEn": "Smartphones", "parent": {"id": 1}}]
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=_client_returning(payload),
    )

    result = await skill.execute()
    assert result.data["categories"][0]["parentId"] == 1


@pytest.mark.asyncio
async def test_strips_internal_context_kwarg():
    """The kit injects ``__context__`` into every skill call. The skill
    must NOT pass it through as a query parameter to the backend."""
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"categories": []})

    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await skill.execute(__context__={"user_id": "abc", "trace_id": "xyz"})

    assert "__context__" not in captured["url"]
    assert "user_id" not in captured["url"]


# ------------------------------------------------------------- params


@pytest.mark.asyncio
async def test_parent_id_is_forwarded_to_backend():
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"categories": []})

    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    await skill.execute(parent_id=42)
    assert "parentId=42" in captured["url"]


@pytest.mark.asyncio
async def test_limit_clamps_response():
    payload = {"categories": [{"id": i, "nameEn": f"c{i}"} for i in range(10)]}
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=_client_returning(payload),
    )

    result = await skill.execute(limit=3)
    assert len(result.data["categories"]) == 3


# ------------------------------------------------------------- error paths


@pytest.mark.asyncio
async def test_4xx_returns_error_skill_result():
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=_client_returning({"error": "nope"}, status=503),
    )

    result = await skill.execute()
    assert result.success is False
    assert "503" in (result.error or "")


@pytest.mark.asyncio
async def test_non_json_payload_returns_error():
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=_client_returning(b"<html>oops</html>"),
    )

    result = await skill.execute()
    assert result.success is False
    assert result.error == "invalid_json"


# ------------------------------------------------------------- tool schema


def test_tool_schema_is_well_formed():
    """Every BaseSkill should produce a valid OpenAI tool schema."""
    skill = CategoriesSkill(
        base_url="http://fake.local",
        client=httpx.AsyncClient(),
    )
    schema = skill.to_tool_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "list_categories"
    assert "categories" in fn["description"].lower()
    assert fn["parameters"]["type"] == "object"
    assert "parent_id" in fn["parameters"]["properties"]


def test_construction_validates_max_returned():
    with pytest.raises(ValueError, match="max_returned"):
        CategoriesSkill(base_url="http://fake.local", max_returned=0)
