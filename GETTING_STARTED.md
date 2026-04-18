# Getting started — zero to a running `/chat` service

> **Audience.** You already have a working backend (the Beasyapp Spring Boot
> app, a Django shop, an Express API — anything that exposes a "search
> products" endpoint). You want a chat box that answers natural-language
> questions like *"red Samsung TV under 100 000 FCFA"* by calling your
> existing endpoint. You **do not** want to set up a vector DB, a second
> database, or any new infrastructure.
>
> This page walks you from `git clone` to *"my frontend can POST to
> http://localhost:5000/chat"* in 5 steps. **Every command is here. Every
> expected output is here. Every "what if it breaks" is here.**

---

## Table of contents

1. [Install](#1-install)
2. [Verify your backend is reachable](#2-verify-your-backend-is-reachable)
3. [Run the offline test suite](#3-run-the-offline-test-suite)
4. [Run the live integration tests against your backend](#4-run-the-live-integration-tests-against-your-backend)
5. [Get an LLM key](#5-get-an-llm-key)
6. [Run the chat service](#6-run-the-chat-service)
7. [Call the service from the frontend](#7-call-the-service-from-the-frontend)
8. [Adapt to your own backend (not Beasyapp)](#8-adapt-to-your-own-backend-not-beasyapp)
9. [Production checklist](#9-production-checklist)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Install

```bash
git clone https://github.com/JIV-DLS/llm-search-kit.git
cd llm-search-kit

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev,flask]"
```

**What success looks like:**

```
Successfully installed llm-search-kit-0.1.0 ...
```

**If it fails** because `python3` is too old, you need Python 3.9 or newer
(`python3 --version` to check).

---

## 2. Verify your backend is reachable

Replace the URL with your own if you're not pointing at the Beasyapp ngrok
tunnel.

```bash
curl -sS -X POST https://actinolitic-glancingly-saturnina.ngrok-free.dev/api/v1/listings/search \
  -H "Content-Type: application/json" \
  -H "ngrok-skip-browser-warning: true" \
  -d '{"query":"samsung","size":2,"includeFacets":false}' \
  | python3 -m json.tool | head -25
```

**What success looks like:**

```json
{
    "listings": [
        {
            "id": 1,
            "status": "ACTIVE",
            "title": "Samsung 55” 4K UHD Smart TV (UN55AU8000FXZA)",
            "price": 50000.00,
            ...
```

If you get HTML instead of JSON, the ngrok tunnel is down — restart it on
the backend side.

---

## 3. Run the offline test suite

This proves the kit is installed correctly. **No network, no LLM key
required.**

```bash
pytest -q
```

**What success looks like:**

```
............................sssssssss...................................
.......
70 passed, 9 skipped in 0.50s
```

The 9 skipped tests are the live integration tests we run in step 4.

---

## 4. Run the live integration tests against your backend

This proves the adapter actually works against your real backend, end to
end. **Still no LLM key needed** — these tests only exercise the catalog
adapter, not the agent loop.

```bash
BEASY_LIVE=1 pytest tests/test_beasyapp_live.py -v
```

If you're pointing at a different backend URL:

```bash
BEASY_LIVE=1 BEASY_BASE_URL=https://your-tunnel.example.com \
  pytest tests/test_beasyapp_live.py -v
```

**What success looks like:**

```
tests/test_beasyapp_live.py::test_freetext_search_returns_kit_shape PASSED
tests/test_beasyapp_live.py::test_match_all_search_returns_results PASSED
tests/test_beasyapp_live.py::test_facets_are_returned_when_requested PASSED
tests/test_beasyapp_live.py::test_min_max_price_filters_are_respected PASSED
tests/test_beasyapp_live.py::test_impossible_filter_returns_zero PASSED
tests/test_beasyapp_live.py::test_price_asc_sort_is_monotonic PASSED
tests/test_beasyapp_live.py::test_price_desc_sort_is_monotonic PASSED
tests/test_beasyapp_live.py::test_pagination_returns_disjoint_pages PASSED
tests/test_beasyapp_live.py::test_relaxation_recovers_results_when_filters_too_tight PASSED
============================== 9 passed in 6.83s ==============================
```

If any of these fails, **stop here and fix it before continuing** — the
chat service can only be as good as the adapter underneath it.

You can also run a manual smoke test that prints each scenario's result:

```bash
python -m llm_search_kit.examples.beasyapp_backend.smoke
```

This script runs **8 scenarios** end-to-end against your real backend and
prints what came back, what was filtered out, and which PII fields were
scrubbed. See [Section 10](#10-troubleshooting) for what its output
should look like.

---

## 5. Get an LLM key

The kit talks to **any OpenAI-compatible chat completions endpoint**. Pick
one (in order of cheapest-to-try-first):

| Provider     | URL                                                | Free tier?              | Set in `.env`                                                                                              |
|--------------|----------------------------------------------------|-------------------------|------------------------------------------------------------------------------------------------------------|
| **Groq**     | https://console.groq.com/keys                       | ✅ generous             | `LLM_BASE_URL=https://api.groq.com/openai/v1`<br>`LLM_MODEL=llama-3.1-8b-instant`<br>`LLM_API_KEY=gsk_...` |
| **OpenAI**   | https://platform.openai.com/api-keys                | ❌ paid only            | `LLM_BASE_URL=https://api.openai.com/v1`<br>`LLM_MODEL=gpt-4o-mini`<br>`LLM_API_KEY=sk-...`                |
| **OpenRouter** | https://openrouter.ai/keys                       | ✅ small free credit    | `LLM_BASE_URL=https://openrouter.ai/api/v1`<br>`LLM_MODEL=meta-llama/llama-3.1-8b-instruct:free`<br>`LLM_API_KEY=sk-or-...` |
| **Ollama**   | local                                               | ✅ free, your hardware  | `LLM_BASE_URL=http://localhost:11434/v1`<br>`LLM_MODEL=llama3.2`<br>`LLM_API_KEY=ollama`                   |

```bash
cp .env.example .env
$EDITOR .env             # paste the three values from your provider
```

Verify it works with a single one-shot question (no service yet, just the CLI):

```bash
python -m llm_search_kit.examples.beasyapp_backend.run \
  -q "samsung tv 4K under 100000 FCFA"
```

**What success looks like:**

```
Assistant> Voici quelques options Samsung 4K disponibles autour de 100 000 FCFA :
  - Samsung 55” 4K UHD Smart TV (UN55AU8000FXZA)  50000 FCFA
  - Samsung 50” QLED 4K Smart TV  78000 FCFA
  ...
```

---

## 6. Run the chat service

This is the single command that starts the HTTP service your frontend
will talk to. It is wired to the Beasyapp backend by default.

```bash
python -m llm_search_kit.examples.beasy_service \
  --beasy-url https://actinolitic-glancingly-saturnina.ngrok-free.dev \
  --port 5000
```

**What success looks like:**

```
[INFO] Beasy chat service ready on http://127.0.0.1:5000
[INFO] Backend:  https://actinolitic-glancingly-saturnina.ngrok-free.dev
[INFO] Skills:   ['search_catalog']
 * Serving Flask app 'llm_search_kit.examples.beasy_service'
 * Running on http://127.0.0.1:5000
```

**Smoke-test the running service from another terminal:**

```bash
# Health check (no LLM call):
curl -s http://127.0.0.1:5000/health | python3 -m json.tool

# Real chat call (English, with a price cap):
curl -s -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"red Samsung TV under 100000 FCFA","session_id":"demo"}' \
  | python3 -m json.tool

# Real chat call (French, gift-shopping, no price, vague intent):
curl -s -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"je veux offrir quelque chose à un nouveau-né, des vêtements doux et confortables pour bébé","session_id":"gift"}' \
  | python3 -m json.tool
```

**Expected response shape:**

```json
{
    "reply": "Voici quelques téléviseurs Samsung qui correspondent...",
    "products": [
        {
            "id": 1,
            "title": "Samsung 55” 4K UHD Smart TV (UN55AU8000FXZA)",
            "price": 50000.00,
            "color": "#808080",
            "brand": {"id": 1, "name": "Samsung"},
            "creator": {
                "id": 7,
                "username": "iamlemuel",
                "fullName": "Lemuel DONTO",
                "city": "Toulouse",
                "country": "FR"
                // NOTE: email, password, phone, full address are scrubbed.
            }
        }
    ],
    "meta": {
        "total": 4,
        "relaxation_level": 0,
        "filters_used": {"max_price": 100000.0},
        "tool_calls": 1
    }
}
```

The service also exposes:

- `GET  /health` → `{status, backend, skills}`
- `POST /chat` → `{reply, products, meta}`
- `POST /sessions/<session_id>/reset` → clears that session's chat history

---

## 7. Call the service from the frontend

Drop this into your React / Vue / vanilla JS app:

```js
const SESSION_ID = localStorage.getItem("chat_sid")
                 ?? (localStorage.setItem("chat_sid", crypto.randomUUID()),
                     localStorage.getItem("chat_sid"));

async function ask(message) {
  const res = await fetch("http://127.0.0.1:5000/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: SESSION_ID }),
  });
  const { reply, products, meta } = await res.json();

  showAssistantBubble(reply);
  renderProductGrid(products);
  if (meta.relaxation_level > 0) {
    showHint(`We loosened your filters to find these (level ${meta.relaxation_level}).`);
  }
}
```

CORS: the Flask service does **not** enable CORS by default. If your
frontend is on a different origin, add it once at startup:

```bash
pip install flask-cors
```

…and edit `beasy_service.py` to call `CORS(app)` after `create_app()`. Or
proxy `/chat` through the same nginx/Caddy that serves your frontend.

---

## 8. Adapt to your own backend (not Beasyapp)

If your search endpoint is **not** Beasyapp, you do exactly two things:

### a) Copy the adapter

```bash
cp -r llm_search_kit/examples/beasyapp_backend/ llm_search_kit/examples/my_backend/
```

### b) Edit two methods in `catalog.py`

Open `llm_search_kit/examples/my_backend/catalog.py` and change:

1. **`_build_body(filters, query, sort_by, skip, limit)`** — rename the
   keys to match your `RequestBody`. Example for a `POST /products/search`
   that accepts `{q, brand, priceMax, page, perPage}`:

   ```python
   body = {"q": query, "page": skip // limit, "perPage": limit}
   if "brand_ids" in filters: body["brand"]    = filters["brand_ids"][0]
   if "max_price" in filters: body["priceMax"] = filters["max_price"]
   ```

2. **The unpacking inside `search()`** — rename `listings` /
   `totalElements` to whatever your endpoint returns. Example:

   ```python
   payload = resp.json()
   return {
       "items": [self._transform(p) for p in payload["products"]],
       "total": payload["count"],
       "metadata": {"facets": payload.get("aggregations")},
   }
   ```

That's it. Run `pytest tests/test_beasyapp_backend.py` and adapt the
copied tests to your shape — the structure of the test file is the
checklist of what your adapter needs to handle (PII, sorts, pagination,
empty results, errors, headers).

[`docs/INTEGRATION.md`](docs/INTEGRATION.md) and
[`docs/INTEGRATION_BEASY.md`](docs/INTEGRATION_BEASY.md) cover this in
more depth.

---

## 8b. Test the LLM brain (not just the plumbing)

Everything up to this point exercises the **plumbing**: the catalog
adapter, the agent loop, the HTTP wiring. None of it tests whether the
**LLM** actually behaves correctly on real user-style prompts. For that,
the kit ships a third tier of tests gated by `LLM_LIVE=1`.

### Tier 1 — offline (default `pytest`)

```bash
pytest -q                      # 70+ tests, no network, no LLM key
```

Tests the agent loop, the adapter, PII scrubbing, session memory, error
paths — all with mocked LLM and mocked backend. Runs in < 1s, must
always pass before merging.

### Tier 2 — live backend (no LLM)

```bash
BEASY_LIVE=1 pytest tests/test_beasyapp_live.py -v
python -m llm_search_kit.examples.beasyapp_backend.smoke
```

Tests the catalog adapter against the **real Beasy backend** (or
yours, via `BEASY_BASE_URL`). Still no LLM cost. Catches "your Spring
endpoint is returning a different shape than we think" bugs.

### Tier 3 — live LLM end-to-end

```bash
# Pytest suite — outcome-based, opt-in, repeats each test 3x and
# requires >=2/3 passes (so a model that's 95% right doesn't flake):
LLM_LIVE=1 pytest tests/test_llm_live.py -v

# Human-readable report card across 15 realistic prompts (English +
# French, including Armand's "vêtements pour bébé" example):
python scripts/run_scenarios.py
python scripts/run_scenarios.py --only baby_gift     # debug one scenario
python scripts/run_scenarios.py --out-md report.md   # commit a snapshot
```

Tests the **LLM brain** itself: does the model actually call
`search_catalog`, with sensible filters, in the user's language,
without inventing a budget the user didn't give, without leaking PII?
The same env vars that drive the chat service drive these tests, so
swapping providers is one env-var change:

```bash
# Default — Technas LLM gateway (Claude Sonnet primary, Gemini fallback):
LLM_BASE_URL=https://llm.technas.fr/v1
LLM_MODEL=smart
LLM_API_KEY=<litellm_master_key>

# Or any other OpenAI-compatible provider:
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.1-70b-versatile
LLM_API_KEY=gsk_...
```

**What to do with the report card:**

- All `PASS` → ship.
- `WARN` rows are usually prompt-tuning opportunities (e.g. the model
  put a color word in `query` instead of extracting it as `color`).
  Edit `soul.md` and re-run.
- `FAIL` rows are blockers (e.g. the model invented a `max_price` the
  user didn't give, or leaked PII). Tighten the prompt or switch model.

### When to run each tier

| Trigger                                     | Tier 1 | Tier 2 | Tier 3 (pytest) | Tier 3 (report card) |
|---------------------------------------------|:------:|:------:|:---------------:|:--------------------:|
| Every commit / pre-merge CI                 | ✅      |        |                 |                      |
| Pre-deploy of the catalog adapter           | ✅      | ✅      |                 |                      |
| Pre-deploy of the chat service              | ✅      | ✅      | ✅               |                      |
| Editing `soul.md` or switching model        | ✅      |        | ✅               | ✅                    |
| Investigating "the assistant said X" bugs   |        |        |                 | ✅                    |

---

## 9. Production checklist

When you're ready to put this in front of real users:

- [ ] **Sessions** → swap the in-memory `dict` in `beasy_service.py` for
      Redis. The current store loses chat history when the process restarts
      and doesn't share across multiple workers.
- [ ] **WSGI server** → don't ship `flask run`. Use `gunicorn -w 1 -k uvicorn.workers.UvicornWorker llm_search_kit.examples.beasy_service:app` (workers=1 because the in-memory session store is per-process — once you're on Redis you can scale workers).
- [ ] **Backend auth** → if your search endpoint is no longer publicly
      open, pass an auth header to the adapter:
      ```python
      BeasyappCatalog(base_url=..., headers={"Authorization": f"Bearer {token}"})
      ```
- [ ] **LLM fallback** → set `LLM_FALLBACK_*` env vars in `.env` so the
      kit's `ResilientLLMClient` swaps to a backup provider if the primary
      times out.
- [ ] **Cost cap** → `AgentEngine(max_iterations=5)` (default 10) limits
      the tool-call rounds per user turn. With a cheap model (Groq Llama
      3.1 8B, GPT-4o mini) a typical chat turn costs < $0.001.
- [ ] **Logging** → set `logging.basicConfig(level=logging.INFO)` and you
      get one line per agent turn:
      `[AGENT] Calling skill: search_catalog({...})`
      `[SEARCH] level=0 filters={...} query='...' sort=RELEVANCE`
- [ ] **Brand & category id mapping** → load `/brands` and `/categories`
      from your backend at startup and inject the `id ↔ name` table into
      the system prompt. The LLM will then map "Samsung" → `brand_ids:[1]`
      reliably without depending on facet drift.

---

## 10. Troubleshooting

| Symptom                                                          | Fix                                                                                                                                                              |
|------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_API_KEY is not set`                                         | Step 5. Run `cp .env.example .env` and paste a real key.                                                                                                        |
| `BeasyappAPIError: HTTP 502 / 503 / 504`                         | Your backend is down or the ngrok tunnel expired. Restart it. Re-run step 2 to confirm.                                                                          |
| `BeasyappAPIError: non-JSON body`                                | The backend returned HTML (often an ngrok warning page). Make sure your custom client also sends `ngrok-skip-browser-warning: true` — the adapter does by default. |
| `httpx.ConnectError: All connection attempts failed`             | Wrong `--beasy-url` or your machine can't reach it. `curl` it from the same shell first.                                                                         |
| Live tests fail at `test_min_max_price_filters_are_respected`    | Your backend is interpreting `minPrice`/`maxPrice` differently than expected. The adapter just passes them through; check your Spring code.                      |
| `module 'flask' has no attribute 'Flask'`                        | You installed only the core kit. Re-run `pip install -e ".[dev,flask]"`.                                                                                         |
| Service starts but `/chat` returns `agent_failure`               | Check the service log — usually the LLM provider is rate-limiting you, returning a malformed `tool_call`, or your `LLM_MODEL` doesn't support tool calling. Try `gpt-4o-mini` or `llama-3.1-70b-versatile` to confirm.  |
| Chat reply is in the wrong language                              | Edit `llm_search_kit/examples/beasyapp_backend/soul.md` — the line *"Default to the user's language"* — to force a specific language.                            |
| Reply mentions products that aren't in the catalog               | The model is hallucinating. Strengthen `soul.md`: *"Never invent listings. If the tool returns 0 items, say so explicitly."*                                     |
| `relaxation_level` is always 0 even when filters seem strict     | Your backend may already be doing fuzzy matching. That's fine — relaxation is a safety net, not a requirement.                                                   |
| Tier-3 pytest `test_real_llm_*` keeps flaking (1/3 or 2/3 passes) | The model is borderline reliable on that scenario. Tighten `soul.md` with an explicit example of the failing case (see how `baby_gift` was added), or swap to a stronger model (`gpt-4o-mini` → `gpt-4o`, `llama-3.1-8b-instant` → `llama-3.1-70b-versatile`, `smart` over `local`). |
| `run_scenarios.py` reports FAIL on `pii_safety_canary`           | **Hard stop, do not deploy.** The reply contained an email-pattern or phone-pattern. Verify (a) the adapter still scrubs PII (run `pytest tests/test_beasyapp_backend.py -k pii`), and (b) the system prompt still has the "Never quote the seller's email/phone…" line.       |
| PII (email/phone/password) shows up in `/chat` response          | **Stop and report this.** That's a security regression. Check that you didn't override `listing_transform` to disable scrubbing. Re-run the live test `test_freetext_search_returns_kit_shape` — it asserts PII is absent.  |

If something here doesn't match what you see, open an issue with the
exact command, the env you ran it in, and the full output. The fix usually
goes in this file so the next person doesn't hit it.
