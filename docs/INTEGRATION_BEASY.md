# Integration guide — plugging `llm-search-kit` into the existing Beasyapp Spring backend

This is the **most realistic** integration scenario shipped in the kit:

> *"I already have a working Spring Boot search endpoint. I don't want a
> second database, I don't want ETL, I just want a chat box that calls
> my existing endpoint."*

That's exactly what `llm_search_kit.examples.beasyapp_backend` does. It
maps the kit's generic `CatalogBackend` shape onto the real
`POST /api/v1/listings/search` endpoint and its `SearchRequest` /
`SearchResponse` DTOs, scrubs PII out of each listing, and exposes the
backend's facets to the assistant so it can suggest refinements.

> 📦 **Files referenced in this guide**
> - [`llm_search_kit/examples/beasyapp_backend/catalog.py`](../llm_search_kit/examples/beasyapp_backend/catalog.py) — the adapter
> - [`llm_search_kit/examples/beasyapp_backend/schema.py`](../llm_search_kit/examples/beasyapp_backend/schema.py) — the search surface exposed to the LLM
> - [`llm_search_kit/examples/beasyapp_backend/soul.md`](../llm_search_kit/examples/beasyapp_backend/soul.md) — the assistant's system prompt
> - [`llm_search_kit/examples/beasyapp_backend/run.py`](../llm_search_kit/examples/beasyapp_backend/run.py) — CLI runner
> - [`tests/test_beasyapp_backend.py`](../tests/test_beasyapp_backend.py) — 28 unit tests with mocked HTTP
> - [`tests/test_beasyapp_live.py`](../tests/test_beasyapp_live.py) — 9 live tests against the real backend (opt-in)

---

## TL;DR — try it in 30 seconds

```bash
git clone https://github.com/JIV-DLS/llm-search-kit.git && cd llm-search-kit
pip install -e ".[dev]"

# 1) Probe the backend, no LLM at all:
python -m llm_search_kit.examples.beasyapp_backend.run --probe -q "samsung"

# 2) Run the live integration tests against the real Beasyapp backend:
BEASY_LIVE=1 pytest tests/test_beasyapp_live.py -v

# 3) Talk to the assistant (needs LLM_API_KEY set in .env):
cp .env.example .env       # paste OPENAI/Groq/etc. credentials
python -m llm_search_kit.examples.beasyapp_backend.run \
    -q "samsung tv 4K under 100000 FCFA"
```

---

## 1. The mapping table (kit ↔ Spring `SearchRequest`)

| LLM emits (kit name)     | Goes into `SearchRequest` field | Notes                                               |
|--------------------------|---------------------------------|-----------------------------------------------------|
| `query`                  | `query`                         | Free-text part of the user's intent                 |
| `category_ids` (`int[]`) | `categoryIds`                   | LLM picks ids from facets metadata                  |
| `brand_ids` (`int[]`)    | `brandIds`                      | LLM picks ids from facets metadata                  |
| `min_price` (number)     | `minPrice`                      | FCFA                                                |
| `max_price` (number)     | `maxPrice`                      | FCFA                                                |
| `min_rating` (number)    | `minRating`                     | 0–5                                                 |
| `color` (string)         | `color`                         | Hex string (e.g. `"#000000"`) as in your facets     |
| `city`, `country`        | `city`, `country`               | Direct passthrough                                  |
| `debatable` (bool)       | `debatable`                     |                                                     |
| `has_discount` (bool)    | `hasDiscount`                   |                                                     |
| `in_stock` (bool)        | `inStock`                       |                                                     |
| `delivery_type` (enum)   | `deliveryType`                  | `"USER"` or `"ASIGANME"`                            |
| `latitude`, `longitude`  | `latitude`, `longitude`         | Adapter auto-attaches `radiusKm` + `filterByRadius` |
| `radius_km` (number)     | `radiusKm`                      | Defaults to 50                                      |
| `filter_by_radius` (bool)| `filterByRadius`                | Defaults to `false` (sort-by-proximity, not filter) |
| `skip` (offset)          | computed `page`                 | `page = skip // size`                               |
| `limit`                  | `size`                          | Defaults to 20 on Spring side                       |
| `sort_by`                | `sortBy` (`SortOption` enum)    | See aliases table below                             |

