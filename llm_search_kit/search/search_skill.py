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
    ) -> None:
        if default_limit <= 0:
            raise ValueError("default_limit must be positive")
        self._schema = schema
        self._backend = backend
        self._name = name
        self._description = description
        self._default_limit = default_limit
        self._default_sort_by = default_sort_by
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
            if total > 0:
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
