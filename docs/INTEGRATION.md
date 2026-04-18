# Integration guide — plugging `llm-search-kit` into your app

This guide is for someone who already has:

- a product database (in our worked example: **Elasticsearch**),
- a backend API (in our worked example: **Flask**),
- a frontend that wants a "natural-language search" / "chat" feature.

Goal: by the end of this page you will have an HTTP endpoint
`POST /chat` that takes `{message, session_id}` and returns
`{reply, products}`, powered by your real catalog.

The kit ships **two ready-to-run reference implementations** that match this
guide one-to-one:

- [`examples/elasticsearch_catalog/`](../llm_search_kit/examples/elasticsearch_catalog/) — a real `CatalogBackend` against Elasticsearch
- [`examples/flask_server/`](../llm_search_kit/examples/flask_server/) — a Flask app that exposes `/chat`

Copy them, change the field names, done.

---

## Mental model in 60 seconds

```
┌────────────┐    POST /chat     ┌──────────────┐
│  Frontend  │ ─────────────────►│  Flask app   │
└────────────┘                   │ (your code)  │
       ▲                         └──────┬───────┘
       │                                │ engine.process(message, history)
       │                                ▼
       │                         ┌──────────────┐
       │                         │ AgentEngine  │ (kit)
       │                         └──────┬───────┘
       │                                │ chat/completions + tool_calls
       │                                ▼
       │                         ┌──────────────┐
       │                         │   OpenAI /   │
       │                         │  Groq / etc  │
       │                         └──────┬───────┘
       │                                │ tool_call: search_catalog(filters)
       │                                ▼
       │                         ┌──────────────┐
       │                         │SearchCatalog │ (kit)
       │                         │    Skill     │
       │                         └──────┬───────┘
       │                                │ backend.search(filters, query, …)
       │                                ▼
       │                         ┌──────────────┐
       └─────────  reply ────────│ YOUR catalog │
                  + items        │  (Elastic-   │
                                 │   search)    │
                                 └──────────────┘
```

You write **two things**:

1. A `CatalogBackend` — one async method that takes filters and returns
   `{items, total}` from your data source.
2. A `SearchSchema` — declarative description of the filters the LLM is
   allowed to extract.

The kit handles the LLM round-trips, JSON parsing, retries, fallback,
relaxation when results are empty, and assembling the final reply.

---

## Step 1 — describe your search surface (`schema.py`)

A `SearchSchema` is just "what filters can the user mention?" It becomes the
JSON-Schema parameters of the tool the LLM sees.

```python
# my_app/llm_search/schema.py
from llm_search_kit.search import SearchField, SearchSchema

CATEGORIES = ["shoes", "shirts", "phones", "laptops", "headphones"]
COLORS     = ["red", "blue", "green", "black", "white", "grey"]

def build_schema() -> SearchSchema:
    return SearchSchema(
        fields=[
            SearchField("category",   "string",  enum=CATEGORIES,
                        description="Top-level product category."),
            SearchField("brand",      "string",
                        description="Brand name (Nike, Apple, Sony, ...)."),
            SearchField("color",      "string",  enum=COLORS),
            SearchField("size",       "string",
                        description="Size as written by the user (42, M, ...)."),
            SearchField("min_price",  "number",  description="Minimum price USD."),
            SearchField("max_price",  "number",  description="Maximum price USD."),
            SearchField("min_rating", "number",  description="Minimum 0–5 rating."),
            SearchField("in_stock",   "boolean"),
        ],
        # When zero results are returned, drop these filters in this order
        # before retrying. `category` is in `core_keys` so it is NEVER dropped.
        drop_priority=["color", "size", "min_rating", "min_price", "max_price", "brand"],
        core_keys={"category"},
    )
```

### What `drop_priority` actually does

The user asks: *"red Nike running shoes under $40, rating 4.5+"*.

The LLM extracts:
```json
{"category": "shoes", "brand": "Nike", "color": "red",
 "max_price": 40, "min_rating": 4.5, "query": "running"}
```

If your DB has zero matches, the kit retries automatically with progressively
fewer filters, in the order you specified:

| level | filters tried                                        |
|------:|------------------------------------------------------|
| 0     | `{category, brand, color, max_price, min_rating}`    |
| 1     | drop `color`     → `{category, brand, max_price, min_rating}` |
| 2     | drop `min_rating`→ `{category, brand, max_price}`    |
| 3     | drop `max_price` → `{category, brand}`               |
| 4     | drop `brand`     → `{category}` ← stops here, `category` is core |

The reply tells the user *"I couldn't find Nikes that cheap, but here are
some red running shoes near your price"* and the JSON includes
`"relaxation_level": 3` so your frontend can show a discreet badge.

---

## Step 2 — adapt your database (`catalog.py`)

A `CatalogBackend` is **one async method**:

```python
async def search(
    self,
    filters: dict,    # whatever the LLM extracted, after relaxation
    query: str,       # free-text part ("running shoes")
    sort_by: str,     # "relevance" | "price_asc" | "newest" | ...
    skip: int,
    limit: int,
) -> dict:            # must return {"items": [...], "total": int}
    ...
```

