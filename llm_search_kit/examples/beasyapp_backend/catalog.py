"""``CatalogBackend`` adapter that calls a remote Spring Boot search endpoint.

Targets the ``POST /api/v1/listings/search`` endpoint described by Armand's
``SearchRequest`` / ``SearchResponse`` DTOs.

Mapping table (kit filter key -> ``SearchRequest`` field):

    query              -> query
    min_price          -> minPrice
    max_price          -> maxPrice
    category_ids       -> categoryIds        (list[int])
    brand_ids          -> brandIds           (list[int])
    debatable          -> debatable          (bool)
    has_discount       -> hasDiscount        (bool)
    in_stock           -> inStock            (bool)
    delivery_type      -> deliveryType       ("USER" | "ASIGANME")
    min_rating         -> minRating
    color              -> color              (hex string from facets, e.g. "#000000")
    city               -> city
    country            -> country
    attributes         -> attributes         (list of {attributeId, values})
    latitude/longitude -> latitude/longitude (+ radiusKm, filterByRadius)

Sort mapping (kit ``sort_by`` -> ``SortOption``):

    relevance | ""        -> RELEVANCE
    price_asc | priceAsc  -> PRICE_ASC
    price_desc            -> PRICE_DESC
    newest | recent       -> NEWEST
    rating                -> RATING
    proximity | nearest   -> PROXIMITY

Pagination: the kit uses ``skip`` (offset) but the backend uses ``page``
(0-indexed) + ``size``. We translate ``page = skip // limit``.

PII scrubbing: every listing passes through :func:`scrub_listing` before
it is returned. We strip ``creator.email``, ``creator.password``,
``creator.phone``, addresses, etc., and keep only what an LLM/UI needs
to recommend the item. Override the scrubbing by passing your own
``listing_transform`` callable to the constructor.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# Sort aliases the LLM is likely to emit -> backend SortOption enum value.
_SORT_MAP: Dict[str, str] = {
    "":           "RELEVANCE",
    "relevance":  "RELEVANCE",
    "price_asc":  "PRICE_ASC",
    "priceasc":   "PRICE_ASC",
    "price_desc": "PRICE_DESC",
    "pricedesc":  "PRICE_DESC",
    "newest":     "NEWEST",
    "recent":     "NEWEST",
    "rating":     "RATING",
    "proximity":  "PROXIMITY",
    "nearest":    "PROXIMITY",
}


# Whitelist of creator fields we are willing to expose. Email, phone,
# password, addresses, etc. are intentionally NOT in this set.
_SAFE_CREATOR_FIELDS = (
    "id", "username", "fullName", "avatar", "sellerAverageRating",
    "sellerRatingCount",
)


class BeasyappAPIError(RuntimeError):
    """Raised when the remote search endpoint returns a non-2xx response."""


def scrub_listing(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a defensive copy of ``raw`` with PII removed.

    Drops embedded user credentials/contacts and trims overly verbose
    nested category trees down to ``{id, nameEn, nameFr}`` so the LLM
    isn't fed 50 KB of cruft per listing.
    """
    cleaned: Dict[str, Any] = {}
    for k, v in raw.items():
        if k == "creator" and isinstance(v, dict):
            cleaned["creator"] = {fk: v.get(fk) for fk in _SAFE_CREATOR_FIELDS
                                  if fk in v}
            # Surface only the seller's *city*, never their full address.
            shipping = v.get("defaultShippingAddress") or {}
            if isinstance(shipping, dict) and shipping.get("city"):
                cleaned["creator"]["city"] = shipping["city"]
                cleaned["creator"]["country"] = shipping.get("country")
            continue
        if k == "categories" and isinstance(v, list):
            cleaned["categories"] = [
                {kk: cat.get(kk) for kk in ("id", "nameEn", "nameFr")
                 if kk in cat}
                for cat in v if isinstance(cat, dict)
            ]
            continue
        if k == "brand" and isinstance(v, dict):
            cleaned["brand"] = {kk: v.get(kk)
                                for kk in ("id", "name", "nameEn", "nameFr")
                                if kk in v}
            continue
        if k == "reviews":
            continue  # avoid dumping user reviews into the LLM context
        cleaned[k] = v
    return cleaned


