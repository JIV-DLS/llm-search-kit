"""Registry of available agent skills (Registry pattern).

Role in the architecture
------------------------
Single source of truth for "which tools does the LLM have right now?".
The :class:`AgentEngine` asks the registry for tool schemas before each
LLM call and dispatches tool calls back through it by name.

Two levels of API:

* **Imperative** — ``register(skill)``, ``register_many([...])``: explicit
  list of skills built by the caller. Use this when you want full control.
* **Declarative** — ``discover(module)``: scan a Python module and pick up
  every ``BaseSkill`` instance / ``@skill``-decorated function it exposes.
  Use this so adding a tool to your project = just dropping a function in
  ``my_app/skills.py``, no extra wiring.

Adapted from ``rede/backend/chatbot-service/agent/skill_registry.py`` —
this kit ships an empty registry; callers register their own skills.
"""
from __future__ import annotations

import importlib
import inspect
import logging
from types import ModuleType
from typing import Any, Dict, Iterable, List, Optional, Union

from .base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


# =============================================================================
# Public API
# =============================================================================


class SkillRegistry:
    """Holds and dispatches agent skills."""

    def __init__(self) -> None:
        self._skills: Dict[str, BaseSkill] = {}

    # ----- registration -----------------------------------------------------

    def register(self, skill: BaseSkill) -> None:
        """Register a skill. Overwrites any previous skill with the same name."""
        if not isinstance(skill, BaseSkill):
            raise TypeError(
                f"register() expects a BaseSkill instance, got "
                f"{type(skill).__name__!r}. If you have an @skill-decorated "
                "function, pass the function itself (the decorator already "
                "produced a BaseSkill)."
            )
        self._skills[skill.name] = skill

    def register_many(self, skills: Iterable[BaseSkill]) -> None:
        """Register every skill in ``skills``. Convenience for ``[a, b, c]``."""
        for s in skills:
            self.register(s)

    def discover(self, source: Union[str, ModuleType]) -> List[str]:
        """Auto-discover skills from a Python module and register them.

        Parameters
        ----------
        source:
            Either a module object or its dotted import path
            (``"my_app.skills"``). The module will be imported if needed.

        Returns
        -------
        list[str]
            Names of skills that were registered (in declaration order).

        How discovery works
        -------------------
        We pick up two kinds of attributes from the module:

        1. **Module-level instances of :class:`BaseSkill`**, including
           every ``@skill``-decorated function (the decorator returns a
           ``_DecoratedSkill`` which is a ``BaseSkill``). This is the
           recommended pattern.
        2. **Module-level :class:`BaseSkill` subclasses with a no-arg
           constructor** — instantiated automatically. This is offered as
           a convenience; if your skill needs constructor arguments
           (``base_url``, shared client, …) instantiate it yourself and
           expose the instance instead.

        Private attributes (leading underscore) and re-exports from other
        modules are ignored. The latter prevents the same skill from being
        registered twice if you ``from .other import my_skill`` somewhere.
        """
        module = _ensure_module(source)
        registered: List[str] = []

        for attr_name, attr_value in _iter_public_module_members(module):
            skill_obj = _coerce_to_skill(attr_value, owning_module=module)
            if skill_obj is None:
                continue
            self.register(skill_obj)
            registered.append(skill_obj.name)
            logger.info(
                "[REGISTRY] Auto-registered skill %r from %s.%s",
                skill_obj.name, module.__name__, attr_name,
            )

        if not registered:
            logger.warning(
                "[REGISTRY] discover(%s) found no skills. Did you forget "
                "to apply @skill or to expose your BaseSkill instance at "
                "module level?", module.__name__,
            )
        return registered

    # ----- lookup -----------------------------------------------------------

    def get(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)

    def get_tool_schemas(
        self, skill_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return OpenAI tool schemas for the requested skills (all if None)."""
        skills = list(self._skills.values())
        if skill_names is not None:
            wanted = set(skill_names)
            skills = [s for s in skills if s.name in wanted]
        return [s.to_tool_schema() for s in skills]

    async def execute_skill(
        self, name: str, params: Dict[str, Any],
    ) -> SkillResult:
        """Validate then execute a skill, catching any exception into ``SkillResult``."""
        skill = self.get(name)
        if not skill:
            return SkillResult(success=False, error=f"Unknown skill: {name}")

        validation_error = skill.validate_params(params)
        if validation_error:
            return SkillResult(success=False, error=validation_error)

        try:
            return await skill.execute(**params)
        except Exception as exc:  # noqa: BLE001
            logger.error("[SKILL] %s execution failed: %s", name, exc)
            return SkillResult(success=False, error=str(exc))

    @property
    def skill_names(self) -> List[str]:
        return list(self._skills.keys())


# =============================================================================
# Internal helpers — discovery
# =============================================================================


def _ensure_module(source: Union[str, ModuleType]) -> ModuleType:
    """Accept a module or its dotted path and return the module object."""
    if isinstance(source, ModuleType):
        return source
    if isinstance(source, str):
        return importlib.import_module(source)
    raise TypeError(
        f"discover() expects a module or a dotted import string, got "
        f"{type(source).__name__!r}."
    )


def _iter_public_module_members(module: ModuleType):
    """Yield ``(name, value)`` for every public attribute of ``module``.

    "Public" means it doesn't start with an underscore. We sort by name
    so registration order is deterministic across Python versions (some
    older ``dir()`` implementations don't preserve insertion order).
    """
    for attr_name in sorted(vars(module)):
        if attr_name.startswith("_"):
            continue
        yield attr_name, getattr(module, attr_name)


def _coerce_to_skill(
    value: Any, *, owning_module: ModuleType,
) -> Optional[BaseSkill]:
    """Decide whether ``value`` should be auto-registered as a skill.

    Returns the ``BaseSkill`` instance to register, or ``None`` if the
    value is not a skill, is a re-export from another module, or is a
    subclass that we cannot instantiate without arguments.
    """
    if isinstance(value, BaseSkill):
        return value

    if inspect.isclass(value) and issubclass(value, BaseSkill):
        # Skip re-exports: only auto-instantiate classes defined in the
        # module the user pointed us at, otherwise we'd pick up
        # ``SearchCatalogSkill`` itself any time the user does
        # ``from llm_search_kit import SearchCatalogSkill``.
        if value.__module__ != owning_module.__name__:
            return None
        try:
            return value()  # type: ignore[call-arg]
        except TypeError:
            logger.debug(
                "[REGISTRY] Skipping %s: requires constructor arguments. "
                "Instantiate it yourself and expose the instance.",
                value.__name__,
            )
            return None

    return None
