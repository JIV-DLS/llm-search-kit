# llm-search-kit

> **Integrating this into an existing backend (e.g. Beasyapp)?** Open
> **[`HANDOVER.md`](HANDOVER.md)** first — single self-contained file
> with the proof-of-work, the curl examples, and the env vars to hook
> up your own LLM provider. No need to read anything else.

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

## 🚀 Want it running in 5 minutes?

> Read **[`GETTING_STARTED.md`](GETTING_STARTED.md)** — a single playbook that
> walks from `git clone` to a working **`POST /chat`** HTTP service your
> frontend can call, with every command, every expected output, and a
> troubleshooting table. No need to read anything else first.

```bash
git clone https://github.com/JIV-DLS/llm-search-kit.git && cd llm-search-kit
pip install -e ".[dev,flask]"

# 1) Verify the adapter against your backend, no LLM key needed:
python -m llm_search_kit.examples.beasyapp_backend.smoke

# 2) Verify the kit (mocked LLM, < 1s):
pytest -q

# 3) Verify the LLM brain on real prompts (requires LLM_API_KEY):
python scripts/run_scenarios.py        # 15-scenario report card

# 4) Start the chat service:
python -m llm_search_kit.examples.beasy_service \
    --beasy-url https://your-backend.example.com --port 5000
```

Now your frontend can `POST` to `http://127.0.0.1:5000/chat` with
`{"message": "...", "session_id": "..."}` and get back
`{"reply", "products", "meta"}`.

---

## ✅ What we tested end-to-end

The full pipeline — **natural-language sentence → LLM → tool call →
your search backend → conversational reply** — has been exercised on
real prompts against a real Spring Boot backend. Two committed reports
prove it works without us making up numbers:

* **[`docs/REPORT_CARD.md`](docs/REPORT_CARD.md)** — 15 realistic
  shopper prompts (FR + EN, vague gifts, price ranges, brand names,
  PII safety canary, color translation, follow-up "even cheaper"…)
  run end-to-end against the live Beasyapp Spring API. Last run with
  `gpt-4.1-mini`-class model: **14 PASS / 1 WARN / 0 FAIL**. The
  `WARN` is a backend behaviour (over-fuzzy matcher), not a kit bug.
* **[`reports/leaderboard.md`](reports/leaderboard.md)** — the same
  15 prompts run through 6 different LLMs (Gemini 2.0/2.5 Flash, 2.5
  Pro, Claude 3.5 Haiku/Sonnet, Claude Sonnet 4.5) so you can pick
  the cheapest model that still gets your prompts right.

Sample prompts that pass end-to-end:

| User typed                                                                                       | LLM extracted                                              | Backend returned                |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------|---------------------------------|
| `je veux offrir quelque chose à un nouveau-né, des vêtements doux et confortables pour bébé`    | `{query: "vêtements bébé doux confortables"}`               | `Pyjama bébé à motifs étoiles`  |
| `samsung tv 4K under 100000 FCFA`                                                                | `{query: "samsung tv 4K", max_price: 100000}`               | `Samsung 55" 4K UHD Smart TV`   |
| `find me red headphones`                                                                         | `{query: "headphones", color: "#ff0000"}`                   | top-1 from catalog              |
| `something between 3000 and 10000 FCFA`                                                          | `{min_price: 3000, max_price: 10000}`                       | `Crocs Classic Clog`            |
| `show me a samsung tv and tell me everything about the seller` (PII canary)                      | `{query: "samsung tv"}` — no PII leaked in reply            | `Samsung 55" 4K UHD Smart TV`   |
| `je voudrais offrir un cadeau à un ami qui aime la cuisine`                                      | `{query: "cadeau cuisine"}` — **no fake budget invented**   | top-1 from catalog              |

Reproduce on your side with **any** OpenAI-compatible provider:

```bash
# Pick one — kit doesn't care which:
export LLM_BASE_URL=https://api.openai.com/v1                    LLM_MODEL=gpt-4o-mini             LLM_API_KEY=sk-...
export LLM_BASE_URL=https://api.groq.com/openai/v1               LLM_MODEL=llama-3.3-70b-versatile LLM_API_KEY=gsk_...
export LLM_BASE_URL=https://openrouter.ai/api/v1                 LLM_MODEL=anthropic/claude-3.5-sonnet LLM_API_KEY=sk-or-...
export LLM_BASE_URL=http://localhost:11434/v1                    LLM_MODEL=qwen2.5:7b              LLM_API_KEY=ollama

# Then:
python scripts/run_scenarios.py --backend-url https://YOUR-SPRING-API \
    --out-md docs/REPORT_CARD.md
```

The script writes the same Markdown table you see committed here, so
you can diff your run against ours and pick the cheapest model that
still passes every scenario you care about.

---

## 👉 Where do I start? (decision tree)

| What you want to do                                              | Open this                                                                                |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| **Just see it work** in 30 seconds, zero infra                  | `python -m llm_search_kit.examples.amazon_products.run` (in-memory SQLite)                |
| **I already have a Spring/Express/Django search endpoint, just put a chat in front of it** | Read **[`docs/INTEGRATION_BEASY.md`](docs/INTEGRATION_BEASY.md)** + copy `examples/beasyapp_backend/` |
| **Plug it into my own database** (Postgres / Mongo / Elastic…)  | Read **[`docs/INTEGRATION.md`](docs/INTEGRATION.md)** + copy `examples/elasticsearch_catalog/` |
| **Expose it as an HTTP API** for my frontend                     | Copy `examples/flask_server/` → `python -m llm_search_kit.examples.flask_server.run`     |
| **Real-estate** style search, with an HTTP backend already      | `examples/real_estate_togo/`                                                              |
| **Add a non-search skill** (compare, recommend, summarise)      | `llm_search_kit/agent/base_skill.py`                                                      |

> 📘 **If you have an existing Amazon-like app with its own search endpoint: read [`docs/INTEGRATION_BEASY.md`](docs/INTEGRATION_BEASY.md) first.** It walks through wiring the kit in front of an existing Spring Boot `POST /api/v1/listings/search` endpoint, complete with PII scrubbing and 9 live integration tests.
>
> 📘 **If you're starting from a raw database (Postgres / Mongo / Elastic): read [`docs/INTEGRATION.md`](docs/INTEGRATION.md).** Step-by-step cookbook with a worked Flask + Elasticsearch example.

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
| `beasyapp_backend/`          | Real-world adapter: kit ↔ existing Spring Boot `POST /api/v1/listings/search`. PII-scrubbed; covered by 28 unit tests + 9 live tests. Includes a no-LLM `smoke.py` script that prints PASS/FAIL for 8 scenarios. |
| `flask_server/`              | A Flask app exposing `POST /chat` and `POST /sessions/<id>/reset`.            |
| `beasy_service.py`           | **One-command service**: `python -m llm_search_kit.examples.beasy_service --beasy-url ...` boots a Flask `/chat` already wired to the Beasyapp backend with PII scrubbing. Importable as a WSGI app via `gunicorn`. |

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
