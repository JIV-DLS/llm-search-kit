"""Unit tests for the Beasyapp Spring-Boot CatalogBackend adapter.

We never hit the real network here -- ``httpx.MockTransport`` lets us
intercept the exact ``SearchRequest`` body the adapter produces, return
canned ``SearchResponse`` payloads, and assert the round-trip.

For end-to-end verification against the live backend, see
``tests/test_beasyapp_live.py`` (skipped unless ``BEASY_LIVE=1``).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx
import pytest

from llm_search_kit.examples.beasyapp_backend import (
    BeasyappAPIError,
    BeasyappCatalog,
    build_schema,
    scrub_listing,
)


# --------------------------------------------------------------------- helpers


def _stub_response(
    *,
    listings: List[Dict[str, Any]] | None = None,
    total: int = 0,
    facets: Dict[str, Any] | None = None,
    status: int = 200,
):
    """Build an ``httpx.MockTransport`` handler that returns a canned payload
    and records every captured request on ``handler.captured``.
    """
    captured: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        body = {
            "listings":      listings or [],
            "totalElements": total,
            "totalPages":    1 if total else 0,
            "currentPage":   0,
            "facets":        facets or {},
        }
        return httpx.Response(status, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    handler.captured = captured  # type: ignore[attr-defined]
    return client, captured


def _body(req: httpx.Request) -> Dict[str, Any]:
    return json.loads(req.content.decode("utf-8") or "{}")


# --------------------------------------------------------------------- scrub


def test_scrub_listing_removes_creator_pii():
    raw = {
        "id": 1,
        "title": "TV",
        "creator": {
            "id": 7, "username": "alice", "fullName": "Alice", "avatar": None,
            "email": "alice@x.com", "password": "$2a$10$xxx", "phone": "+228...",
            "addresses": [{"city": "Lomé", "street": "rue 1"}],
            "defaultShippingAddress": {"city": "Lomé", "country": "TG", "street": "rue 1"},
            "sellerAverageRating": 4.5, "sellerRatingCount": 12,
        },
        "reviews": [{"text": "great"}],
    }

    cleaned = scrub_listing(raw)

    creator = cleaned["creator"]
    assert creator == {
        "id": 7, "username": "alice", "fullName": "Alice", "avatar": None,
        "sellerAverageRating": 4.5, "sellerRatingCount": 12,
        "city": "Lomé", "country": "TG",
    }
    # Forbidden fields are gone:
    assert "email"     not in creator
    assert "password"  not in creator
    assert "phone"     not in creator
    assert "addresses" not in creator
    assert "street"    not in str(creator)
    # Reviews dropped to keep the LLM context lean:
    assert "reviews" not in cleaned


def test_scrub_listing_trims_categories_and_brand():
    raw = {
        "id": 1, "title": "TV",
        "categories": [
            {"id": 60, "nameEn": "4K TVs", "nameFr": "4K TVs", "subCategories": [{"id": 99}]},
            {"id": 3, "nameEn": "Electronics", "nameFr": "Électronique", "image": "http://x"},
        ],
        "brand": {"id": 1, "name": "Samsung", "internalNote": "secret"},
    }

    cleaned = scrub_listing(raw)

    assert cleaned["categories"] == [
        {"id": 60, "nameEn": "4K TVs", "nameFr": "4K TVs"},
        {"id": 3,  "nameEn": "Electronics", "nameFr": "Électronique"},
    ]
    assert cleaned["brand"] == {"id": 1, "name": "Samsung"}


# --------------------------------------------------------------------- request body


@pytest.mark.asyncio
async def test_minimal_search_emits_correct_pagination_and_defaults():
    client, captured = _stub_response(total=0)
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    out = await catalog.search(filters={}, query="", limit=10)

    assert out["total"] == 0
    assert out["items"] == []
    assert len(captured) == 1
    body = _body(captured[0])
    assert body["page"] == 0
    assert body["size"] == 10
    assert body["sortBy"] == "RELEVANCE"
    assert body["includeFacets"] is True
    assert "query" not in body  # empty query -> omitted


@pytest.mark.asyncio
async def test_skip_translates_to_zero_indexed_page():
    client, captured = _stub_response(total=100)
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(filters={}, query="x", skip=40, limit=20)

    body = _body(captured[0])
    assert body["page"] == 2  # 40 // 20
    assert body["size"] == 20


@pytest.mark.asyncio
async def test_filters_are_renamed_to_camelcase():
    client, captured = _stub_response()
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(
        filters={
            "category_ids":  [1, 60],
            "brand_ids":     [1],
            "min_price":     10000,
            "max_price":     100000,
            "min_rating":    4.5,
            "color":         "#000000",
            "city":          "Lomé",
            "country":       "TG",
            "debatable":     True,
            "has_discount":  True,
            "in_stock":      True,
            "delivery_type": "ASIGANME",
        },
        query="tv samsung",
    )

    body = _body(captured[0])
    assert body["query"]        == "tv samsung"
    assert body["categoryIds"]  == [1, 60]
    assert body["brandIds"]     == [1]
    assert body["minPrice"]     == 10000
    assert body["maxPrice"]     == 100000
    assert body["minRating"]    == 4.5
    assert body["color"]        == "#000000"
    assert body["city"]         == "Lomé"
    assert body["country"]      == "TG"
    assert body["debatable"]    is True
    assert body["hasDiscount"]  is True
    assert body["inStock"]      is True
    assert body["deliveryType"] == "ASIGANME"


@pytest.mark.asyncio
async def test_geo_filters_attach_radius_and_filter_by_radius_defaults():
    client, captured = _stub_response()
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(
        filters={"latitude": 6.13, "longitude": 1.22},
        query="",
    )

    body = _body(captured[0])
    assert body["latitude"] == 6.13
    assert body["longitude"] == 1.22
    assert body["radiusKm"] == 50.0
    assert body["filterByRadius"] is False


@pytest.mark.asyncio
async def test_geo_filter_honors_explicit_radius_and_filter_by_radius():
    client, captured = _stub_response()
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(
        filters={
            "latitude": 6.13, "longitude": 1.22,
            "radius_km": 5, "filter_by_radius": True,
        },
        query="",
    )

    body = _body(captured[0])
    assert body["radiusKm"] == 5
    assert body["filterByRadius"] is True


@pytest.mark.asyncio
async def test_empty_filter_values_are_omitted():
    client, captured = _stub_response()
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(
        filters={"city": "", "brand_ids": [], "min_price": None,
                 "max_price": 0,  # zero is a valid filter, must NOT be dropped
                 "in_stock": False},  # explicit False is meaningful too
        query="",
    )

    body = _body(captured[0])
    assert "city"      not in body
    assert "brandIds"  not in body
    assert "minPrice"  not in body
    assert body["maxPrice"] == 0
    assert body["inStock"]  is False


# --------------------------------------------------------------------- sort


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_by,expected", [
    ("",            "RELEVANCE"),
    ("relevance",   "RELEVANCE"),
    ("price_asc",   "PRICE_ASC"),
    ("priceAsc",    "PRICE_ASC"),
    ("price_desc",  "PRICE_DESC"),
    ("newest",      "NEWEST"),
    ("recent",      "NEWEST"),
    ("rating",      "RATING"),
    ("proximity",   "PROXIMITY"),
    ("nearest",     "PROXIMITY"),
    ("garbage_xyz", "RELEVANCE"),  # safe fallback
])
async def test_sort_by_aliases_map_to_backend_enum(sort_by, expected):
    client, captured = _stub_response()
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(filters={}, query="", sort_by=sort_by)

    assert _body(captured[0])["sortBy"] == expected


# --------------------------------------------------------------------- response


@pytest.mark.asyncio
async def test_response_is_normalised_to_kit_shape_and_listings_are_scrubbed():
    listings = [
        {"id": 1, "title": "TV", "price": 50000,
         "creator": {"id": 7, "username": "u", "email": "x@y.z",
                     "password": "hash", "phone": "+228..."}},
    ]
    facets = {"brands": [{"key": "1", "label": "Samsung", "count": 4}]}
    client, _ = _stub_response(listings=listings, total=42, facets=facets)
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    out = await catalog.search(filters={}, query="x")

    assert out["total"] == 42
    assert out["items"][0]["title"] == "TV"
    creator = out["items"][0]["creator"]
    assert creator["username"] == "u"
    assert "email" not in creator
    assert "password" not in creator
    assert "phone" not in creator
    assert out["metadata"]["facets"]["brands"][0]["label"] == "Samsung"


@pytest.mark.asyncio
async def test_listing_transform_can_be_overridden():
    client, _ = _stub_response(listings=[{"id": 1, "title": "X"}], total=1)

    def upper(item):
        return {**item, "title": item["title"].upper()}

    catalog = BeasyappCatalog(base_url="http://test", client=client,
                              listing_transform=upper)
    out = await catalog.search(filters={}, query="")

    assert out["items"][0]["title"] == "X"


@pytest.mark.asyncio
async def test_zero_results_returns_empty_payload_not_an_error():
    client, _ = _stub_response(listings=[], total=0)
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    out = await catalog.search(filters={"max_price": 1}, query="")

    assert out == {
        "items": [],
        "total": 0,
        "metadata": {
            "totalPages": 0, "currentPage": 0, "facets": {},
        },
    }


# --------------------------------------------------------------------- errors


@pytest.mark.asyncio
async def test_http_error_raises_beasyapp_error():
    def handler(request):
        return httpx.Response(503, text="Service Unavailable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                               base_url="http://test")
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    with pytest.raises(BeasyappAPIError, match="HTTP 503"):
        await catalog.search(filters={}, query="x")


@pytest.mark.asyncio
async def test_non_json_response_raises_beasyapp_error():
    def handler(request):
        return httpx.Response(200, content=b"<html>oops</html>",
                              headers={"content-type": "text/html"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                               base_url="http://test")
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    with pytest.raises(BeasyappAPIError, match="non-JSON"):
        await catalog.search(filters={}, query="x")


# --------------------------------------------------------------------- schema


def test_schema_compiles_to_openai_parameters():
    params = build_schema().to_openai_parameters()

    assert params["type"] == "object"
    props = params["properties"]
    assert {"category_ids", "brand_ids", "min_price", "max_price", "color",
            "city", "country", "debatable", "has_discount", "in_stock",
            "delivery_type", "latitude", "longitude"} <= set(props)

    # Array fields must declare their item type so OpenAI accepts the schema.
    assert props["category_ids"]["type"] == "array"
    assert props["category_ids"]["items"] == {"type": "integer"}
    assert props["brand_ids"]["items"]    == {"type": "integer"}

    # Enum is exposed for delivery_type:
    assert sorted(props["delivery_type"]["enum"]) == ["ASIGANME", "USER"]


def test_schema_drop_priority_does_not_drop_category():
    schema = build_schema()
    assert "category_ids" not in schema.drop_priority
    assert schema.core_keys == {"category_ids"}


# --------------------------------------------------------------------- headers


@pytest.mark.asyncio
async def test_default_headers_include_ngrok_skip_warning():
    captured: List[httpx.Request] = []

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"listings": [], "totalElements": 0,
                                         "totalPages": 0, "currentPage": 0,
                                         "facets": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                               base_url="http://test")
    catalog = BeasyappCatalog(base_url="http://test", client=client)

    await catalog.search(filters={}, query="")

    headers = captured[0].headers
    assert headers["content-type"] == "application/json"
    assert headers["ngrok-skip-browser-warning"] == "true"


@pytest.mark.asyncio
async def test_custom_headers_are_merged_with_defaults():
    captured: List[httpx.Request] = []

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"listings": [], "totalElements": 0,
                                         "totalPages": 0, "currentPage": 0,
                                         "facets": {}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                               base_url="http://test")
    catalog = BeasyappCatalog(
        base_url="http://test", client=client,
        headers={"Authorization": "Bearer XYZ"},
    )

    await catalog.search(filters={}, query="")

    h = captured[0].headers
    assert h["authorization"] == "Bearer XYZ"
    assert h["ngrok-skip-browser-warning"] == "true"
