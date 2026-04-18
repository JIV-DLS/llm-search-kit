"""HTTP catalog adapter for the real-estate example.

Talks to a backend that exposes a smart-search endpoint compatible with
the original rede contract:

    GET {base}/api/v1/smart-search/intelligent
        ?q=<text>&skip=<n>&limit=<n>&sort_by=<...>&city=<...>&...

The endpoint may return either a JSON list of items or a dict with
``items``/``properties`` and ``total``.

If you don't have a backend ready, the file also ships a tiny in-memory
demo (``InMemoryRealEstateCatalog``) so the CLI can still be played with.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from llm_search_kit.search import CatalogBackend

logger = logging.getLogger(__name__)


class HttpRealEstateCatalog(CatalogBackend):
    """HTTP adapter for a rede-style smart-search REST endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/api/v1/smart-search/intelligent",
        timeout: float = 30.0,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self._url = f"{base_url.rstrip('/')}{path}"
        self._headers = dict(extra_headers or {})
        self._client = httpx.AsyncClient(timeout=timeout)

    async def search(
        self,
        filters: Dict[str, Any],
        query: str = "",
        sort_by: str = "relevance",
        skip: int = 0,
        limit: int = 5,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "q": query,
            "skip": skip,
            "limit": limit,
            "sort_by": sort_by,
        }
        for k, v in filters.items():
            if v is None or v == "" or v == []:
                continue
            if isinstance(v, list):
                params[k] = ",".join(str(x) for x in v if x not in (None, ""))
            else:
                params[k] = v

        try:
            resp = await self._client.get(
                self._url, params=params, headers=self._headers or None,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            logger.error("[REAL-ESTATE] HTTP error: %s", exc)
            return {"items": [], "total": 0, "metadata": {"error": str(exc)}}

        if isinstance(data, list):
            return {"items": data, "total": len(data)}
        items = data.get("items") or data.get("properties") or []
        total = int(data.get("total") or len(items))
        return {"items": items, "total": total}

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# Tiny in-memory fallback so the CLI is still playable without a real backend.
# ---------------------------------------------------------------------------

_DEMO_PROPERTIES: List[Dict[str, Any]] = [
    {"id": "rp1", "title": "Studio meublé climatisé Tokoin", "city": "Lomé", "quartier": "Tokoin", "property_type": "studio", "transaction_type": "location", "loyer_mensuel": 80000, "chambres": 1, "amenities": ["meuble", "climatisation"]},
    {"id": "rp2", "title": "Chambre étudiante Adidogomé", "city": "Lomé", "quartier": "Adidogomé", "property_type": "chambre", "transaction_type": "location", "loyer_mensuel": 35000, "chambres": 1, "amenities": []},
    {"id": "rp3", "title": "Villa 4 chambres avec piscine Agoè", "city": "Lomé", "quartier": "Agoè", "property_type": "villa", "transaction_type": "location", "loyer_mensuel": 450000, "chambres": 4, "amenities": ["piscine", "garage", "climatisation"]},
    {"id": "rp4", "title": "Appartement 3 chambres Bè", "city": "Lomé", "quartier": "Bè", "property_type": "appartement", "transaction_type": "location", "loyer_mensuel": 150000, "chambres": 3, "amenities": ["wc_douche_interne", "carrelage"]},
    {"id": "rp5", "title": "Maison à vendre Kara centre", "city": "Kara", "quartier": "Centre", "property_type": "maison", "transaction_type": "vente", "prix_vente": 25000000, "chambres": 5, "amenities": ["cour", "cloture"]},
    {"id": "rp6", "title": "Terrain 600m² Kpalimé", "city": "Kpalimé", "quartier": "", "property_type": "terrain", "transaction_type": "vente", "prix_vente": 8000000, "chambres": 0, "amenities": []},
    {"id": "rp7", "title": "Studio meublé Lomé Nyékonakpoè", "city": "Lomé", "quartier": "Nyékonakpoè", "property_type": "studio", "transaction_type": "location", "loyer_mensuel": 120000, "chambres": 1, "amenities": ["meuble", "wifi", "climatisation"]},
    {"id": "rp8", "title": "Villa 3 chambres Sokodé", "city": "Sokodé", "quartier": "", "property_type": "villa", "transaction_type": "location", "loyer_mensuel": 180000, "chambres": 3, "amenities": ["garage", "cour"]},
]


class InMemoryRealEstateCatalog(CatalogBackend):
    """Tiny demo catalog -- avoids needing a real backend just to play."""

    def __init__(self, properties: Optional[List[Dict[str, Any]]] = None) -> None:
        self._props = list(properties or _DEMO_PROPERTIES)

    async def search(
        self,
        filters: Dict[str, Any],
        query: str = "",
        sort_by: str = "relevance",
        skip: int = 0,
        limit: int = 5,
    ) -> Dict[str, Any]:
        items = list(self._props)

        def _norm(s: Any) -> str:
            return str(s or "").strip().lower()

        if filters.get("city"):
            items = [p for p in items if _norm(p.get("city")) == _norm(filters["city"])]
        if filters.get("quartier"):
            items = [p for p in items if _norm(filters["quartier"]) in _norm(p.get("quartier"))]
        if filters.get("property_type"):
            items = [p for p in items if _norm(p.get("property_type")) == _norm(filters["property_type"])]
        if filters.get("transaction_type"):
            items = [p for p in items if _norm(p.get("transaction_type")) == _norm(filters["transaction_type"])]
        if filters.get("min_chambres"):
            items = [p for p in items if int(p.get("chambres") or 0) >= int(filters["min_chambres"])]
        if filters.get("min_price") is not None:
            items = [p for p in items if (p.get("loyer_mensuel") or p.get("prix_vente") or 0) >= float(filters["min_price"])]
        if filters.get("max_price") is not None:
            items = [p for p in items if (p.get("loyer_mensuel") or p.get("prix_vente") or 0) <= float(filters["max_price"])]
        if filters.get("amenities"):
            wanted = {a.lower() for a in filters["amenities"]}
            items = [p for p in items if wanted.issubset({a.lower() for a in (p.get("amenities") or [])})]
        if filters.get("exclude_property_types"):
            excluded = {x.lower() for x in filters["exclude_property_types"]}
            items = [p for p in items if _norm(p.get("property_type")) not in excluded]

        if query:
            tokens = [t for t in query.lower().split() if t]
            for tok in tokens:
                items = [p for p in items if tok in _norm(p.get("title")) or tok in _norm(p.get("quartier"))]

        if sort_by == "price_asc":
            items.sort(key=lambda p: p.get("loyer_mensuel") or p.get("prix_vente") or 0)
        elif sort_by == "price_desc":
            items.sort(key=lambda p: -(p.get("loyer_mensuel") or p.get("prix_vente") or 0))
        elif sort_by == "newest":
            items.sort(key=lambda p: p.get("id"), reverse=True)

        total = len(items)
        page = items[skip:skip + limit]
        return {"items": page, "total": total}

    async def aclose(self) -> None:
        return None