Here's the **Elasticsearch** version (full file:
[`examples/elasticsearch_catalog/catalog.py`](../llm_search_kit/examples/elasticsearch_catalog/catalog.py)):

```python
# my_app/llm_search/catalog.py
from typing import Any, Dict
from elasticsearch import AsyncElasticsearch

class ElasticsearchCatalog:
    """Maps llm-search-kit filters to an Elasticsearch products index."""

    def __init__(self, es: AsyncElasticsearch, index: str = "products") -> None:
        self._es = es
        self._index = index

    async def search(self, filters: Dict[str, Any], query: str = "",
                     sort_by: str = "relevance", skip: int = 0,
                     limit: int = 10) -> Dict[str, Any]:
        must:   list = []
        filt:   list = []

        if query:
            must.append({
                "multi_match": {
                    "query": query,
                    "fields": ["title^3", "description", "brand"],
                    "fuzziness": "AUTO",
                }
            })

        # term filters (exact match)
        for key in ("category", "brand", "color", "size"):
            if key in filters:
                filt.append({"term": {f"{key}.keyword": filters[key]}})

        if "in_stock" in filters:
            filt.append({"term": {"in_stock": bool(filters["in_stock"])}})

        # range filters
        price_range: Dict[str, Any] = {}
        if "min_price" in filters: price_range["gte"] = filters["min_price"]
        if "max_price" in filters: price_range["lte"] = filters["max_price"]
        if price_range:
            filt.append({"range": {"price": price_range}})

        if "min_rating" in filters:
            filt.append({"range": {"rating": {"gte": filters["min_rating"]}}})

        body: Dict[str, Any] = {
            "from": skip,
            "size": limit,
            "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filt}},
        }
        if sort_by == "price_asc":  body["sort"] = [{"price":  "asc"}]
        if sort_by == "price_desc": body["sort"] = [{"price":  "desc"}]
        if sort_by == "newest":     body["sort"] = [{"created_at": "desc"}]

        resp = await self._es.search(index=self._index, body=body)

        return {
            "items": [hit["_source"] | {"_id": hit["_id"]}
                      for hit in resp["hits"]["hits"]],
            "total": resp["hits"]["total"]["value"],
        }
```

That's it. **No other changes are needed in the kit** — `SearchCatalogSkill`
will discover this object via the `CatalogBackend` Protocol.

> Tip — if your fields are different (e.g. `nom`, `prix`, `marque` in
> French), keep the *kit* schema in English (`brand`, `price`, ...) and
> translate inside `search()`. That way your LLM prompt is short and your
> DB stays as it is.

---

## Step 3 — wire it into Flask (`app.py`)

The full file lives at
[`examples/flask_server/app.py`](../llm_search_kit/examples/flask_server/app.py).
The essence:

```python
# my_app/api.py
import asyncio
from collections import defaultdict, deque
from flask import Flask, request, jsonify
from elasticsearch import AsyncElasticsearch

from llm_search_kit import AgentEngine, SearchCatalogSkill
from llm_search_kit.config import build_default_llm_client

from my_app.llm_search.schema  import build_schema
from my_app.llm_search.catalog import ElasticsearchCatalog

app = Flask(__name__)

# ---- one-time setup ----------------------------------------------------
LLM      = build_default_llm_client()                       # reads .env
ES       = AsyncElasticsearch("http://localhost:9200")
CATALOG  = ElasticsearchCatalog(ES, index="products")
SKILL    = SearchCatalogSkill(schema=build_schema(), backend=CATALOG)
ENGINE   = AgentEngine(
    llm_client=LLM,
    system_prompt=open("soul.md").read(),  # personality + rules
)
ENGINE.register_skill(SKILL)

# super-naive in-memory session store. Replace with Redis in production.
SESSIONS: dict[str, deque] = defaultdict(lambda: deque(maxlen=12))

# ---- the endpoint ------------------------------------------------------
@app.post("/chat")
def chat():
    payload    = request.get_json(force=True) or {}
    message    = (payload.get("message") or "").strip()
    session_id = payload.get("session_id") or "anon"
    user_id    = payload.get("user_id")  # optional

    if not message:
        return jsonify(error="message is required"), 400

    history = list(SESSIONS[session_id])

    result = asyncio.run(ENGINE.process(
        message,
        conversation_history=history,
        context={"user_id": user_id} if user_id else None,
    ))

    SESSIONS[session_id].append({"role": "user",      "content": message})
    SESSIONS[session_id].append({"role": "assistant", "content": result["reply"]})

    return jsonify({
        "reply":    result["reply"],
        "products": (result.get("data") or {}).get("items", []),
        "meta": {
            "relaxation_level": (result.get("data") or {}).get("relaxation_level", 0),
            "filters_used":     (result.get("data") or {}).get("filters_used", {}),
            "tool_calls":       len(result.get("tool_calls", [])),
        },
    })
```

