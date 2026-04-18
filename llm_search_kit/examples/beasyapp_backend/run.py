"""CLI runner for the Beasyapp backend example.

Usage::

    cp .env.example .env  # set LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
    export BEASY_BASE_URL=https://actinolitic-glancingly-saturnina.ngrok-free.dev

    # Interactive REPL:
    python -m llm_search_kit.examples.beasyapp_backend.run

    # One-shot:
    python -m llm_search_kit.examples.beasyapp_backend.run \
        --query "samsung tv 4K under 100000"

    # Just probe the backend, no LLM:
    python -m llm_search_kit.examples.beasyapp_backend.run --probe
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from llm_search_kit import AgentEngine, SearchCatalogSkill
from llm_search_kit.config import build_default_llm_client, llm_api_key

from .catalog import BeasyappCatalog
from .schema import build_schema

_DEFAULT_BASE_URL = "https://actinolitic-glancingly-saturnina.ngrok-free.dev"
_SOUL_PATH = Path(__file__).parent / "soul.md"


def _load_soul() -> str:
    try:
        return _SOUL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "You are a helpful shopping assistant."


async def _probe(catalog: BeasyappCatalog, query: str) -> None:
    result = await catalog.search(filters={}, query=query, limit=5)
    print(f"Total: {result['total']}")
    for it in result["items"][:5]:
        title = it.get("title", "?")
        price = it.get("price")
        print(f"  - {title}  ({price} FCFA)")
    facets = (result.get("metadata") or {}).get("facets") or {}
    if facets.get("brands"):
        print("Top brands:", ", ".join(
            f"{b['label']}({b['count']})" for b in facets["brands"][:5]
        ))


async def _run_one(engine: AgentEngine, query: str,
                   history: List[Dict[str, str]]) -> None:
    result = await engine.process(query, conversation_history=history)
    reply = result.get("reply", "")
    print("\nAssistant>", reply)

    data = result.get("data") or {}
    items = data.get("items", [])
    for it in items[:5]:
        print(f"  - {it.get('title')}  {it.get('price')} FCFA")
    if data.get("relaxation_level", 0) > 0:
        print(f"  (filters relaxed to level {data['relaxation_level']})")

    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": reply})


async def _async_main(args: argparse.Namespace) -> None:
    base_url = args.base_url or os.environ.get("BEASY_BASE_URL", _DEFAULT_BASE_URL)
    catalog = BeasyappCatalog(base_url=base_url)

    try:
        if args.probe:
            await _probe(catalog, args.query or "samsung")
            return

        if not llm_api_key():
            raise SystemExit(
                "LLM_API_KEY is not set. Copy .env.example to .env and fill it in."
            )

        llm    = build_default_llm_client()
        skill  = SearchCatalogSkill(schema=build_schema(), backend=catalog)
        engine = AgentEngine(llm_client=llm, system_prompt=_load_soul())
        engine.register_skill(skill)

        try:
            history: List[Dict[str, str]] = []
            if args.query:
                await _run_one(engine, args.query, history)
                if args.json:
                    last = await engine.process(args.query, conversation_history=[])
                    print("\nRaw payload:")
                    print(json.dumps(last, indent=2, default=str)[:5000])
                return

            print("Beasy demo. Type 'exit' to quit.\n")
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
            await llm.aclose()
    finally:
        await catalog.aclose()


def main() -> None:
    p = argparse.ArgumentParser(description="Beasyapp backend agent demo.")
    p.add_argument("--base-url", help=f"Beasy backend URL (default: ${_DEFAULT_BASE_URL!s} or $BEASY_BASE_URL).")
    p.add_argument("--query", "-q", help="One-shot query and exit.")
    p.add_argument("--probe", action="store_true",
                   help="Skip the LLM, just hit the backend with the given query.")
    p.add_argument("--json", action="store_true",
                   help="With --query, also print the raw engine payload.")
    asyncio.run(_async_main(p.parse_args()))


if __name__ == "__main__":
    main()
