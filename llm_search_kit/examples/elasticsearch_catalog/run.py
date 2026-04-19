"""Tiny end-to-end smoke test for the Elasticsearch adapter.

Requires a running Elasticsearch 8.x instance and the optional dep::

    pip install "elasticsearch[async]>=8,<9"
    docker run -d -p 9200:9200 -e discovery.type=single-node \
        -e xpack.security.enabled=false \
        docker.elastic.co/elasticsearch/elasticsearch:8.13.0

Then::

    export LLM_API_KEY=sk-...
    python -m llm_search_kit.examples.elasticsearch_catalog.run --seed
    python -m llm_search_kit.examples.elasticsearch_catalog.run \
        --query "red Nike running shoes under 100"
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Dict, List

from llm_search_kit import AgentEngine, SearchCatalogSkill
from llm_search_kit.config import assert_llm_credentials, build_default_llm_client

from ..amazon_products.schema import build_schema
from .catalog import ElasticsearchCatalog, build_default_index_mapping


_SAMPLE_PRODUCTS: List[Dict[str, Any]] = [
    {"title": "Nike Air Zoom Pegasus 40", "brand": "Nike",  "category": "shoes", "color": "red",   "size": "42", "price":  89.0, "rating": 4.6, "in_stock": True,  "description": "Lightweight running shoe with responsive cushioning."},
    {"title": "Nike Revolution 6",         "brand": "Nike",  "category": "shoes", "color": "black", "size": "42", "price":  55.0, "rating": 4.3, "in_stock": True,  "description": "Affordable everyday running shoe."},
    {"title": "Adidas Ultraboost 22",      "brand": "Adidas","category": "shoes", "color": "white", "size": "43", "price": 149.0, "rating": 4.7, "in_stock": True,  "description": "Premium boost cushioning for long runs."},
    {"title": "Apple iPhone 15",           "brand": "Apple", "category": "phones","color": "black", "size": "",   "price": 799.0, "rating": 4.8, "in_stock": True,  "description": "Latest A17 chip, USB-C, great cameras."},
    {"title": "Sony WH-1000XM5",           "brand": "Sony",  "category": "headphones","color":"black","size":"","price": 349.0, "rating": 4.7, "in_stock": True,  "description": "Industry-leading noise cancellation."},
    {"title": "Bose QuietComfort 45",      "brand": "Bose",  "category": "headphones","color":"white","size":"","price": 279.0, "rating": 4.5, "in_stock": False, "description": "Comfortable ANC over-ear headphones."},
]


async def _seed(es: Any, index: str) -> None:
    if await es.indices.exists(index=index):
        await es.indices.delete(index=index)
    await es.indices.create(index=index, body=build_default_index_mapping())
    for i, doc in enumerate(_SAMPLE_PRODUCTS):
        await es.index(index=index, id=str(i), document=doc, refresh=False)
    await es.indices.refresh(index=index)
    print(f"Seeded {len(_SAMPLE_PRODUCTS)} products into '{index}'.")


async def _async_main(args: argparse.Namespace) -> None:
    try:
        from elasticsearch import AsyncElasticsearch  # type: ignore[import-not-found]
    except ImportError as e:
        raise SystemExit(
            "This example needs the async Elasticsearch client. Install it with:\n"
            '    pip install "elasticsearch[async]>=8,<9"'
        ) from e

    es = AsyncElasticsearch(args.url)
    try:
        if args.seed:
            await _seed(es, args.index)

        if not args.query:
            print("Seeded. Re-run with --query \"...\" to ask the agent.")
            return

        assert_llm_credentials(
            hint="If you're hitting Ollama locally, make sure LLM_BASE_URL "
                 "is http://localhost:11434/v1 (mind the /v1 suffix)."
        )

        catalog = ElasticsearchCatalog(es, index=args.index)
        skill   = SearchCatalogSkill(schema=build_schema(), backend=catalog)
        llm     = build_default_llm_client()
        engine  = AgentEngine(
            llm_client=llm,
            system_prompt=(
                "You are Shoply, a friendly shopping assistant. ALWAYS call "
                "search_catalog whenever the user is looking for a product. "
                "Recommend 1-3 items in one short paragraph."
            ),
        )
        engine.register_skill(skill)

        try:
            result = await engine.process(args.query)
        finally:
            await llm.aclose()

        print("\nAssistant>", result.get("reply", ""))
        items = (result.get("data") or {}).get("items", [])
        for it in items[:5]:
            print(f"  - {it.get('title')}  ${it.get('price')}  ({it.get('brand')})")
    finally:
        await es.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Elasticsearch catalog demo.")
    p.add_argument("--url",   default="http://localhost:9200",
                   help="Elasticsearch URL (default: http://localhost:9200).")
    p.add_argument("--index", default="products",
                   help="Index name (default: products).")
    p.add_argument("--seed",  action="store_true",
                   help="Re-create the index and bulk-load sample products.")
    p.add_argument("--query", "-q",
                   help="Natural-language query to send through the agent.")
    asyncio.run(_async_main(p.parse_args()))


if __name__ == "__main__":
    main()
