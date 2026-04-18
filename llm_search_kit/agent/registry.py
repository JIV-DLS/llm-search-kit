"""Registry of available agent skills (Factory pattern).

Adapted from ``rede/backend/chatbot-service/agent/skill_registry.py`` -- here
it is empty by default; callers register their own skills.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base_skill import BaseSkill, SkillResult

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Holds and dispatches agent skills."""

    def __init__(self) -> None:
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """Register a skill. Overwrites any previous skill with the same name."""
        self._skills[skill.name] = skill

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
