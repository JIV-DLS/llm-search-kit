"""Agent Engine — core ReAct tool-calling loop.

Role in the architecture
------------------------
This module is the **orchestrator** of the kit. Given a user message,
it drives a multi-turn conversation with the LLM, executes any tools
the LLM asks for, and returns a final reply.

Collaborators (injected via ``__init__``)
-----------------------------------------
* :class:`BaseLLMClient` — the LLM transport (OpenAI-compat).
* :class:`SkillRegistry` — owns the registered tools.
* :class:`AgentHooks`   — observability sidecar (default: no-op).

High-level flow (every call to :meth:`AgentEngine.process`)
-----------------------------------------------------------
1. Build the conversation messages (system + history + user).
2. Loop up to ``max_iterations`` times:
     a. Ask the LLM ``chat_completion(messages, tools)``.
     b. If it returned ``tool_calls`` → execute them in parallel,
        append results, loop again.
     c. Otherwise return its ``content`` as the final reply.
3. If the loop exhausts without a final reply, surface a graceful
   "I couldn't finish" message instead of looping forever.

Adapted from ``rede/backend/chatbot-service/agent/engine.py`` — the
metering / authorization / SOUL-loader / pipeline-phases plumbing was
intentionally dropped for this kit.
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


# =============================================================================
# Defaults & constants
# =============================================================================

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_TEMPERATURE = 0.3
DEFAULT_TOOL_CALL_CONCURRENCY = 5

MSG_TECHNICAL_ERROR = (
    "I ran into a technical issue. Please try again in a moment."
)
MSG_MAX_ITERATIONS = (
    "I'm having trouble completing that request. Could you rephrase?"
)


# =============================================================================
# Public API
# =============================================================================


class AgentEngine:
    """ReAct tool-calling loop on top of any OpenAI-compatible LLM client.

    Collaborators
    -------------
    llm_client : BaseLLMClient
        The transport. The engine only ever calls ``chat_completion``.
    skill_registry : SkillRegistry
        Holds the available tools. The engine asks for their schemas
        before each LLM call and dispatches by name.
    hooks : AgentHooks
        Observability hooks (no-op by default). See ``hooks.py``.
    """

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

    # ----- skill registration ------------------------------------------------

    def register_skill(self, skill: BaseSkill) -> None:
        """Register a skill on the underlying registry. Convenience method."""
        self._registry.register(skill)

    def register_skills(self, skills) -> None:
        """Register every skill in ``skills`` (iterable). Convenience method."""
        self._registry.register_many(skills)

    def discover_skills(self, source) -> List[str]:
        """Auto-discover skills from a module or dotted path.

        Equivalent to ``self._registry.discover(source)``. See
        :meth:`SkillRegistry.discover` for the full contract.

        Returns the list of skill names that were registered, so callers
        can assert on it in tests or print it at startup.
        """
        return self._registry.discover(source)

    @property
    def available_skills(self) -> List[str]:
        """Names of every currently registered skill."""
        return self._registry.skill_names

    # ----- main entry point --------------------------------------------------

    async def process(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the agentic loop and return ``{reply, tool_calls, data}``.

        Reads top-to-bottom like a table of contents:

            build messages
              → run ReAct loop (delegates each turn to ``_run_iteration``)
              → fall back to a graceful message if max iterations hit

        Errors raised inside the loop are reported to ``hooks.on_error``
        before being re-raised so callers see the real exception.
        """
        context = context or {}
        messages = self._build_messages(user_message, conversation_history)
        tools = self._registry.get_tool_schemas() or None

        run_state = _RunState()

        try:
            for iteration in range(1, self._max_iterations + 1):
                done = await self._run_iteration(
                    iteration, messages, tools, context, run_state,
                )
                if done:
                    return run_state.result

            return await self._on_max_iterations_reached(messages, run_state)
        except Exception as exc:
            await self._hooks.on_error(exc)
            raise

    # =========================================================================
    # Internal: one ReAct iteration
    # =========================================================================

    async def _run_iteration(
        self,
        iteration: int,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        context: Dict[str, Any],
        run_state: "_RunState",
    ) -> bool:
        """Run a single ReAct turn. Returns True if the loop must stop.

        A turn either:
          * gets ``None`` from the LLM → stop with a technical-error reply;
          * gets ``tool_calls`` → execute them and continue (returns False);
          * gets a final ``content`` → stop with that reply.
        """
        await self._hooks.on_iteration_start(iteration, messages)

        response = await self._call_llm(iteration, messages, tools)
        if response is None:
            await self._finalize_iteration(iteration, run_state, MSG_TECHNICAL_ERROR)
            return True

        message = self._extract_assistant_message(response)
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(message)
            await self._execute_tool_calls(
                tool_calls, messages, run_state.all_tool_calls, context,
            )
            run_state.refresh_last_data()
            await self._hooks.on_iteration_end(iteration)
            return False

        reply = message.get("content") or ""
        await self._finalize_iteration(iteration, run_state, reply)
        return True

    async def _call_llm(
        self,
        iteration: int,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        """Wrap one LLM round-trip with start/end hooks and timing."""
        await self._hooks.on_llm_start(iteration, messages, tools)

        started_at = time.monotonic()
        response = await self._llm.chat_completion(
            messages=messages,
            tools=tools,
            temperature=self._temperature,
        )
        latency_ms = (time.monotonic() - started_at) * 1000.0

        await self._hooks.on_llm_end(iteration, response, latency_ms)

        if response is None:
            logger.error("[AGENT] LLM returned no response (iter %d)", iteration)
        return response

    @staticmethod
    def _extract_assistant_message(response: Dict[str, Any]) -> Dict[str, Any]:
        """Pull ``response.choices[0].message`` defensively from any provider."""
        choices = response.get("choices") or [{}]
        return (choices[0] or {}).get("message", {}) or {}

    async def _finalize_iteration(
        self,
        iteration: int,
        run_state: "_RunState",
        reply: str,
    ) -> None:
        """Emit ``on_iteration_end`` + ``on_final_reply`` and store the result."""
        run_state.set_result(reply)
        await self._hooks.on_iteration_end(iteration)
        await self._hooks.on_final_reply(
            reply, iteration, run_state.all_tool_calls,
        )

    async def _on_max_iterations_reached(
        self,
        messages: List[Dict[str, Any]],
        run_state: "_RunState",
    ) -> Dict[str, Any]:
        """Graceful exit when the model never produced a final answer."""
        logger.warning(
            "[AGENT] Max iterations (%d) reached", self._max_iterations,
        )
        last_reply = self._last_assistant_text(messages) or MSG_MAX_ITERATIONS
        run_state.set_result(last_reply)
        await self._hooks.on_final_reply(
            last_reply, self._max_iterations, run_state.all_tool_calls,
        )
        return run_state.result

    # =========================================================================
    # Internal: tool-call fan-out (parallel)
    # =========================================================================

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        messages: List[Dict[str, Any]],
        all_tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> None:
        """Execute every tool call concurrently and append results in order.

        OpenAI / Mammouth / Groq routinely emit several ``tool_calls`` in
        the same assistant turn (e.g. ``list_categories`` + ``search_catalog``
        to cross-reference). Running them sequentially multiplied total
        latency by N. We now fan them out under a semaphore (default 5)
        and rejoin results in the original order so the ``tool`` messages
        line up with the ``tool_call_id``s OpenAI expects.
        """
        if not tool_calls:
            return

        semaphore = asyncio.Semaphore(self._tool_call_concurrency)
        executed = await asyncio.gather(
            *[
                self._dispatch_one_tool_call(tc, context, semaphore)
                for tc in tool_calls
            ],
        )

        for entry in executed:
            self._record_tool_call(entry, messages, all_tool_calls)

    async def _dispatch_one_tool_call(
        self,
        tool_call: Dict[str, Any],
        context: Dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> Dict[str, Any]:
        """Validate, hook-instrument, and run a single tool call."""
        skill_name, tc_id, params = self._parse_tool_call(tool_call)

        if context:
            params.setdefault("__context__", context)
        visible_params = _strip_context(params)

        logger.info("[AGENT] Calling skill: %s(%s)", skill_name, visible_params)
        await self._hooks.on_tool_start(skill_name, visible_params, tc_id)

        started_at = time.monotonic()
        async with semaphore:
            result = await self._registry.execute_skill(skill_name, params)
        latency_ms = (time.monotonic() - started_at) * 1000.0

        await self._hooks.on_tool_end(
            skill_name, visible_params, tc_id, result, latency_ms,
        )
        return {
            "tool_call_id": tc_id,
            "skill": skill_name,
            "params": visible_params,
            "result": result.model_dump(),
        }

    @staticmethod
    def _parse_tool_call(
        tool_call: Dict[str, Any],
    ) -> tuple[str, str, Dict[str, Any]]:
        """Extract ``(skill_name, tool_call_id, parsed_arguments)``."""
        function = tool_call.get("function", {}) or {}
        skill_name = function.get("name", "")
        tc_id = tool_call.get("id", "")
        try:
            params = json.loads(function.get("arguments", "{}") or "{}")
        except json.JSONDecodeError:
            params = {}
        return skill_name, tc_id, params

    @staticmethod
    def _record_tool_call(
        entry: Dict[str, Any],
        messages: List[Dict[str, Any]],
        all_tool_calls: List[Dict[str, Any]],
    ) -> None:
        """Append a completed tool call to both the audit log and the
        assistant↔tool message thread sent back to the LLM."""
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

    # =========================================================================
    # Internal: message building
    # =========================================================================

    def _build_messages(
        self,
        user_message: str,
        history: Optional[List[Dict[str, str]]],
    ) -> List[Dict[str, Any]]:
        """Compose the [system, ...history, user] message array for the LLM."""
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
    def _last_assistant_text(messages: List[Dict[str, Any]]) -> str:
        """Find the most recent non-empty assistant message in the thread."""
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return ""


# =============================================================================
# Internal helpers
# =============================================================================


class _RunState:
    """Mutable per-run state shared between iteration helpers.

    Kept as a small bag rather than scattered locals so the iteration
    helpers can be plain methods (no closure capture, no positional-arg
    explosion).
    """

    def __init__(self) -> None:
        self.all_tool_calls: List[Dict[str, Any]] = []
        self.last_data: Optional[Dict[str, Any]] = None
        self.result: Dict[str, Any] = {
            "reply": "", "tool_calls": [], "data": None,
        }

    def refresh_last_data(self) -> None:
        """Cache the ``data`` payload from the most recent successful tool."""
        if not self.all_tool_calls:
            return
        last = self.all_tool_calls[-1].get("result", {})
        if isinstance(last, dict) and last.get("data") is not None:
            self.last_data = last["data"]

    def set_result(self, reply: str) -> None:
        """Snapshot ``{reply, tool_calls, data}`` for return to the caller."""
        self.result = {
            "reply": reply,
            "tool_calls": self.all_tool_calls,
            "data": self.last_data,
        }


def _strip_context(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``params`` without the engine-injected ``__context__`` key."""
    return {k: v for k, v in params.items() if k != "__context__"}
