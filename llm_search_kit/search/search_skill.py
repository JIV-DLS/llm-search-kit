"""Generic, schema-driven catalog-search skill.

This is the equivalent of
``rede/backend/chatbot-service/agent/skills/search_properties.py``, but
domain-agnostic: the parameters schema is auto-built from a ``SearchSchema``
and the relaxation ladder is driven by the schema's ``drop_priority``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..agent.base_skill import BaseSkill, SkillResult
from .backend import CatalogBackend
from .relaxation import build_relaxation_levels
from .schema import SearchSchema

logger = logging.getLogger(__name__)

DEFAULT_SKILL_NAME = "search_catalog"
DEFAULT_DESCRIPTION = (
    "Search the catalog for items matching the user's request. "
    "Extract structured filters from the user's natural-language query "
    "and call this tool. The tool will progressively relax filters if "
    "no items are found."
)
INTERNAL_PARAM_KEYS = {"query", "sort_by", "skip", "limit", "__context__"}


class SearchCatalogSkill(BaseSkill):
    """Generic search skill: turns LLM-extracted filters into a catalog call."""

    def __init__(
        self,
        schema: SearchSchema,
        backend: CatalogBackend,
        *,
        name: str = DEFAULT_SKILL_NAME,
        description: str = DEFAULT_DESCRIPTION,
        default_limit: int = 10,
        default_sort_by: str = "relevance",
        max_relaxed_total: Optional[int] = None,
        max_relaxed_growth_factor: float = 5.0,
    ) -> None:
        """
        Parameters
        ----------
        max_relaxed_total:
            Hard cap on how many items a *relaxed* level (level > 0) is
            allowed to return before we treat it as "the remaining filters
            stopped discriminating anything" and bail out with an empty
            result instead. Without this guard, some backends (Spring/JPA
            with an empty Specification, ES with an unknown query falling
            back to match_all, etc.) happily return the entire catalog
            once the structured filters get stripped — leading to
            "I asked for a Range Rover and got watches" UX disasters.

            Default ``None`` keeps backward compatibility (no cap). Set
            to e.g. ``50`` for typical product search to mean "if a
            relaxed level matches >50 items, the user did NOT really
            want this — return empty so the UI can ask a clarifying
            question instead".
        max_relaxed_growth_factor:
            Companion safety net for when the backend's total is large
            enough that ``max_relaxed_total`` would still match. If a
            relaxed level returns more than ``factor * level0_total``
            items (and level 0 returned at least one), assume the
            relaxation made the query meaningless. Defaults to 5×.
            Ignored when level 0 returned 0 items (we have no baseline).
        """
        if default_limit <= 0:
            raise ValueError("default_limit must be positive")
        if max_relaxed_total is not None and max_relaxed_total <= 0:
            raise ValueError("max_relaxed_total must be positive when set")
        if max_relaxed_growth_factor <= 1.0:
            raise ValueError("max_relaxed_growth_factor must be > 1.0")
        self._schema = schema
        self._backend = backend
        self._name = name
        self._description = description
        self._default_limit = default_limit
        self._default_sort_by = default_sort_by
        self._max_relaxed_total = max_relaxed_total
        self._max_relaxed_growth_factor = max_relaxed_growth_factor
        self._cached_params_schema = self._build_parameters_schema()

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return self._cached_params_schema

    def _is_runaway_relaxation(
        self,
        level: int,
        total: int,
        level0_total: Optional[int],
    ) -> bool:
        """Return True if a relaxed-level result looks like the backend
        gave up filtering and returned (most of) the catalog.

        Two independent triggers:
          * absolute cap: ``max_relaxed_total`` is set and exceeded;
          * growth ratio: level 0 returned a non-zero baseline and this
            level returned more than ``growth_factor ×`` that baseline.
        """
        if self._max_relaxed_total is not None and total > self._max_relaxed_total:
            return True
        if level0_total and level0_total > 0:
            if total > self._max_relaxed_growth_factor * level0_total:
                return True
        return False

    def _build_parameters_schema(self) -> Dict[str, Any]:
        params = self._schema.to_openai_parameters()
        # Add a few control parameters every search exposes.
        params["properties"].setdefault(
            "query",
            {
                "type": "string",
                "description": (
                    "Free-text search terms (the parts of the user query that "
                    "don't map to a structured filter). Leave empty when all "
                    "intent is captured by structured filters."
                ),
            },
        )
        params["properties"].setdefault(
            "sort_by",
            {
                "type": "string",
                "description": "How to sort results (e.g. relevance, price_asc, newest).",
            },
        )
        params["properties"].setdefault(
            "skip",
            {
                "type": "integer",
                "description": "Pagination offset (number of items to skip).",
            },
        )
        params["properties"].setdefault(
            "limit",
            {
                "type": "integer",
                "description": "Maximum number of items to return.",
            },
        )
        return params

    async def execute(self, **kwargs: Any) -> SkillResult:
        query: str = (kwargs.get("query") or "").strip()
        sort_by: str = kwargs.get("sort_by") or self._default_sort_by
        skip: int = int(kwargs.get("skip") or 0)
        limit: int = int(kwargs.get("limit") or self._default_limit)

        filters: Dict[str, Any] = {}
        for f in self._schema.fields:
            value = kwargs.get(f.name)
            if value is None or value == "" or value == []:
                continue
            filters[f.name] = value
        # Allow free-form extra properties declared in the schema.
        for extra_name in self._schema.extra_properties:
            if extra_name in kwargs and kwargs[extra_name] not in (None, "", []):
                filters[extra_name] = kwargs[extra_name]

        levels = build_relaxation_levels(
            filters,
            drop_priority=self._schema.drop_priority,
            core_keys=self._schema.core_keys,
        )

        last_result: Optional[Dict[str, Any]] = None
        level0_total: Optional[int] = None
        for level, relaxed in enumerate(levels):
            logger.info(
                "[SEARCH] level=%d filters=%s query=%r sort=%s",
                level, relaxed, query, sort_by,
            )
            result = await self._backend.search(
                filters=dict(relaxed),
                query=query,
                sort_by=sort_by,
                skip=skip,
                limit=limit,
            )
            last_result = result
            total = int(result.get("total", len(result.get("items", []))) or 0)
            if level == 0:
                level0_total = total
            if total > 0:
                # Relaxed-level safety: catch backends that "match all"
                # once the structured filters get stripped (Spring with
                # an empty Specification, ES match_all fallback, etc.).
                # Without this, "I want a Range Rover" relaxes to
                # ``filters={}, query="Range Rover"`` and the backend
                # ignores the unknown query → returns the full
                # catalogue. We'd rather honestly say "no match" than
                # return watches and tractors.
                if level > 0 and self._is_runaway_relaxation(level, total, level0_total):
                    logger.warning(
                        "[SEARCH] discarding relaxed level %d (total=%d): "
                        "looks like the remaining filters stopped "
                        "discriminating anything (level0_total=%s, "
                        "max_relaxed_total=%s, growth_factor=%s)",
                        level, total, level0_total,
                        self._max_relaxed_total,
                        self._max_relaxed_growth_factor,
                    )
                    break
                items = result.get("items", [])
                payload: Dict[str, Any] = {
                    "items": items,
                    "total": total,
                    "relaxation_level": level,
                    "filters_used": dict(relaxed),
                    "query": query,
                    "sort_by": sort_by,
                    "skip": skip,
                    "limit": limit,
                }
                if "metadata" in result:
                    payload["metadata"] = result["metadata"]
                msg = f"Found {total} item(s)"
                if level > 0:
                    msg += f" with relaxed filters (level {level})"
                return SkillResult(success=True, data=payload, message=msg)

        empty_payload: Dict[str, Any] = {
            "items": [],
            "total": 0,
            "relaxation_level": len(levels),
            "filters_used": filters,
            "query": query,
            "sort_by": sort_by,
            "skip": skip,
            "limit": limit,
        }
        if last_result and "metadata" in last_result:
            empty_payload["metadata"] = last_result["metadata"]
        return SkillResult(
            success=True,
            data=empty_payload,
            message="No items matched the criteria, even after relaxing filters.",
        )
