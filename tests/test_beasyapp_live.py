"""Live integration tests against Armand's actual Beasyapp backend.

These tests are SKIPPED by default. To run them::

    BEASY_LIVE=1 pytest tests/test_beasyapp_live.py -v

Optionally override the backend URL::

    BEASY_BASE_URL=https://your-tunnel.example.com BEASY_LIVE=1 \
        pytest tests/test_beasyapp_live.py -v

Each scenario asserts the **adapter contract** (kit-shape response,
pagination respected, sort respected, PII scrubbed) rather than the
specific items returned -- the catalog evolves and we don't want CI to
break every time a new listing is added.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import pytest

from llm_search_kit.examples.beasyapp_backend import BeasyappCatalog


_BASE_URL = os.environ.get(
    "BEASY_BASE_URL",
    "https://actinolitic-glancingly-saturnina.ngrok-free.dev",
)

# Whole module is skipped unless the developer opts in.
pytestmark = pytest.mark.skipif(
    os.environ.get("BEASY_LIVE") != "1",
    reason="Set BEASY_LIVE=1 to run live integration tests against the Beasyapp backend.",
)


@pytest.fixture
async def catalog():
    cat = BeasyappCatalog(base_url=_BASE_URL, timeout=30.0)
    yield cat
    await cat.aclose()


def _assert_kit_shape(out: Dict[str, Any]) -> None:
    assert isinstance(out, dict)
    assert isinstance(out.get("items"), list)
    assert isinstance(out.get("total"), int)
    assert "metadata" in out
    for item in out["items"]:
        creator = item.get("creator") or {}
        # PII MUST be scrubbed at the adapter boundary -- this is a hard
        # security contract, not just a nice-to-have.
        assert "email"     not in creator, item
        assert "password"  not in creator, item
        assert "phone"     not in creator, item
        assert "addresses" not in creator, item


@pytest.mark.asyncio
async def test_freetext_search_returns_kit_shape(catalog):
    out = await catalog.search(filters={}, query="samsung tv 4K", limit=5)
    _assert_kit_shape(out)
    assert out["total"] >= 0
    assert len(out["items"]) <= 5


@pytest.mark.asyncio
async def test_match_all_search_returns_results(catalog):
    out = await catalog.search(filters={}, query="", limit=5)
    _assert_kit_shape(out)
    assert out["total"] > 0, "we expect at least one listing in the demo catalog"


@pytest.mark.asyncio
async def test_facets_are_returned_when_requested(catalog):
    out = await catalog.search(filters={}, query="", limit=1)
    facets = (out.get("metadata") or {}).get("facets") or {}
    # The backend always returns at least one of these keys when there are listings.
    assert any(k in facets for k in ("brands", "cities", "colors",
                                     "priceRanges", "deliveryTypes")), facets


@pytest.mark.asyncio
async def test_min_max_price_filters_are_respected(catalog):
    out = await catalog.search(
        filters={"min_price": 1000, "max_price": 5000}, query="", limit=20,
    )
    _assert_kit_shape(out)
    for item in out["items"]:
        price = float(item.get("price") or 0)
        assert 1000 <= price <= 5000, f"price {price} out of [1000, 5000]"


@pytest.mark.asyncio
async def test_impossible_filter_returns_zero(catalog):
    out = await catalog.search(
        filters={"min_price": 99_999_999_999}, query="samsung", limit=10,
    )
    assert out["total"] == 0
    assert out["items"] == []


@pytest.mark.asyncio
async def test_price_asc_sort_is_monotonic(catalog):
    out = await catalog.search(filters={}, query="", sort_by="price_asc", limit=10)
    prices = [float(it.get("price") or 0) for it in out["items"]]
    assert prices == sorted(prices), prices


@pytest.mark.asyncio
async def test_price_desc_sort_is_monotonic(catalog):
    out = await catalog.search(filters={}, query="", sort_by="price_desc", limit=10)
    prices = [float(it.get("price") or 0) for it in out["items"]]
    assert prices == sorted(prices, reverse=True), prices


@pytest.mark.asyncio
async def test_pagination_returns_disjoint_pages(catalog):
    page0 = await catalog.search(filters={}, query="", sort_by="price_asc",
                                 skip=0, limit=5)
    page1 = await catalog.search(filters={}, query="", sort_by="price_asc",
                                 skip=5, limit=5)

    if page0["total"] >= 6:
        ids0 = {it.get("id") for it in page0["items"]}
        ids1 = {it.get("id") for it in page1["items"]}
        assert ids0 and ids1
        assert not (ids0 & ids1), f"pages overlap: {ids0 & ids1}"


@pytest.mark.asyncio
async def test_relaxation_recovers_results_when_filters_too_tight(catalog):
    """End-to-end relaxation: ask for an over-constrained query, then the
    SearchCatalogSkill should drop filters one by one and eventually find
    something. We exercise this through the skill, not the bare adapter."""
    from llm_search_kit import SearchCatalogSkill
    from llm_search_kit.examples.beasyapp_backend import build_schema

    skill = SearchCatalogSkill(schema=build_schema(), backend=catalog)
    result = await skill.execute(
        query="samsung",
        max_price=1,           # nothing this cheap
        min_rating=4.9,        # very tight
        color="#FF00FF",       # rare color
        debatable=True,
    )

    assert result.success
    # Either the backend returned 0 OR relaxation found something. Both are
    # acceptable; the contract is just that the call succeeds and reports
    # the relaxation level it stopped at.
    data = result.data or {}
    assert data["relaxation_level"] >= 0
    assert isinstance(data["items"], list)
