"""Pytest fixtures shared across tests."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from llm_search_kit import AgentEngine, BaseLLMClient, BaseSkill, SkillResult


class ScriptedLLMClient(BaseLLMClient):
    """Test double that replays a fixed list of pre-baked LLM responses.

    Each response is either:
      * a string -> wrapped into a final assistant message;
      * a list of tool-call dicts -> returns an assistant message with those
        tool_calls and an empty content;
      * a full OpenAI-shaped dict -> returned as-is.
    """

    def __init__(self, responses: List[Any]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        self.calls.append({
            "messages": list(messages),
            "tools": tools,
        })
        if not self._responses:
            return {"choices": [{"message": {"role": "assistant", "content": ""}}]}
        scripted = self._responses.pop(0)
        if scripted is None:
            return None
        if isinstance(scripted, dict) and "choices" in scripted:
            return scripted
        if isinstance(scripted, str):
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": scripted},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        if isinstance(scripted, list):
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": scripted,
                    },
                    "finish_reason": "tool_calls",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        raise TypeError(f"Unsupported scripted response: {scripted!r}")


def make_tool_call(call_id: str, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class EchoSkill(BaseSkill):
    """A trivial skill that echoes its arguments back as data."""

    def __init__(self, name: str = "echo"):
        self._name = name
        self.calls: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Echo the given arguments back."

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to echo back."},
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> SkillResult:
        clean = {k: v for k, v in kwargs.items() if k != "__context__"}
        self.calls.append(clean)
        return SkillResult(
            success=True,
            data={"echoed": clean.get("text", "")},
            message="ok",
        )


@pytest.fixture
def make_engine():
    def _factory(responses: List[Any], skills: Optional[List[BaseSkill]] = None,
                 max_iterations: int = 10) -> AgentEngine:
        llm = ScriptedLLMClient(responses)
        engine = AgentEngine(
            llm_client=llm,
            system_prompt="test system",
            max_iterations=max_iterations,
        )
        for s in skills or []:
            engine.register_skill(s)
        engine._test_llm = llm  # type: ignore[attr-defined]
        return engine

    return _factory
