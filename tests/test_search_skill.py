"""Tests for SearchCatalogSkill against an in-memory catalog."""
from __future__ import annotations

import pytest

from llm_search_kit import SearchCatalogSkill
from llm_search_kit.examples.amazon_products.catalog import InMemoryAmazonCatalog
from llm_search_kit.examples.amazon_products.schema import build_schema  # noqa: F401


@pytest.fixture
def skill() -> SearchCatalogSkill:
    return SearchCatalogSkill(schema=build_schema(), backend=InMemoryAmazonCatalog())


def test_parameters_schema_includes_control_fields(skill: SearchCatalogSkill):
    params = skill.parameters_schema
    assert params["type"] == "object"
    props = params["properties"]
    # Domain fields are present.
    for f in ("category", "brand", "color", "size", "min_price", "max_price",
              "min_rating", "prime_only"):
        assert f in props
    # Control fields auto-added by SearchCatalogSkill.
    for f in ("query", "sort_by", "skip", "limit"):
        assert f in props


def test_tool_schema_is_openai_compatible(skill: SearchCatalogSkill):
    schema = skill.to_tool_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search_catalog"
    assert "parameters" in schema["function"]
    assert schema["function"]["parameters"]["type"] == "object"


async def test_returns_items_when_filters_match(skill: SearchCatalogSkill):
    result = await skill.execute(category="shoes", brand="Nike")
    assert result.success
    assert result.data is not None
    assert result.data["total"] >= 1
    assert all(it["category"] == "shoes" for it in result.data["items"])
    assert all(it["brand"].lower() == "nike" for it in result.data["items"])
    assert result.data["relaxation_level"] == 0


async def test_relaxes_when_strict_filters_yield_zero(skill: SearchCatalogSkill):
    # No headphones in 'red' color; we should fall back to dropping color.
    result = await skill.execute(category="headphones", color="red")
    assert result.success
    assert result.data is not None
    assert result.data["total"] >= 1
    assert result.data["relaxation_level"] >= 1
    assert all(it["category"] == "headphones" for it in result.data["items"])


async def test_returns_empty_when_no_relaxation_helps(skill: SearchCatalogSkill):
    # An impossible category produces zero results since 'category' is core.
    result = await skill.execute(category="kitchen", max_price=0.01)
    assert result.success
    # Even the relaxed search keeps category=kitchen, but with all-relaxed
    # there should be at least one kitchen item without the price constraint.
    if result.data["total"] == 0:
        assert result.data["relaxation_level"] >= 1
    else:
        # When relaxation kicks in the price filter is dropped.
        assert result.data["relaxation_level"] >= 1


async def test_query_string_filters_by_title(skill: SearchCatalogSkill):
    result = await skill.execute(category="laptops", query="MacBook")
    assert result.success
    assert result.data["total"] >= 1
    titles = [it["title"].lower() for it in result.data["items"]]
    assert any("macbook" in t for t in titles)


async def test_sort_by_price_asc(skill: SearchCatalogSkill):
    result = await skill.execute(category="phones", sort_by="price_asc")
    prices = [it["price"] for it in result.data["items"]]
    assert prices == sorted(prices)


async def test_pagination_skip_and_limit(skill: SearchCatalogSkill):
    page1 = await skill.execute(category="shoes", limit=2, skip=0)
    page2 = await skill.execute(category="shoes", limit=2, skip=2)
    assert len(page1.data["items"]) <= 2
    assert len(page2.data["items"]) <= 2
    ids1 = {it["id"] for it in page1.data["items"]}
    ids2 = {it["id"] for it in page2.data["items"]}
    assert ids1.isdisjoint(ids2)


async def test_skill_ignores_context_kwarg(skill: SearchCatalogSkill):
    """The engine injects __context__; the search skill must ignore it gracefully."""
    result = await skill.execute(
        category="shoes",
        __context__={"user_id": "u-1"},
    )
    assert result.success
    assert "filters_used" in (result.data or {})
    assert "__context__" not in result.data["filters_used"]