Run it:
```bash
pip install flask "elasticsearch[async]>=8" llm-search-kit
export LLM_API_KEY=sk-...
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini
flask --app my_app.api run
```

> ⚠️ **`asyncio.run` per request is fine for prototyping** but creates a new
> event loop on every call. For production you have two options:
> 1. switch to **Quart** (async Flask) and `await engine.process(...)` directly,
> 2. or keep Flask and put the engine behind an `asyncio` thread + queue.
>
> The example file shows option 1 commented out at the bottom.

---

## Step 4 — call it from the frontend

```js
// React / vanilla / anything
async function ask(message) {
  const r = await fetch("/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      message,
      session_id: localStorage.getItem("sid") ?? crypto.randomUUID(),
    }),
  });
  const { reply, products, meta } = await r.json();
  // render `reply` in the chat bubble, render `products` in a grid below.
  if (meta.relaxation_level > 0) {
    showBadge(`We loosened your filters to find these (level ${meta.relaxation_level}).`);
  }
}
```

---

## Step 5 — give the assistant a personality (`soul.md`)

The system prompt is **the single biggest lever** for response quality. A
good one is short, concrete, and tells the model **when to call the tool**.
Example:

```markdown
You are **Shoply**, the friendly shopping assistant for ExampleStore.

## Rules
- ALWAYS call the `search_catalog` tool whenever the user is looking for a
  product. Never invent products from memory.
- Extract structured filters (category, brand, color, size, max_price, ...)
  from the user's message and put them into the tool arguments.
- The remaining free-text words go into `query` (e.g. "running", "gaming").
- After the tool returns:
  * If `relaxation_level > 0`, briefly tell the user you broadened the
    search and explain what you dropped.
  * Recommend 1–3 items in a friendly tone, mentioning price + 1 selling
    point each. Keep it under 4 sentences.
- If `total == 0`, apologise and ask one clarifying question.
- Never expose internal field names like `_id`, `relaxation_level`, etc.

## Tone
Warm, casual, helpful. Use the user's language (English, French, ...).
```

Save this as `soul.md`, load it with `open("soul.md").read()`, pass to
`AgentEngine(system_prompt=...)`. Tweak it as you observe real conversations
— this file *is* your product.

---

## FAQ — common adaptation questions

**Q: My DB has different field names (`nom`, `prix`, `marque`).**
Translate inside `search()`. Keep the kit schema in English so the LLM has
clean tool-argument names.

**Q: I want to also expose "compare two products" or "recommend an outfit".**
Write another `BaseSkill` and `engine.register_skill(my_other_skill)`.
The LLM will pick which tool to call. See
[`llm_search_kit/agent/base_skill.py`](../llm_search_kit/agent/base_skill.py)
for the protocol — you need: `name`, `description`, `parameters_schema`
(JSON Schema), and an async `execute(**kwargs)` returning `SkillResult`.

**Q: I don't have Elasticsearch — I have Postgres / Mongo / a REST API.**
Same shape. Just change the body of `search()`. The kit doesn't care what's
underneath; it only ever calls `await backend.search(...)` and expects
`{items, total}` back.

**Q: Costs are scary. Can I cap them?**
Two knobs:
- `AgentEngine(max_iterations=5)` — caps tool-call rounds per user turn (default 10).
- Use a cheap model (`gpt-4o-mini`, `groq/llama-3.1-8b-instant`,
  `openrouter/anthropic/claude-3-haiku`). All work via the same OpenAI-compatible API.

**Q: Can I add a fallback LLM in case the primary is down?**
Yes:
```python
from llm_search_kit.llm import OpenAILLMClient, ResilientLLMClient

primary  = OpenAILLMClient(base_url="https://api.openai.com/v1", api_key=os.environ["OAI"], model="gpt-4o-mini")
fallback = OpenAILLMClient(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ"], model="llama-3.1-8b-instant")
LLM      = ResilientLLMClient(primary=primary, fallback=fallback)
```

**Q: How do I see what the LLM is actually doing?**
```python
import logging
logging.basicConfig(level=logging.INFO)
# you'll see [AGENT] Calling skill: search_catalog({...})
# and       [SEARCH] level=0 filters={...}
```

**Q: How do I test my catalog adapter without burning API credits?**
Use the `ScriptedLLMClient` from [`tests/conftest.py`](../tests/conftest.py)
as a template. It returns canned LLM responses so your tests stay
deterministic and offline.

---

## Where to look next

| If you want to…                              | Open this                                               |
|----------------------------------------------|---------------------------------------------------------|
| See it work end-to-end with zero setup       | `python -m llm_search_kit.examples.amazon_products.run` |
| Copy a real DB adapter                       | `llm_search_kit/examples/elasticsearch_catalog/`        |
| Copy a real HTTP server                      | `llm_search_kit/examples/flask_server/`                 |
| Understand the search skill / relaxation    | `llm_search_kit/search/search_skill.py`                 |
| Add a non-search skill (compare, recommend) | `llm_search_kit/agent/base_skill.py`                    |
