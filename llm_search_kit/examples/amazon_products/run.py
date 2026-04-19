"""CLI runner for the Amazon-products demo.

Usage:
    python -m llm_search_kit.examples.amazon_products.run
    python -m llm_search_kit.examples.amazon_products.run --query "red Nike size 42 under 100$"
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import List, Dict

from llm_search_kit import AgentEngine, SearchCatalogSkill
from llm_search_kit.config import assert_llm_credentials, build_default_llm_client

from .catalog import InMemoryAmazonCatalog
from .schema import build_schema

_SOUL_PATH = Path(__file__).parent / "soul.md"


def _load_soul() -> str:
    try:
        return _SOUL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "You are a helpful shopping assistant."


async def _run_one(engine: AgentEngine, query: str, history: List[Dict[str, str]]) -> None:
    result = await engine.process(query, conversation_history=history)
    reply = result.get("reply", "")
    print("\nAssistant>", reply)
    if result.get("data"):
        items = result["data"].get("items", [])
        if items:
            print("\nTop results:")
            for it in items[:5]:
                print(
                    f"  - {it.get('title')}  ${it.get('price')}  "
                    f"({it.get('brand')}, rating {it.get('rating')})"
                )
        if result["data"].get("relaxation_level", 0) > 0:
            print(
                f"  (filters were relaxed to level "
                f"{result['data']['relaxation_level']})"
            )
    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": reply})


async def _async_main(args: argparse.Namespace) -> None:
    assert_llm_credentials(
        hint="If you're hitting Ollama locally, make sure LLM_BASE_URL "
             "is http://localhost:11434/v1 (mind the /v1 suffix)."
    )

    llm = build_default_llm_client()
    catalog = InMemoryAmazonCatalog()
    skill = SearchCatalogSkill(schema=build_schema(), backend=catalog)

    engine = AgentEngine(llm_client=llm, system_prompt=_load_soul())
    engine.register_skill(skill)

    history: List[Dict[str, str]] = []
    try:
        if args.query:
            await _run_one(engine, args.query, history)
            if args.json:
                last = await engine.process(args.query, conversation_history=history[:-2])
                print("\nRaw payload:")
                print(json.dumps(last, indent=2, default=str))
            return

        print("Shoply demo. Type 'exit' to quit.\n")
        while True:
            try:
                user_input = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", ":q"}:
                break
            await _run_one(engine, user_input, history)
    finally:
        catalog.close()
        await llm.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Shoply demo agent.")
    parser.add_argument(
        "--query", "-q",
        help="Run a single query and exit (skip the interactive REPL).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="When used with --query, also print the raw engine payload.",
    )
    args = parser.parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
