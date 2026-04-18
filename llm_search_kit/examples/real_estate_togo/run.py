"""CLI runner for the real-estate (Togo) demo.

Usage:
    # in-memory demo (no backend required):
    python -m llm_search_kit.examples.real_estate_togo.run

    # against your own REST endpoint:
    REAL_ESTATE_API_URL=https://api.example.com \
        python -m llm_search_kit.examples.real_estate_togo.run --backend http
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import List, Dict

from llm_search_kit import AgentEngine, SearchCatalogSkill
from llm_search_kit.config import build_default_llm_client, llm_api_key

from .catalog import HttpRealEstateCatalog, InMemoryRealEstateCatalog
from .schema import build_schema

_SOUL_PATH = Path(__file__).parent / "soul.md"


def _load_soul() -> str:
    try:
        return _SOUL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Tu es Afa, l'assistant immobilier."


def _build_catalog(kind: str):
    if kind == "http":
        url = os.getenv("REAL_ESTATE_API_URL", "").strip()
        if not url:
            raise SystemExit(
                "REAL_ESTATE_API_URL is not set. "
                "Set it to your backend's base URL or use --backend memory."
            )
        return HttpRealEstateCatalog(base_url=url)
    return InMemoryRealEstateCatalog()


async def _run_one(engine: AgentEngine, query: str, history: List[Dict[str, str]]) -> None:
    result = await engine.process(query, conversation_history=history)
    reply = result.get("reply", "")
    print("\nAfa>", reply)
    if result.get("data"):
        items = result["data"].get("items", [])
        if items:
            print("\nRésultats:")
            for it in items[:5]:
                price = it.get("loyer_mensuel") or it.get("prix_vente")
                print(
                    f"  - {it.get('title')} | {it.get('city')}/{it.get('quartier')} | "
                    f"{price} FCFA"
                )
        if result["data"].get("relaxation_level", 0) > 0:
            print(
                f"  (filtres élargis au niveau "
                f"{result['data']['relaxation_level']})"
            )
    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": reply})


async def _async_main(args: argparse.Namespace) -> None:
    if not llm_api_key():
        raise SystemExit(
            "LLM_API_KEY is not set. Copy .env.example to .env and fill it in."
        )

    llm = build_default_llm_client()
    catalog = _build_catalog(args.backend)
    skill = SearchCatalogSkill(schema=build_schema(), backend=catalog)

    engine = AgentEngine(llm_client=llm, system_prompt=_load_soul())
    engine.register_skill(skill)

    history: List[Dict[str, str]] = []
    try:
        if args.query:
            await _run_one(engine, args.query, history)
            return

        print("Démo Afa (assistant immobilier). Tape 'exit' pour quitter.\n")
        while True:
            try:
                user_input = input("Vous> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", ":q"}:
                break
            await _run_one(engine, user_input, history)
    finally:
        await catalog.aclose()
        await llm.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Démo Afa (immobilier Togo).")
    parser.add_argument(
        "--query", "-q",
        help="Lance une seule requête puis quitte (sans REPL).",
    )
    parser.add_argument(
        "--backend", choices=["memory", "http"], default="memory",
        help="Backend catalogue: 'memory' (démo intégrée) ou 'http' (REAL_ESTATE_API_URL).",
    )
    args = parser.parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
