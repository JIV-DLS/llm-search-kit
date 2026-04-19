"""Tests for ``SkillRegistry.discover()`` and ``register_many()``.

What we lock in
---------------
1. ``register_many`` accepts an iterable of ``BaseSkill`` instances.
2. ``register_many`` rejects non-skills with a clear ``TypeError``.
3. ``discover()`` picks up ``@skill``-decorated functions from a module.
4. ``discover()`` picks up plain ``BaseSkill`` instances from a module.
5. ``discover()`` skips re-exports (skills imported FROM another module).
6. ``discover()`` skips private (underscore) attributes.
7. ``discover()`` accepts a dotted import path string.
8. ``AgentEngine.discover_skills()`` proxies the registry call.
"""
from __future__ import annotations

import types
from typing import Any, Dict, Optional

import pytest
from pydantic import Field

from llm_search_kit import AgentEngine, BaseLLMClient, BaseSkill, SkillResult, skill
from llm_search_kit.agent.registry import SkillRegistry


# =============================================================================
# Fixtures — fake skills + a fake module to scan
# =============================================================================


@skill(description="Test skill A.")
async def skill_a(x: int = Field(..., description="An int.")) -> SkillResult:
    return SkillResult(success=True, data={"x": x})


@skill(description="Test skill B.")
async def skill_b(y: str = Field(..., description="A string.")) -> SkillResult:
    return SkillResult(success=True, data={"y": y})


class HandwrittenSkill(BaseSkill):
    """Plain ``BaseSkill`` subclass with a no-arg constructor."""

    @property
    def name(self) -> str:
        return "handwritten_tool"

    @property
    def description(self) -> str:
        return "A hand-written skill."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> SkillResult:
        return SkillResult(success=True, data={})


def _make_skills_module() -> types.ModuleType:
    """Build an in-memory module that mimics a user's ``my_skills.py``."""
    mod = types.ModuleType("test_user_skills_module")
    mod.skill_a = skill_a
    mod.skill_b = skill_b
    mod.HandwrittenSkill = HandwrittenSkill
    HandwrittenSkill.__module__ = mod.__name__
    mod._private_skill = skill_a  # should be ignored (leading underscore)
    return mod


# =============================================================================
# register_many
# =============================================================================


def test_register_many_accepts_list_of_skills() -> None:
    registry = SkillRegistry()
    registry.register_many([skill_a, skill_b])

    assert set(registry.skill_names) == {"skill_a", "skill_b"}


def test_register_many_rejects_non_skill_with_actionable_error() -> None:
    registry = SkillRegistry()

    with pytest.raises(TypeError, match="BaseSkill"):
        registry.register_many([skill_a, "not_a_skill"])  # type: ignore[list-item]


# =============================================================================
# discover
# =============================================================================


def test_discover_picks_up_decorated_functions_and_subclasses() -> None:
    registry = SkillRegistry()
    module = _make_skills_module()

    registered = registry.discover(module)

    assert set(registered) == {"skill_a", "skill_b", "handwritten_tool"}
    assert set(registry.skill_names) == {"skill_a", "skill_b", "handwritten_tool"}


def test_discover_skips_private_attributes() -> None:
    registry = SkillRegistry()
    module = _make_skills_module()

    registry.discover(module)

    # _private_skill is the SAME object as skill_a, so name collision would
    # silently overwrite — but since it starts with `_` we never look at it.
    # The assertion below proves discovery happened exactly once per name:
    assert len(registry.skill_names) == 3


def test_discover_skips_skills_imported_from_other_modules() -> None:
    """Re-exports must NOT be auto-instantiated.

    If a user does ``from llm_search_kit import SearchCatalogSkill`` in
    their module, we must not blindly try ``SearchCatalogSkill()`` (which
    would crash because it needs ``schema`` + ``backend``).
    """
    from llm_search_kit import SearchCatalogSkill

    mod = types.ModuleType("module_with_reexport")
    mod.SearchCatalogSkill = SearchCatalogSkill  # imported from elsewhere
    mod.local_tool = skill_a  # bound name doesn't matter; skill.name is "skill_a"

    registry = SkillRegistry()
    registered = registry.discover(mod)

    # Only skill_a (an instance, not a class) made it in. SearchCatalogSkill
    # was a class re-exported from another module → correctly skipped.
    assert registered == ["skill_a"]
    assert "search_catalog" not in registry.skill_names


def test_discover_accepts_dotted_path_string() -> None:
    registry = SkillRegistry()
    registered = registry.discover("llm_search_kit.examples.starter.my_skills")

    # The starter ships two demo skills.
    assert set(registered) == {"convert_currency", "greet_user"}


def test_discover_warns_when_module_has_no_skills(caplog: pytest.LogCaptureFixture) -> None:
    empty = types.ModuleType("empty_module")
    registry = SkillRegistry()

    with caplog.at_level("WARNING"):
        registered = registry.discover(empty)

    assert registered == []
    assert any("found no skills" in rec.message for rec in caplog.records)


# =============================================================================
# AgentEngine façade
# =============================================================================


class _DummyLLM(BaseLLMClient):
    """Minimal LLM stub — discover_skills tests don't actually call the LLM."""

    async def chat_completion(
        self,
        messages,
        tools=None,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ):
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


def test_engine_discover_skills_proxies_to_registry() -> None:
    engine = AgentEngine(llm_client=_DummyLLM())

    registered = engine.discover_skills(
        "llm_search_kit.examples.starter.my_skills",
    )

    assert "convert_currency" in registered
    assert "greet_user" in registered
    assert set(engine.available_skills) == set(registered)