class BeasyappCatalog:
    """``CatalogBackend`` for the Beasyapp Spring Boot search endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        endpoint: str = "/api/v1/listings/search",
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 20.0,
        headers: Optional[Dict[str, str]] = None,
        include_facets: bool = True,
        listing_transform: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = scrub_listing,
        radius_km_default: float = 50.0,
        filter_by_radius_default: bool = False,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout
        self._headers = {
            "Content-Type":               "application/json",
            "Accept":                     "application/json",
            "ngrok-skip-browser-warning": "true",
            **(headers or {}),
        }
        self._include_facets = include_facets
        self._transform = listing_transform or (lambda x: x)
        self._radius_km_default = radius_km_default
        self._filter_by_radius_default = filter_by_radius_default

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ----------------------------------------------------- CatalogBackend
    async def search(
        self,
        filters: Dict[str, Any],
        query: str = "",
        sort_by: str = "relevance",
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        body = self._build_body(filters, query, sort_by, skip, limit)
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            url = f"{self._base_url}{self._endpoint}"
            logger.debug("[BEASY] POST %s body=%s", url, body)
            resp = await client.post(url, json=body, headers=self._headers)
        finally:
            if self._client is None:
                await client.aclose()

        if resp.status_code >= 400:
            text = (resp.text or "")[:500]
            raise BeasyappAPIError(
                f"Beasyapp search failed: HTTP {resp.status_code} -- {text}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise BeasyappAPIError("Beasyapp search returned non-JSON body") from exc

        listings = payload.get("listings") or []
        items = [self._transform(item) for item in listings if isinstance(item, dict)]

        return {
            "items": items,
            "total": int(payload.get("totalElements", len(items)) or 0),
            "metadata": {
                "totalPages":  payload.get("totalPages"),
                "currentPage": payload.get("currentPage"),
                "facets":      payload.get("facets") if self._include_facets else None,
            },
        }

    # ----------------------------------------------------- internals
    def _build_body(
        self,
        filters: Dict[str, Any],
        query: str,
        sort_by: str,
        skip: int,
        limit: int,
    ) -> Dict[str, Any]:
        size = max(1, int(limit or 20))
        page = max(0, int(skip or 0)) // size

        body: Dict[str, Any] = {
            "page":          page,
            "size":          size,
            "sortBy":        _SORT_MAP.get((sort_by or "").strip().lower(), "RELEVANCE"),
            "includeFacets": bool(self._include_facets),
        }
        if query:
            body["query"] = query

        # Direct passthroughs (only set when present so the backend's
        # builder defaults stay in effect for what we omit).
        passthrough = {
            "min_price":     "minPrice",
            "max_price":     "maxPrice",
            "category_ids":  "categoryIds",
            "brand_ids":     "brandIds",
            "debatable":     "debatable",
            "has_discount":  "hasDiscount",
            "in_stock":      "inStock",
            "delivery_type": "deliveryType",
            "min_rating":    "minRating",
            "color":         "color",
            "city":          "city",
            "country":       "country",
            "attributes":    "attributes",
            "latitude":      "latitude",
            "longitude":     "longitude",
        }
        for src, dst in passthrough.items():
            v = filters.get(src)
            if v is None or v == "" or v == []:
                continue
            body[dst] = v

        # Geo: only attach radius/filterByRadius if the caller asked for geo.
        if "latitude" in body and "longitude" in body:
            body.setdefault("radiusKm",       filters.get("radius_km",
                                                          self._radius_km_default))
            body.setdefault("filterByRadius", bool(filters.get(
                "filter_by_radius", self._filter_by_radius_default)))

        return body
