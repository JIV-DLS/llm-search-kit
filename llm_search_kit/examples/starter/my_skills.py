"""Your project's skills — one ``@skill``-decorated function per tool.

This file is the **only place a developer needs to touch** to teach the
LLM a new capability. The flow is:

1. Write an ``async def`` with type-hinted parameters and ``Field(...)``
   descriptions.
2. Decorate it with ``@skill(description=...)``.
3. ...there is no step 3. The kit auto-discovers it.

The wiring in ``service.py`` calls ``engine.discover_skills(my_skills)``
which scans this module for ``BaseSkill`` instances (every decorated
function returns one) and registers them automatically.

Every tool below is a runnable demo with NO external dependencies, so
the starter works out of the box. Replace them with your real tools.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field

from llm_search_kit import SkillResult, skill


# =============================================================================
# Demo tool 1 — pure-Python calculation
# =============================================================================


@skill(description="Convert an amount from one currency to another using fixed demo rates.")
async def convert_currency(
    amount: float = Field(..., description="Amount to convert."),
    from_ccy: str = Field(..., description="Source currency code, e.g. EUR or USD."),
    to_ccy: str = Field(..., description="Target currency code, e.g. XOF or EUR."),
) -> SkillResult:
    """Pure-Python skill — no HTTP, no DB. The simplest possible tool."""
    rates_to_xof = {"EUR": 655.957, "USD": 600.0, "XOF": 1.0}

    from_rate = rates_to_xof.get(from_ccy.upper())
    to_rate = rates_to_xof.get(to_ccy.upper())
    if from_rate is None or to_rate is None:
        return SkillResult(
            success=False,
            error=f"Unsupported currency pair {from_ccy} -> {to_ccy}",
            message="Supported codes: EUR, USD, XOF.",
        )

    converted = amount * from_rate / to_rate
    return SkillResult(
        success=True,
        data={"converted": round(converted, 2), "from": from_ccy, "to": to_ccy},
    )


# =============================================================================
# Demo tool 2 — uses the per-request context
# =============================================================================


@skill(description="Greet the current user. Says hello in their preferred language if known.")
async def greet_user(
    name: str = Field(..., description="The user's display name."),
    formal: bool = Field(False, description="Use a formal salutation if true."),
    ctx: Optional[Dict[str, Any]] = None,
) -> SkillResult:
    """Demonstrates how to read the per-request ``ctx`` injected by the engine.

    The engine forwards the ``context=`` dict you pass to
    ``engine.process(...)`` to every skill that declares a ``ctx`` (or
    ``context``) parameter. Use this to thread tenant ids, auth tokens,
    feature flags, etc. without making them globals.
    """
    language = (ctx or {}).get("language", "en")
    greetings = {
        "en": ("Good day, {n}." if formal else "Hi {n}!"),
        "fr": ("Bonjour {n}." if formal else "Salut {n} !"),
        "ewe": "Ndi {n}.",
    }
    template = greetings.get(language, greetings["en"])
    return SkillResult(success=True, data={"greeting": template.format(n=name)})