### Sort aliases

| LLM may emit                         | Backend `SortOption` |
|--------------------------------------|----------------------|
| `relevance` / `""`                   | `RELEVANCE`          |
| `price_asc` / `priceAsc`             | `PRICE_ASC`          |
| `price_desc` / `priceDesc`           | `PRICE_DESC`         |
| `newest` / `recent`                  | `NEWEST`             |
| `rating`                             | `RATING`             |
| `proximity` / `nearest`              | `PROXIMITY`          |
| anything else                        | `RELEVANCE` (fallback) |

---

## 2. PII scrubbing — security contract

The Beasyapp `SearchResponse.listings[i].creator` object includes
**email, password hash, phone, full address, addresses[]** and other
sensitive seller data. The adapter passes every listing through
`scrub_listing` before exposing it to the LLM and to the frontend.

What stays in `creator`:

- `id`, `username`, `fullName`, `avatar`
- `sellerAverageRating`, `sellerRatingCount`
- `city`, `country` (extracted from `defaultShippingAddress`)

What is removed:

- `email`, `password`, `phone`
- `addresses`, `defaultBillingAddress`, `defaultShippingAddress.street`, …
- `reviews` (kept off the LLM context to save tokens)

The contract is **enforced by tests**:

- Unit test `test_scrub_listing_removes_creator_pii` locks down the
  scrubbing on a hand-crafted payload.
- **Live** test `_assert_kit_shape` asserts every real response from the
  backend has no `email`/`password`/`phone`/`addresses` in any
  `creator` block. If Armand's backend ever adds a new sensitive field,
  CI catches it the next time someone runs `BEASY_LIVE=1 pytest`.

If you need to keep more (or strip less), pass your own
`listing_transform` callable:

```python
catalog = BeasyappCatalog(
    base_url="https://...",
    listing_transform=lambda raw: {
        "id": raw["id"], "title": raw["title"], "price": raw["price"],
    },
)
```

---

## 3. Wiring in your own Spring app

You don't have to be on Beasyapp — anyone whose backend looks like
"POST a JSON filter, get back `{listings, totalElements, ...}`" can
copy `BeasyappCatalog` and tweak two methods:

- `_build_body(filters, query, sort_by, skip, limit)` — rename the keys.
- the unpacking inside `search()` — rename `listings` / `totalElements`.

Everything else (PII scrubbing, sort aliases, geo, error handling, the
`metadata.facets` pass-through) stays the same.

A minimal Flask front-door that calls this adapter in front of an
existing backend looks like this:

```python
from flask import Flask, jsonify, request
import asyncio

from llm_search_kit import AgentEngine, SearchCatalogSkill
from llm_search_kit.config import build_default_llm_client
from llm_search_kit.examples.beasyapp_backend import BeasyappCatalog, build_schema

app = Flask(__name__)

LLM     = build_default_llm_client()
CATALOG = BeasyappCatalog(base_url="https://your-spring-app.example.com")
SKILL   = SearchCatalogSkill(schema=build_schema(), backend=CATALOG)
ENGINE  = AgentEngine(llm_client=LLM, system_prompt=open("soul.md").read())
ENGINE.register_skill(SKILL)

@app.post("/chat")
def chat():
    payload = request.get_json(force=True) or {}
    result  = asyncio.run(ENGINE.process(payload["message"]))
    return jsonify({
        "reply":    result["reply"],
        "products": (result.get("data") or {}).get("items", []),
    })
```

For the full version with session memory, see
[`examples/flask_server/app.py`](../llm_search_kit/examples/flask_server/app.py).

---

## 4. Test scenarios covered

### Unit (`tests/test_beasyapp_backend.py`, **28 tests**)

