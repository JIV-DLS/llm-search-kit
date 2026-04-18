"""Abstract base class for agent skills.

Each skill exposes:
  * a unique ``name`` (used as the OpenAI function name);
  * a ``description`` (helps the LLM pick when to call it);
  * a ``parameters_schema`` (JSON Schema for arguments);
  * an ``execute`` coroutine that performs the action.

Adapted from ``rede/backend/chatbot-service/agent/skills/base_skill.py`` --
``StateMutation`` was dropped; this kit doesn't manage any conversation state
besides plain message history.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel


class SkillResult(BaseModel):
    """Result returned by a skill execution."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    message: str = ""
    error: Optional[str] = None


class BaseSkill(ABC):
    """Abstract base class for agent skills (Template Method pattern)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this skill (used as the function name in tool calls)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description that helps the LLM pick when to call this."""
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema for the skill's parameters (OpenAI function-calling format)."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute the skill. Subclasses MUST implement."""
        ...

    def to_tool_schema(self) -> Dict[str, Any]:
        """Convert this skill to OpenAI tool-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def validate_params(self, params: Dict[str, Any]) -> Optional[str]:
        """Quick check: every ``required`` field is present. Returns error string or None."""
        required = self.parameters_schema.get("required", [])
        for field in required:
            if field not in params:
                return f"Missing required parameter: {field}"
        return None
