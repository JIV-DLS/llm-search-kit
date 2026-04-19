"""Worked example: a *second* skill plugged into the Beasy agent.

Goal of this file: give Armand (or anyone forking the kit) a copy-pastable
recipe for adding a new tool to the agent **without** touching ``soul.md``,
``schema.py``, or ``catalog.py``. Adding a tool is a 3-step exercise:

    1. Subclass :class:`llm_search_kit.BaseSkill`. Define ``name``,
       ``description`` and ``parameters_schema`` (this is what the LLM sees
       and uses to decide *when* to call you and *with what arguments*).
    2. Implement ``async def execute(self, **kwargs) -> SkillResult``: this
       is the actual side-effect (HTTP call, DB query, computation, ...).
    3. Register the skill on the engine
       (``engine.register_skill(MySkill(...))``). The kit's ReAct loop
       (``AgentEngine.process``) will pick it up automatically — the LLM
       routes between ``search_catalog`` and your new tool on its own.

This file uses Beasy's hypothetical ``GET /api/v1/categories`` endpoint as
a pretext. The same template applies to any other route Spring exposes
(brands, orders, delivery quotes, user profile, …).

Why is this useful? When the user asks something like "what categories
do you have?" or "show me all brands", the LLM should NOT call
``search_catalog`` (which expects an intent + filters). It should call
this thin browse-the-taxonomy tool instead. Adding it lets the agent
*self-onboard* the user with no new plumbing in ``soul.md``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from llm_search_kit.agent.base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class CategoriesSkill(BaseSkill):
    """List the categories exposed by the Beasy Spring backend.

    Wraps ``GET /api/v1/categories`` (or any URL you pass to ``endpoint``).
    Returned items are trimmed to ``{id, nameEn, nameFr, parentId}`` so we
    don't dump 50 KB of nested taxonomy into the LLM context window.
    """

    # ------------------------------------------------------------------ ctor
    def __init__(
        self,
        base_url: str,
        *,
        endpoint: str = "/api/v1/categories",
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 10.0,
        headers: Optional[Dict[str, str]] = None,
        max_returned: int = 200,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout
        self._headers = {
            "Accept":                     "application/json",
            "ngrok-skip-browser-warning": "true",
            **(headers or {}),
        }
        if max_returned <= 0:
            raise ValueError("max_returned must be positive")
        self._max_returned = max_returned

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------ BaseSkill
    @property
    def name(self) -> str:
        # The LLM picks tools by name. Keep it stable, snake_case, verb-y.
        return "list_categories"

    @property
    def description(self) -> str:
        # Critical for routing: this sentence is how the LLM decides
        # whether *this* tool is a better fit than ``search_catalog``.
        return (
            "List the product categories available in the catalog. "
            "Call this when the user asks what kinds of products are "
            "sold (e.g. 'what do you sell?', 'show me the categories', "
            "'quels rayons avez-vous ?'). Do NOT call this for product "
            "queries — use ``search_catalog`` instead."
        )

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        # JSON Schema that the LLM will populate. Keep it minimal —
        # every extra parameter is one more thing the LLM can get wrong.
        return {
            "type": "object",
            "properties": {
                "parent_id": {
                    "type": "integer",
                    "description": (
                        "If set, only return sub-categories of this parent. "
                        "Omit to list top-level categories."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max number of categories to return (default and "
                        f"hard cap: {200})."
                    ),
                },
            },
            "required": [],
        }

    # --------------------------------------------------------------- execute
    async def execute(self, **kwargs: Any) -> SkillResult:
        # Strip the kit's internal ``__context__`` injection. Every skill
        # that takes **kwargs from the engine should do this.
        kwargs.pop("__context__", None)

        parent_id = kwargs.get("parent_id")
        limit = int(kwargs.get("limit") or self._max_returned)
        limit = max(1, min(limit, self._max_returned))

        params: Dict[str, Any] = {}
        if parent_id is not None:
            params["parentId"] = int(parent_id)

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            url = f"{self._base_url}{self._endpoint}"
            logger.debug("[CATEGORIES] GET %s params=%s", url, params)
            resp = await client.get(url, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            logger.warning("[CATEGORIES] HTTP error: %s", exc)
            return SkillResult(
                success=False,
                error=f"backend_unreachable: {exc}",
                message="I couldn't reach the catalog right now.",
            )
        finally:
            if self._client is None:
                await client.aclose()

        if resp.status_code >= 400:
            text = (resp.text or "")[:300]
            return SkillResult(
                success=False,
                error=f"http_{resp.status_code}",
                message=f"Categories endpoint returned {resp.status_code}: {text}",
            )

        try:
            payload = resp.json()
        except ValueError:
            return SkillResult(
                success=False,
                error="invalid_json",
                message="Categories endpoint did not return JSON.",
            )

        items = self._normalise(payload)[:limit]

        return SkillResult(
            success=True,
            data={
                "categories": items,
                "total":      len(items),
                "parent_id":  parent_id,
            },
            message=f"Found {len(items)} categor" + (
                "y" if len(items) == 1 else "ies"
            ),
        )

    # ----------------------------------------------------------- internals
    @staticmethod
    def _normalise(payload: Any) -> List[Dict[str, Any]]:
        """Flatten the payload into a list of ``{id, nameEn, nameFr, parentId}``.

        Accepts either a bare list or a ``{categories: [...]}`` envelope
        (Spring controllers vary).
        """
        raw: List[Any]
        if isinstance(payload, list):
            raw = payload
        elif isinstance(payload, dict):
            raw = (
                payload.get("categories")
                or payload.get("content")
                or payload.get("items")
                or []
            )
        else:
            raw = []

        out: List[Dict[str, Any]] = []
        for cat in raw:
            if not isinstance(cat, dict):
                continue
            entry = {
                "id":       cat.get("id"),
                "nameEn":   cat.get("nameEn") or cat.get("name"),
                "nameFr":   cat.get("nameFr"),
                "parentId": cat.get("parentId") or (
                    (cat.get("parent") or {}).get("id")
                    if isinstance(cat.get("parent"), dict) else None
                ),
            }
            # Drop empty keys to keep the LLM context tight.
            out.append({k: v for k, v in entry.items() if v is not None})
        return out