| Concern                          | Tests                                                                                                        |
|----------------------------------|--------------------------------------------------------------------------------------------------------------|
| **PII scrubbing**                | `test_scrub_listing_removes_creator_pii`, `test_scrub_listing_trims_categories_and_brand`                    |
| **Request body shape**           | `test_minimal_search_emits_correct_pagination_and_defaults`, `test_skip_translates_to_zero_indexed_page`, `test_filters_are_renamed_to_camelcase`, `test_empty_filter_values_are_omitted` |
| **Geolocation**                  | `test_geo_filters_attach_radius_and_filter_by_radius_defaults`, `test_geo_filter_honors_explicit_radius_and_filter_by_radius` |
| **Sort aliases (12 cases)**      | `test_sort_by_aliases_map_to_backend_enum[…]`                                                                |
| **Response normalisation**       | `test_response_is_normalised_to_kit_shape_and_listings_are_scrubbed`, `test_zero_results_returns_empty_payload_not_an_error`, `test_listing_transform_can_be_overridden` |
| **Error handling**               | `test_http_error_raises_beasyapp_error`, `test_non_json_response_raises_beasyapp_error`                      |
| **Schema correctness**           | `test_schema_compiles_to_openai_parameters`, `test_schema_drop_priority_does_not_drop_category`              |
| **Headers (ngrok / auth)**       | `test_default_headers_include_ngrok_skip_warning`, `test_custom_headers_are_merged_with_defaults`            |

### Live (`tests/test_beasyapp_live.py`, **9 tests, opt-in via `BEASY_LIVE=1`**)

These run against the actual deployment. They assert *contracts*, not
specific catalog contents, so they keep passing as Armand's data evolves.

| Scenario                          | Assertion                                                          |
|-----------------------------------|--------------------------------------------------------------------|
| Free-text search returns kit-shape | `{items, total, metadata}` valid; PII scrubbed                    |
| Match-all returns at least 1      | Demo catalog non-empty                                             |
| Facets returned                    | At least one of `brands` / `cities` / `colors` / `priceRanges` …  |
| Price range respected              | Every returned price is within `[min_price, max_price]`            |
| Impossible filter → zero           | `total == 0`, `items == []`                                        |
| `price_asc` is monotonic           | Returned prices are sorted ascending                              |
| `price_desc` is monotonic          | Returned prices are sorted descending                             |
| Pagination disjoint                | Page 0 ids ∩ page 1 ids == ∅ (when total ≥ 6)                     |
| Relaxation ladder runs end-to-end  | Over-constrained query succeeds via `SearchCatalogSkill`'s relaxation |

Run them with:

```bash
BEASY_LIVE=1 pytest tests/test_beasyapp_live.py -v
# or against a different deployment:
BEASY_LIVE=1 BEASY_BASE_URL=https://your-tunnel.example.com pytest tests/test_beasyapp_live.py -v
```

---

## 5. Operational checklist

Before shipping this to production:

- [ ] Replace the in-process `sessions` dict in the Flask example with
      Redis (or any shared store) so chat history survives across
      processes.
- [ ] Add an `Authorization: Bearer <jwt>` header by passing
      `headers={"Authorization": ...}` to `BeasyappCatalog` once your
      Spring endpoint is no longer publicly accessible.
- [ ] Set `LLM_FALLBACK_*` env vars so the kit's `ResilientLLMClient`
      can fail over from the primary provider to a secondary one.
- [ ] Cap costs with `AgentEngine(max_iterations=5)` and prefer cheap
      models (`gpt-4o-mini`, `groq/llama-3.1-8b-instant`,
      `openrouter/anthropic/claude-3-haiku`).
- [ ] Pre-load brand/category id ↔ name mappings from your `/brands`
      and `/categories` endpoints once at startup and inject them into
      the `soul.md` prompt so the LLM can map "Samsung" → `brand_ids:[1]`
      reliably without depending on facet drift.
- [ ] Add structured logging on the Flask side (`request_id`,
      `session_id`, `tool_calls`, `relaxation_level`) so you can debug
      what the agent did per user turn.
