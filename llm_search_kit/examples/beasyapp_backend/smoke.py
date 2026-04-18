"""Manual smoke test that hits a live Beasyapp backend without using an LLM.

Run::

    python -m llm_search_kit.examples.beasyapp_backend.smoke
    # or against a different deployment:
    python -m llm_search_kit.examples.beasyapp_backend.smoke \
        --base-url https://your-tunnel.example.com

It exercises **eight scenarios** end-to-end and prints a one-line PASS/FAIL
verdict per scenario plus a short evidence snippet, so a human can
sanity-check the adapter against the backend without paying for tokens.

Exit code is 0 when every scenario passes, 1 otherwise — handy for CI or a
chronjob health probe.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .catalog import BeasyappAPIError, BeasyappCatalog


_DEFAULT_BASE_URL = "https://actinolitic-glancingly-saturnina.ngrok-free.dev"

_PII_FORBIDDEN = ("email", "password", "phone", "addresses")


@dataclass
class Scenario:
    name: str
    run: Callable[[BeasyappCatalog], Awaitable["Verdict"]]


@dataclass
class Verdict:
    passed: bool
    evidence: str


def _green(s: str) -> str: return f"\033[32m{s}\033[0m"
def _red(s: str)   -> str: return f"\033[31m{s}\033[0m"
def _dim(s: str)   -> str: return f"\033[90m{s}\033[0m"


def _check_pii_clean(items: List[Dict[str, Any]]) -> Optional[str]:
    """Return the offending message if any listing leaks PII, else None."""
    for item in items:
        creator = item.get("creator") or {}
        for forbidden in _PII_FORBIDDEN:
            if forbidden in creator:
                return f"creator.{forbidden} present in listing id={item.get('id')!r}"
    return None


# --------------------------------------------------------------------- scenarios

async def _scen_freetext(cat: BeasyappCatalog) -> Verdict:
    out = await cat.search(filters={}, query="samsung", limit=3)
    leak = _check_pii_clean(out["items"])
    if leak:
        return Verdict(False, f"PII leak: {leak}")
    titles = [it.get("title", "?") for it in out["items"]]
    return Verdict(True, f"total={out['total']} examples={titles[:2]}")


async def _scen_match_all(cat: BeasyappCatalog) -> Verdict:
    out = await cat.search(filters={}, query="", limit=3)
    if out["total"] <= 0:
        return Verdict(False, f"expected at least 1 listing, got total={out['total']}")
    return Verdict(True, f"total={out['total']}")


async def _scen_facets(cat: BeasyappCatalog) -> Verdict:
    out = await cat.search(filters={}, query="", limit=1)
    facets = (out.get("metadata") or {}).get("facets") or {}
    have = [k for k in ("brands", "cities", "colors", "priceRanges", "deliveryTypes")
            if k in facets and facets[k]]
    if not have:
        return Verdict(False, f"no facets returned (got keys: {list(facets)})")
    return Verdict(True, f"facets present: {have}")


async def _scen_price_range(cat: BeasyappCatalog) -> Verdict:
    out = await cat.search(filters={"min_price": 1000, "max_price": 5000},
                           query="", limit=20)
    bad = [it for it in out["items"]
           if not (1000 <= float(it.get("price") or 0) <= 5000)]
    if bad:
        return Verdict(False, f"{len(bad)}/{len(out['items'])} items outside [1000,5000]")
    return Verdict(True, f"all {len(out['items'])} items inside price window")


async def _scen_impossible(cat: BeasyappCatalog) -> Verdict:
    out = await cat.search(filters={"min_price": 99_999_999_999},
                           query="samsung", limit=10)
    if out["total"] != 0 or out["items"]:
        return Verdict(False, f"expected zero results, got total={out['total']}")
    return Verdict(True, "total=0 as expected")


async def _scen_sort_asc(cat: BeasyappCatalog) -> Verdict:
    out = await cat.search(filters={}, query="", sort_by="price_asc", limit=10)
    prices = [float(it.get("price") or 0) for it in out["items"]]
    if prices != sorted(prices):
        return Verdict(False, f"prices not ascending: {prices}")
    return Verdict(True, f"prices ascending: {prices[:5]}{'…' if len(prices) > 5 else ''}")


async def _scen_pagination(cat: BeasyappCatalog) -> Verdict:
    p0 = await cat.search(filters={}, query="", sort_by="price_asc",
                          skip=0, limit=5)
    p1 = await cat.search(filters={}, query="", sort_by="price_asc",
                          skip=5, limit=5)
    if p0["total"] < 6:
        return Verdict(True, f"only {p0['total']} listings total, skipping disjointness check")
    ids0 = {it.get("id") for it in p0["items"]}
    ids1 = {it.get("id") for it in p1["items"]}
    overlap = ids0 & ids1
    if overlap:
        return Verdict(False, f"page 0 and page 1 overlap on ids: {overlap}")
    return Verdict(True, f"page0={sorted(ids0)} page1={sorted(ids1)} no overlap")


async def _scen_error_path(cat: BeasyappCatalog) -> Verdict:
    """Hit a deliberately wrong endpoint to make sure errors raise cleanly."""
    bad = BeasyappCatalog(base_url=cat._base_url, endpoint="/api/v1/this-does-not-exist")
    try:
        try:
            await bad.search(filters={}, query="x", limit=1)
        except BeasyappAPIError as e:
            return Verdict(True, f"raised BeasyappAPIError as expected: {str(e)[:80]}")
        except Exception as e:  # noqa: BLE001 -- we want the type info here
            return Verdict(False,
                           f"wrong exception type: {type(e).__name__}: {e}")
        return Verdict(False, "no exception raised when endpoint is wrong")
    finally:
        await bad.aclose()


SCENARIOS: List[Scenario] = [
    Scenario("freetext-search returns scrubbed listings", _scen_freetext),
    Scenario("match-all returns at least one listing",   _scen_match_all),
    Scenario("facets are returned with results",         _scen_facets),
    Scenario("min/max price filters are respected",      _scen_price_range),
    Scenario("impossible filter returns zero",           _scen_impossible),
    Scenario("price_asc sort is monotonic",              _scen_sort_asc),
    Scenario("pagination yields disjoint pages",         _scen_pagination),
    Scenario("HTTP error raises BeasyappAPIError",       _scen_error_path),
]


# --------------------------------------------------------------------- runner


async def _run_all(base_url: str) -> int:
    catalog = BeasyappCatalog(base_url=base_url, timeout=30.0)
    print(_dim(f"Backend: {base_url}"))
    print(_dim(f"Scenarios: {len(SCENARIOS)}"))
    print()

    failures = 0
    try:
        for i, sc in enumerate(SCENARIOS, 1):
            label = f"[{i}/{len(SCENARIOS)}] {sc.name}"
            try:
                v = await sc.run(catalog)
            except BeasyappAPIError as e:
                v = Verdict(False, f"BeasyappAPIError: {str(e)[:120]}")
            except Exception as e:  # noqa: BLE001
                v = Verdict(False, f"{type(e).__name__}: {str(e)[:120]}")

            tag = _green("PASS") if v.passed else _red("FAIL")
            print(f"  {tag}  {label}")
            print(f"        {_dim(v.evidence)}")
            if not v.passed:
                failures += 1
    finally:
        await catalog.aclose()

    print()
    if failures == 0:
        print(_green(f"All {len(SCENARIOS)} scenarios passed."))
        return 0
    print(_red(f"{failures}/{len(SCENARIOS)} scenarios failed."))
    return 1


def main() -> None:
    p = argparse.ArgumentParser(
        description="Smoke-test the Beasyapp adapter against a live backend, no LLM needed."
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("BEASY_BASE_URL", _DEFAULT_BASE_URL),
        help="Beasy backend URL (default: %(default)s).",
    )
    args = p.parse_args()

    sys.exit(asyncio.run(_run_all(args.base_url)))


if __name__ == "__main__":
    main()
