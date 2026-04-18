# llm-search-kit

A small, dependency-light, **domain-agnostic agentic LLM search kit**. It gives
you a tool-calling loop that turns a user's natural-language question into
structured filters, calls *your* catalog backend, applies progressive filter
relaxation when results are empty, and returns a clean JSON payload + a
conversational reply.

It talks to **any OpenAI-compatible chat-completions endpoint**: OpenAI, Groq,
OpenRouter, Together, vLLM, llama.cpp's `--api`, Ollama (OpenAI mode), etc. No
vendor SDK required.

Originally extracted from a real-estate chatbot ("rede"); generalised so you can
plug it into any catalog: products, jobs, recipes, anything searchable.

---

## 👉 Where do I start? (decision tree)

| What you want to do                                              | Open this                                                                                |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| **Just see it work** in 30 seconds, zero infra                  | `python -m llm_search_kit.examples.amazon_products.run` (in-memory SQLite)                |
| **Plug it into my own database** (Postgres / Mongo / Elastic…)  | Read **[`docs/INTEGRATION.md`](docs/INTEGRATION.md)** + copy `examples/elasticsearch_catalog/` |
| **Expose it as an HTTP API** for my frontend                     | Copy `examples/flask_server/` → `python -m llm_search_kit.examples.flask_server.run`     |
| **Real-estate** style search, with an HTTP backend already      | `examples/real_estate_togo/`                                                              |
| **Add a non-search skill** (compare, recommend, summarise)      | `llm_search_kit/agent/base_skill.py`                                                      |

> 📘 **If you have an existing Amazon-like app and you don't know where to start: read [`docs/INTEGRATION.md`](docs/INTEGRATION.md) first.** It is a step-by-step cookbook with a worked Flask + Elasticsearch example matching exactly that situation.

---

## Quick start

```bash
pip install -e ".[examples,dev]"
cp .env.example .env
# edit .env -> set LLM_API_KEY and LLM_MODEL

# Run the Amazon-products demo (in-memory SQLite, zero setup):
python -m llm_search_kit.examples.amazon_products.run

# Or one-shot:
python -m llm_search_kit.examples.amazon_products.run --query "red Nike running shoes under 80$ size 42"

# Spin up the HTTP server (Flask):
pip install -e ".[flask]"
python -m llm_search_kit.examples.flask_server.run
# then: curl -s localhost:5000/chat -H 'Content-Type: application/json' \
#         -d '{"message":"red Nike under 80","session_id":"demo"}' | jq
```

Tests:

```bash
pytest -q
```

---

## Architecture

```
User text
   │
   ▼
AgentEngine ──► OpenAI-compatible LLM (tool-calling loop, max 10 iterations)
   │                      │
   │                      ▼
   │                  tool_call: search_catalog(filters...)
   │                      │
   ▼                      ▼
SkillRegistry ──► SearchCatalogSkill ──► your CatalogBackend.search(...)
                          │                      │
                          ▼                      ▼
                 build_relaxation_levels   {items, total}
```

You write **two things**:

1. A `SearchSchema` — declare which filters the LLM is allowed to extract
   (and the order to drop them in if no results are found).
2. A `CatalogBackend` — one async method `search(filters, query, sort_by,
   skip, limit) -> {items, total}` against your DB / REST API / vector store.

The kit handles the LLM round-trips, JSON parsing, retries, fallback
provider, relaxation when results are empty, and assembling the final reply.

For the full step-by-step including a Flask `/chat` endpoint and a real
Elasticsearch adapter, see [`docs/INTEGRATION.md`](docs/INTEGRATION.md).

---

## What ships in `examples/`

| Folder                       | What it shows                                                                 |
|------------------------------|-------------------------------------------------------------------------------|
| `amazon_products/`           | A complete domain (schema + soul.md + in-memory SQLite catalog) you can run. |
| `real_estate_togo/`          | Same but for property search, with both in-memory and HTTP catalog adapters.  |
| `elasticsearch_catalog/`     | A production-grade `CatalogBackend` against Elasticsearch 8.x.                |
| `flask_server/`              | A Flask app exposing `POST /chat` and `POST /sessions/<id>/reset`.            |

---

## Adding a new domain

Copy `llm_search_kit/examples/amazon_products/` and edit three files:

1. **`schema.py`** — declare the searchable fields (name, type, enum, description)
   and the *relaxation drop priority* (which filters to drop first when no
   results are found).
2. **`catalog.py`** — implement `CatalogBackend.search(filters, query, sort_by,
   skip, limit) -> {items, total}` against your DB / REST API / vector store.
3. **`soul.md`** — write the system prompt that gives your assistant its
   personality and domain rules.

That's it. The agent loop, tool schema generation, JSON parsing, retries,
fallback provider, and relaxation ladder are all handled for you.

---

## Public API

```python
from llm_search_kit import AgentEngine, OpenAILLMClient
from llm_search_kit.search import SearchCatalogSkill, SearchSchema, SearchField

llm = OpenAILLMClient(base_url="https://api.openai.com/v1", api_key="sk-...", model="gpt-4o-mini")

schema = SearchSchema(
    fields=[
        SearchField("category", "string", enum=["shoes", "shirts", "phones"]),
        SearchField("max_price", "number", description="Max price in USD"),
        SearchField("brand", "string"),
    ],
    drop_priority=["brand", "max_price"],
    core_keys={"category"},
)

skill = SearchCatalogSkill(schema=schema, backend=MyCatalog())
engine = AgentEngine(llm_client=llm, system_prompt=open("soul.md").read())
engine.register_skill(skill)

result = await engine.process("show me cheap red Nike sneakers")
print(result["reply"])           # conversational reply
print(result["data"]["items"])   # the items your backend returned
```

---

## License

MIT.
