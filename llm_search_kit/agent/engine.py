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

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from ..llm.base import BaseLLMClient
from .base_skill import BaseSkill
from .hooks import AgentHooks, NoOpHooks
from .registry import SkillRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOOL_CALL_CONCURRENCY = 5

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
        tool_call_concurrency: int = DEFAULT_TOOL_CALL_CONCURRENCY,
        hooks: Optional[AgentHooks] = None,
    ) -> None:
        self._llm = llm_client
        self._registry = skill_registry or SkillRegistry()
        self._system_prompt = system_prompt or ""
        self._max_iterations = max(1, max_iterations)
        self._temperature = temperature
        self._history_limit = max(0, history_limit)
        self._tool_call_concurrency = max(1, tool_call_concurrency)
        self._hooks: AgentHooks = hooks or NoOpHooks()

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

        try:
            for iteration in range(1, self._max_iterations + 1):
                await self._hooks.on_iteration_start(iteration, messages)
                await self._hooks.on_llm_start(iteration, messages, tools)

                t0 = time.monotonic()
                response = await self._llm.chat_completion(
                    messages=messages,
                    tools=tools,
                    temperature=self._temperature,
                )
                llm_latency_ms = (time.monotonic() - t0) * 1000.0
                await self._hooks.on_llm_end(iteration, response, llm_latency_ms)

                if not response:
                    logger.error(
                        "[AGENT] LLM returned no response (iter %d)", iteration,
                    )
                    await self._hooks.on_iteration_end(iteration)
                    result = self._make_result(
                        MSG_TECHNICAL_ERROR, all_tool_calls, last_data,
                    )
                    await self._hooks.on_final_reply(
                        result["reply"], iteration, all_tool_calls,
                    )
                    return result

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
                    await self._hooks.on_iteration_end(iteration)
                    continue

                reply = message.get("content") or ""
                await self._hooks.on_iteration_end(iteration)
                result = self._make_result(reply, all_tool_calls, last_data)
                await self._hooks.on_final_reply(reply, iteration, all_tool_calls)
                return result

            logger.warning(
                "[AGENT] Max iterations (%d) reached", self._max_iterations,
            )
            last_reply = ""
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    last_reply = msg["content"]
                    break
            final_reply = last_reply or MSG_MAX_ITERATIONS
            result = self._make_result(final_reply, all_tool_calls, last_data)
            await self._hooks.on_final_reply(
                final_reply, self._max_iterations, all_tool_calls,
            )
            return result
        except Exception as exc:
            await self._hooks.on_error(exc)
            raise

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
        all_tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> None:
        """Execute every tool call concurrently and append results in order.

        OpenAI / Mammouth / Groq routinely emit several ``tool_calls`` in the
        same assistant turn (e.g. ``list_categories`` + ``search_catalog`` to
        cross-reference). Running them sequentially multiplied total latency
        by N. We now fan them out under a semaphore (default 5) and rejoin
        results in the original order so the ``tool`` messages line up with
        the ``tool_call_id``s OpenAI expects.
        """
        if not tool_calls:
            return

        sem = asyncio.Semaphore(self._tool_call_concurrency)

        async def _run_one(tc: Dict[str, Any]) -> Dict[str, Any]:
            func = tc.get("function", {}) or {}
            skill_name = func.get("name", "")
            tc_id = tc.get("id", "")
            try:
                params = json.loads(func.get("arguments", "{}") or "{}")
            except json.JSONDecodeError:
                params = {}

            if context:
                params.setdefault("__context__", context)

            visible_params = {k: v for k, v in params.items() if k != "__context__"}
            logger.info("[AGENT] Calling skill: %s(%s)", skill_name, visible_params)

            await self._hooks.on_tool_start(skill_name, visible_params, tc_id)
            t0 = time.monotonic()
            async with sem:
                result = await self._registry.execute_skill(skill_name, params)
            latency_ms = (time.monotonic() - t0) * 1000.0
            await self._hooks.on_tool_end(
                skill_name, visible_params, tc_id, result, latency_ms,
            )

            return {
                "tool_call_id": tc_id,
                "skill": skill_name,
                "params": visible_params,
                "result": result.model_dump(),
            }

        executed = await asyncio.gather(
            *[_run_one(tc) for tc in tool_calls], return_exceptions=False,
        )

        for entry in executed:
            all_tool_calls.append({
                "skill": entry["skill"],
                "params": entry["params"],
                "result": entry["result"],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": entry["tool_call_id"],
                "content": json.dumps(entry["result"], default=str),
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
