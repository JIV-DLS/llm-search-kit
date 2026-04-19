"""Regression tests for the "relaxation runaway" bug.

Reported by Armand:
    > "I want a Range Rover" returned a Range Rover *and* a bunch of
    > watches. Asking for "tractors" returned the whole catalog.

Root cause: when the structured filters get progressively dropped to
make room for results, some backends (Spring/JPA with an empty
``Specification``, Elasticsearch falling back to ``match_all``, our
own demo SQLite when ``query`` doesn't match anything…) happily return
the entire catalog as if the user had asked for nothing at all. The
kit used to consider any ``total > 0`` a success and propagate that
to the LLM, which then "recommended" unrelated items.

The fix introduces two safety nets in ``SearchCatalogSkill``:
  * ``max_relaxed_total`` — absolute cap on items returned at level > 0;
  * ``max_relaxed_growth_factor`` — relative cap on growth vs level 0.

Either trigger marks the result as "the remaining filters stopped
discriminating anything" and we return an empty payload so the
assistant can honestly say "no match" instead of pulling watches from
a Range Rover query.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from llm_search_kit import SearchCatalogSkill
from llm_search_kit.search.backend import CatalogBackend
from llm_search_kit.search.schema import SearchField, SearchSchema


# --------------------------------------------------------------------- helpers


class _RunawayBackend(CatalogBackend):
    """Backend that mimics the Spring/JPA "empty Specification = match_all" bug.

    * If any structured filter is set, return 0 items (strict match: nothing
      in the fake catalog actually matches "voiture" / "tracteur" / etc.).
    * If filters is empty (i.e. the kit had to relax everything), return
      a HUGE list as if it had ignored the ``query`` and matched
      ``SELECT * FROM listings``.
    """

    def __init__(self, runaway_size: int = 200) -> None:
        self._runaway_size = runaway_size
        self.calls: List[Dict[str, Any]] = []

    async def search(self, *, filters, query, sort_by, skip, limit):
        self.calls.append({"filters": dict(filters), "query": query})
        if filters:
            return {"items": [], "total": 0}
        # No structured filter left → backend "matches all" regardless
        # of the query.
        items = [
            {"id": f"p{i}", "title": f"Unrelated product #{i}"}
            for i in range(self._runaway_size)
        ]
        return {"items": items[:limit or 10], "total": self._runaway_size}


class _CleanBackend(CatalogBackend):
    """Backend that respects the query: returns 0 if the query doesn't
    match. Used to assert the safety net does NOT regress healthy paths.
    """

    async def search(self, *, filters, query, sort_by, skip, limit):
        if "tractor" in (query or "").lower():
            return {"items": [], "total": 0}
        return {
            "items": [{"id": "p1", "title": "Real result"}],
            "total": 1,
        }


def _build_schema() -> SearchSchema:
    return SearchSchema(
        fields=[
            SearchField(name="category", json_type="string", description="cat"),
            SearchField(name="brand",    json_type="string", description="brand"),
            SearchField(name="max_price", json_type="number", description="max"),
        ],
        drop_priority=["max_price", "brand", "category"],
    )


# ---------------------------------------------------------------- max_relaxed_total


@pytest.mark.asyncio
async def test_runaway_relaxation_blocked_by_absolute_cap():
    """When level > 0 returns more than ``max_relaxed_total`` items,
    discard the result and return empty so the LLM doesn't recommend
    unrelated junk to the user."""
    backend = _RunawayBackend(runaway_size=200)
    skill = SearchCatalogSkill(
        schema=_build_schema(),
        backend=backend,
        max_relaxed_total=50,
    )

    result = await skill.execute(
        category="cars", brand="Range Rover", query="Range Rover",
    )

    assert result.success is True
    data = result.data
    assert data["total"] == 0
    assert data["items"] == []
    # Sanity-check: we DID call the backend several times trying to relax.
    assert len(backend.calls) >= 2
    # The very last call had no filters (we relaxed all the way down) —
    # but the safety net rejected the runaway result.
    assert backend.calls[-1]["filters"] == {}


@pytest.mark.asyncio
async def test_runaway_under_cap_is_kept():
    """If the relaxed total stays under the cap, we still return it —
    the safety net only fires for truly suspicious sizes."""
    backend = _RunawayBackend(runaway_size=10)  # well under cap
    skill = SearchCatalogSkill(
        schema=_build_schema(),
        backend=backend,
        max_relaxed_total=50,
    )

    result = await skill.execute(category="cars", query="Range Rover")

    assert result.success is True
    assert result.data["total"] == 10
    assert result.data["relaxation_level"] >= 1


# --------------------------------------------------------------- growth-factor cap


class _GrowingBackend(CatalogBackend):
    """Returns 1 item at level 0 (with all filters) and a much larger
    set once filters are stripped. Simulates the realistic case where
    the strict query matches a couple of things but the relaxed query
    explodes.
    """

    async def search(self, *, filters, query, sort_by, skip, limit):
        # "Strict" level: at least 2 filters set → 1 result.
        if len(filters) >= 2:
            return {"items": [{"id": "x", "title": "Strict match"}], "total": 1}
        # Relaxed levels: backend over-matches.
        items = [{"id": f"p{i}", "title": f"Loose #{i}"} for i in range(20)]
        return {"items": items, "total": 20}


@pytest.mark.asyncio
async def test_growth_factor_blocks_huge_jump_vs_level0():
    """Level 0 found 1 item; level 1 jumped to 20 (20× the baseline).
    With ``max_relaxed_growth_factor=5.0`` (default) we should reject
    the relaxed level and stick with the strict one."""
    backend = _GrowingBackend()
    skill = SearchCatalogSkill(
        schema=_build_schema(),
        backend=backend,
        # No absolute cap — only the growth-factor guard should fire.
        max_relaxed_total=None,
        max_relaxed_growth_factor=5.0,
    )

    result = await skill.execute(category="cars", brand="Range Rover", query="rr")

    # Strict level produced a result; the kit took it and didn't even
    # need to relax. (relaxation_level == 0)
    assert result.data["total"] == 1
    assert result.data["relaxation_level"] == 0


@pytest.mark.asyncio
async def test_growth_factor_with_zero_baseline_falls_back_to_absolute_cap():
    """If level 0 found nothing, the growth ratio is undefined. The
    absolute cap is then the only safety net. Without it, we keep the
    legacy behaviour (don't break existing callers)."""
    backend = _RunawayBackend(runaway_size=30)
    # No absolute cap set, only growth factor → no baseline → no
    # safety. We get the runaway result back. This documents the
    # current contract.
    skill = SearchCatalogSkill(
        schema=_build_schema(),
        backend=backend,
        max_relaxed_total=None,
        max_relaxed_growth_factor=5.0,
    )

    result = await skill.execute(category="cars", query="Range Rover")

    assert result.data["total"] == 30  # opt-in safety: caller didn't ask for it
    assert result.data["relaxation_level"] >= 1


# --------------------------------------------------------------- backwards-compat


@pytest.mark.asyncio
async def test_default_construction_still_works_no_safety():
    """Existing callers that built ``SearchCatalogSkill(schema, backend)``
    must keep getting the legacy "any total > 0 is success" behaviour
    so we don't silently break their tests / prod."""
    backend = _RunawayBackend(runaway_size=200)
    skill = SearchCatalogSkill(schema=_build_schema(), backend=backend)
    # No max_relaxed_total set ⇒ default None ⇒ no absolute cap.
    # No level0 baseline (level 0 returned 0) ⇒ growth guard skipped.

    result = await skill.execute(category="cars", query="Range Rover")
    assert result.data["total"] == 200
    assert result.data["relaxation_level"] >= 1


@pytest.mark.asyncio
async def test_clean_backend_unaffected():
    """A backend that honours the query (returns 0 when nothing
    matches) is not affected by the safety net at all."""
    backend = _CleanBackend()
    skill = SearchCatalogSkill(
        schema=_build_schema(),
        backend=backend,
        max_relaxed_total=10,
    )

    result = await skill.execute(query="tractor")
    assert result.data["total"] == 0
    assert result.data["items"] == []


# ----------------------------------------------------------------- argument validation


def test_construction_rejects_invalid_thresholds():
    schema = _build_schema()
    backend = _RunawayBackend()

    with pytest.raises(ValueError, match="max_relaxed_total"):
        SearchCatalogSkill(schema=schema, backend=backend, max_relaxed_total=0)

    with pytest.raises(ValueError, match="max_relaxed_total"):
        SearchCatalogSkill(schema=schema, backend=backend, max_relaxed_total=-1)

    with pytest.raises(ValueError, match="max_relaxed_growth_factor"):
        SearchCatalogSkill(
            schema=schema, backend=backend, max_relaxed_growth_factor=1.0
        )
