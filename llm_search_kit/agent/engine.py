"""Agent Engine -- core tool-calling loop.

Adapted from ``rede/backend/chatbot-service/agent/engine.py``, stripped of:
  * metering / authorization / token accounting;
  * the ``SOUL.md`` auto-loader (the system prompt is now passed in);
  * "unified mode" / dynamic tool filtering by phase;
  * state-mutation plumbing;
  * pipeline phases and rede-specific context keys.

The remaining algorithm is the standard ReAct-style tool loop:
  1. Send messages + tool schemas to the LLM.
  2. If it returns ``tool_calls``, execute each, append results, loop.
  3. Otherwise return its text content as the final reply.
  4. Bail out after ``max_iterations`` to avoid infinite loops.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ..llm.base import BaseLLMClient
from .base_skill import BaseSkill
from .registry import SkillRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_TEMPERATURE = 0.3

MSG_TECHNICAL_ERROR = (
    "I ran into a technical issue. Please try again in a moment."
)
MSG_MAX_ITERATIONS = (
    "I'm having trouble completing that request. Could you rephrase?"
)


class AgentEngine:
    """Tool-calling loop on top of any OpenAI-compatible LLM client."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        *,
        system_prompt: str = "",
        skill_registry: Optional[SkillRegistry] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        temperature: float = DEFAULT_TEMPERATURE,
        history_limit: int = 12,
    ) -> None:
        self._llm = llm_client
        self._registry = skill_registry or SkillRegistry()
        self._system_prompt = system_prompt or ""
        self._max_iterations = max(1, max_iterations)
        self._temperature = temperature
        self._history_limit = max(0, history_limit)

    def register_skill(self, skill: BaseSkill) -> None:
        """Convenience: register a skill on the underlying registry."""
        self._registry.register(skill)

    @property
    def available_skills(self) -> List[str]:
        return self._registry.skill_names

    async def process(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the agentic loop and return ``{reply, tool_calls, data}``.

        ``conversation_history`` is a list of ``{role, content}`` dicts.
        ``context`` is forwarded into every skill call as additional kwargs
        (under the ``__context__`` key) -- useful for passing user_id, locale,
        auth tokens, etc.
        """
        context = context or {}
        messages = self._build_messages(user_message, conversation_history)
        tools = self._registry.get_tool_schemas() or None

        all_tool_calls: List[Dict[str, Any]] = []
        last_data: Optional[Dict[str, Any]] = None

        for iteration in range(1, self._max_iterations + 1):
            response = await self._llm.chat_completion(
                messages=messages,
                tools=tools,
                temperature=self._temperature,
            )

            if not response:
                logger.error("[AGENT] LLM returned no response (iter %d)", iteration)
                return self._make_result(MSG_TECHNICAL_ERROR, all_tool_calls, last_data)

            choices = response.get("choices") or [{}]
            message = (choices[0] or {}).get("message", {}) or {}

            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                messages.append(message)
                await self._execute_tool_calls(
                    tool_calls, messages, all_tool_calls, context,
                )
                if all_tool_calls:
                    last = all_tool_calls[-1].get("result", {})
                    if isinstance(last, dict) and last.get("data") is not None:
                        last_data = last["data"]
                continue

            reply = message.get("content") or ""
            return self._make_result(reply, all_tool_calls, last_data)

        logger.warning("[AGENT] Max iterations (%d) reached", self._max_iterations)
        last_reply = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                last_reply = msg["content"]
                break
        return self._make_result(
            last_reply or MSG_MAX_ITERATIONS, all_tool_calls, last_data,
        )

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
        all_tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> None:
        """Execute every tool call in sequence and append its result."""
        for tc in tool_calls:
            func = tc.get("function", {}) or {}
            skill_name = func.get("name", "")
            try:
                params = json.loads(func.get("arguments", "{}") or "{}")
            except json.JSONDecodeError:
                params = {}

            if context:
                params.setdefault("__context__", context)

            logger.info(
                "[AGENT] Calling skill: %s(%s)",
                skill_name,
                {k: v for k, v in params.items() if k != "__context__"},
            )

            result = await self._registry.execute_skill(skill_name, params)
            result_dump = result.model_dump()

            all_tool_calls.append({
                "skill": skill_name,
                "params": {k: v for k, v in params.items() if k != "__context__"},
                "result": result_dump,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": json.dumps(result_dump, default=str),
            })

    def _build_messages(
        self,
        user_message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        if history and self._history_limit > 0:
            for msg in history[-self._history_limit:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})
        return messages

    @staticmethod
    def _make_result(
        reply: str,
        tool_calls: List[Dict[str, Any]],
        data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {"reply": reply, "tool_calls": tool_calls, "data": data}
