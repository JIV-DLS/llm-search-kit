"""Catalog backend protocol.

Implement this against your own data source: SQL DB, REST API, vector
store, ElasticSearch, MongoDB, anything. The ``SearchCatalogSkill`` only
ever calls ``search``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


class CatalogSearchResult(Dict[str, Any]):
    """Mapping with at least ``items: List[dict]`` and ``total: int``."""


@runtime_checkable
class CatalogBackend(Protocol):
    """Async catalog backend protocol used by ``SearchCatalogSkill``."""

    async def search(
        self,
        filters: Dict[str, Any],
        query: str = "",
        sort_by: str = "relevance",
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Run a search and return ``{"items": [...], "total": int}``.

        Implementations may return additional metadata (latency, facets, etc.).
        """
        ...
