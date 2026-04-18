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

## Quick start

```bash
pip install -e ".[examples,dev]"
cp .env.example .env
# edit .env -> set LLM_API_KEY and LLM_MODEL

# Run the Amazon-products demo (in-memory SQLite, zero setup):
python -m llm_search_kit.examples.amazon_products.run

# Or one-shot:
python -m llm_search_kit.examples.amazon_products.run --query "red Nike running shoes under 80$ size 42"

# Real-estate demo (needs a REST backend that returns property results):
python -m llm_search_kit.examples.real_estate_togo.run
```

Tests:

```bash
pytest -q
```

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

## License

MIT.
