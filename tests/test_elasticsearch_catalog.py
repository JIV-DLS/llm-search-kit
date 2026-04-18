"""Tests for the Elasticsearch CatalogBackend example.

We don't run a real Elasticsearch in CI -- we feed the adapter a tiny
fake client that records the issued ``body`` and returns a canned
``hits`` payload. That is enough to lock down the filter-translation
behaviour, which is the only non-trivial thing in the adapter.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from llm_search_kit.examples.elasticsearch_catalog import ElasticsearchCatalog


class _FakeES:
    """Minimal stand-in for ``AsyncElasticsearch`` for these tests."""

    def __init__(self, items: List[Dict[str, Any]]) -> None:
        self._items = items
        self.last_body: Dict[str, Any] | None = None
        self.last_index: str | None = None

    async def search(self, *, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.last_index = index
        self.last_body = body
        return {
            "hits": {
                "total": {"value": len(self._items)},
                "hits": [{"_id": str(i), "_source": doc}
                         for i, doc in enumerate(self._items)],
            }
        }


@pytest.mark.asyncio
async def test_returns_items_and_total_in_kit_shape():
    es = _FakeES([{"title": "Shoe", "price": 50}, {"title": "Shoe 2", "price": 60}])
    catalog = ElasticsearchCatalog(es, index="products")

    out = await catalog.search(filters={}, query="", limit=10)

    assert out["total"] == 2
    assert [it["title"] for it in out["items"]] == ["Shoe", "Shoe 2"]
    assert all("_id" in it for it in out["items"])


@pytest.mark.asyncio
async def test_term_filters_are_applied():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(
        filters={"category": "shoes", "brand": "Nike", "color": "red", "in_stock": True},
        query="",
    )

    flt = es.last_body["query"]["bool"]["filter"]
    assert {"term": {"category": "shoes"}} in flt
    assert {"term": {"brand": "Nike"}}     in flt
    assert {"term": {"color": "red"}}      in flt
    assert {"term": {"in_stock": True}}    in flt


@pytest.mark.asyncio
async def test_price_and_rating_become_range_queries():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(
        filters={"min_price": 10, "max_price": 100, "min_rating": 4.5},
        query="",
    )

    flt = es.last_body["query"]["bool"]["filter"]
    assert {"range": {"price":  {"gte": 10, "lte": 100}}}  in flt
    assert {"range": {"rating": {"gte": 4.5}}}             in flt


@pytest.mark.asyncio
async def test_query_text_becomes_multi_match():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(filters={}, query="running shoes")

    must = es.last_body["query"]["bool"]["must"]
    assert len(must) == 1
    mm = must[0]["multi_match"]
    assert mm["query"]    == "running shoes"
    assert mm["fuzziness"] == "AUTO"
    assert "title^3" in mm["fields"]


@pytest.mark.asyncio
async def test_empty_filters_and_query_use_match_all():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(filters={}, query="")

    must = es.last_body["query"]["bool"]["must"]
    assert must == [{"match_all": {}}]
    assert es.last_body["query"]["bool"]["filter"] == []


@pytest.mark.asyncio
async def test_sort_by_price_asc_emits_sort_clause():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(filters={}, query="", sort_by="price_asc")

    assert es.last_body["sort"] == [{"price": "asc"}]


@pytest.mark.asyncio
async def test_relevance_sort_emits_no_sort_clause():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(filters={}, query="", sort_by="relevance")

    assert "sort" not in es.last_body


@pytest.mark.asyncio
async def test_skip_and_limit_become_from_and_size():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(filters={}, query="", skip=20, limit=5)

    assert es.last_body["from"] == 20
    assert es.last_body["size"] == 5


@pytest.mark.asyncio
async def test_unknown_filter_keys_are_ignored_gracefully():
    es = _FakeES([])
    catalog = ElasticsearchCatalog(es, index="products")

    await catalog.search(filters={"category": "shoes", "weird_extra": "ignored"}, query="")

    flt = es.last_body["query"]["bool"]["filter"]
    assert {"term": {"category": "shoes"}} in flt
    assert all("weird_extra" not in str(f) for f in flt)
