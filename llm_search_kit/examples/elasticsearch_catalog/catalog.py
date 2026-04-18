"""Elasticsearch ``CatalogBackend`` adapter.

This is the recommended starting point if your products live in
Elasticsearch / OpenSearch. Copy this file into your own project, change
the field mapping in :func:`ElasticsearchCatalog.search` to match your
index, and you are done.

The adapter is intentionally written against the **public Elasticsearch
8.x async client API** (``elasticsearch.AsyncElasticsearch``). It also
works against OpenSearch with the ``opensearchpy.AsyncOpenSearch`` client
since the request/response shape is identical for the operations we use.

We do *not* import ``elasticsearch`` at module top-level so the rest of
the kit (and its tests) does not need it as a dependency. Install it
explicitly when you actually want to use this adapter::

    pip install "elasticsearch[async]>=8,<9"
"""
from __future__ import annotations

from typing import Any, Awaitable, Dict, List, Optional, Protocol


class _AsyncESLike(Protocol):
    """Minimal subset of ``AsyncElasticsearch`` we depend on.

    Declared as a Protocol so that:
      * the real client (``elasticsearch.AsyncElasticsearch``) satisfies it,
      * tests can inject a tiny in-process fake without installing
        Elasticsearch.
    """

    def search(self, *, index: str, body: Dict[str, Any]) -> Awaitable[Dict[str, Any]]: ...


def build_default_index_mapping() -> Dict[str, Any]:
    """Return a sensible ``products`` index mapping you can use as a starter.

    Example::

        from elasticsearch import AsyncElasticsearch
        from llm_search_kit.examples.elasticsearch_catalog import build_default_index_mapping

        es = AsyncElasticsearch("http://localhost:9200")
        await es.indices.create(index="products", body=build_default_index_mapping())
    """
    return {
        "mappings": {
            "properties": {
                "title":       {"type": "text"},
                "description": {"type": "text"},
                "brand":       {"type": "keyword"},
                "category":    {"type": "keyword"},
                "color":       {"type": "keyword"},
                "size":        {"type": "keyword"},
                "price":       {"type": "double"},
                "rating":      {"type": "double"},
                "in_stock":    {"type": "boolean"},
                "created_at":  {"type": "date"},
            }
        }
    }


class ElasticsearchCatalog:
    """Map kit-shaped filters to an Elasticsearch query.

    Filters understood out of the box:
      * ``category``, ``brand``, ``color``, ``size``  → ``term`` filters
      * ``in_stock`` (bool)                            → ``term`` filter
      * ``min_price`` / ``max_price``                  → ``range`` on ``price``
      * ``min_rating``                                 → ``range`` on ``rating``
      * free-text ``query``                            → ``multi_match`` on
        ``title^3`` + ``description`` + ``brand``

    Extra keys present in ``filters`` are ignored, so you can extend
    ``SearchSchema`` without breaking the adapter — just teach it any new
    keys you actually want to enforce.

    ``sort_by`` recognises ``"price_asc"``, ``"price_desc"``, ``"newest"``,
    and falls back to relevance for anything else.
    """

    def __init__(
        self,
        client: _AsyncESLike,
        index: str = "products",
        *,
        text_fields: Optional[List[str]] = None,
    ) -> None:
        self._es = client
        self._index = index
        self._text_fields = text_fields or ["title^3", "description", "brand"]

    async def search(
        self,
        filters: Dict[str, Any],
        query: str = "",
        sort_by: str = "relevance",
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        must: List[Dict[str, Any]] = []
        flt: List[Dict[str, Any]] = []

        if query:
            must.append({
                "multi_match": {
                    "query": query,
                    "fields": self._text_fields,
                    "fuzziness": "AUTO",
                }
            })

        for key in ("category", "brand", "color", "size"):
            if key in filters and filters[key] not in (None, "", []):
                flt.append({"term": {key: filters[key]}})

        if "in_stock" in filters and filters["in_stock"] is not None:
            flt.append({"term": {"in_stock": bool(filters["in_stock"])}})

        price_range: Dict[str, Any] = {}
        if filters.get("min_price") is not None:
            price_range["gte"] = filters["min_price"]
        if filters.get("max_price") is not None:
            price_range["lte"] = filters["max_price"]
        if price_range:
            flt.append({"range": {"price": price_range}})

        if filters.get("min_rating") is not None:
            flt.append({"range": {"rating": {"gte": filters["min_rating"]}}})

        body: Dict[str, Any] = {
            "from": max(0, int(skip or 0)),
            "size": max(1, int(limit or 10)),
            "query": {
                "bool": {
                    "must": must or [{"match_all": {}}],
                    "filter": flt,
                }
            },
        }
        if sort_by == "price_asc":
            body["sort"] = [{"price": "asc"}]
        elif sort_by == "price_desc":
            body["sort"] = [{"price": "desc"}]
        elif sort_by == "newest":
            body["sort"] = [{"created_at": "desc"}]

        resp = await self._es.search(index=self._index, body=body)

        hits = (resp.get("hits") or {}).get("hits") or []
        items: List[Dict[str, Any]] = []
        for hit in hits:
            src = dict(hit.get("_source") or {})
            src.setdefault("_id", hit.get("_id"))
            items.append(src)

        total_block = (resp.get("hits") or {}).get("total") or {}
        if isinstance(total_block, dict):
            total = int(total_block.get("value", len(items)))
        else:
            total = int(total_block or len(items))

        return {"items": items, "total": total}
