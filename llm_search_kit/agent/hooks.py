"""Observer pattern: pluggable hooks for the agent loop.

Inspired by LangChain ``BaseCallbackHandler`` and OpenAI Agents SDK
``RunHooks``. Lets callers observe (and only observe — hooks must not
mutate state) every interesting moment in ``AgentEngine.process``:

* iteration boundaries (``on_iteration_start``, ``on_iteration_end``);
* the LLM round-trip (``on_llm_start``, ``on_llm_end``);
* every tool dispatch (``on_tool_start``, ``on_tool_end``);
* the final answer (``on_final_reply``);
* unexpected errors (``on_error``).

Hooks are *additive*: register many at once with ``CompositeHooks``.
The engine calls every hook with ``await``; exceptions raised inside
a hook are caught and logged (an instrumentation bug must never break
the user-facing chat).

Why a Protocol and not an ABC?
------------------------------
We want callers to write tiny, partial implementations. With a
``Protocol`` they can subclass ``NoOpHooks`` and override only the
two methods they care about, instead of being forced to implement
all eight.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .base_skill import SkillResult

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentHooks(Protocol):
    """Lifecycle hooks fired by ``AgentEngine.process``.

    Every method is async to keep the engine fully non-blocking;
    if you have nothing to do for a given event simply ``return``.
    """

    async def on_iteration_start(
        self, iteration: int, messages: List[Dict[str, Any]],
    ) -> None: ...

    async def on_llm_start(
        self, iteration: int, messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
    ) -> None: ...

    async def on_llm_end(
        self, iteration: int, response: Optional[Dict[str, Any]],
        latency_ms: float,
    ) -> None: ...

    async def on_tool_start(
        self, skill: str, params: Dict[str, Any], tool_call_id: str,
    ) -> None: ...

    async def on_tool_end(
        self, skill: str, params: Dict[str, Any], tool_call_id: str,
        result: SkillResult, latency_ms: float,
    ) -> None: ...

    async def on_iteration_end(self, iteration: int) -> None: ...

    async def on_final_reply(
        self, reply: str, total_iterations: int,
        tool_calls: List[Dict[str, Any]],
    ) -> None: ...

    async def on_error(self, exc: BaseException) -> None: ...


class NoOpHooks:
    """Default ``AgentHooks`` implementation: every method is a no-op.

    Subclass this to override only the events you care about, e.g.::

        class MyHooks(NoOpHooks):
            async def on_tool_end(self, skill, params, tool_call_id,
                                  result, latency_ms):
                metrics.timing(f"agent.tool.{skill}", latency_ms)
    """

    async def on_iteration_start(self, iteration, messages): return None
    async def on_llm_start(self, iteration, messages, tools): return None
    async def on_llm_end(self, iteration, response, latency_ms): return None
    async def on_tool_start(self, skill, params, tool_call_id): return None
    async def on_tool_end(self, skill, params, tool_call_id, result, latency_ms): return None
    async def on_iteration_end(self, iteration): return None
    async def on_final_reply(self, reply, total_iterations, tool_calls): return None
    async def on_error(self, exc): return None


class CompositeHooks(NoOpHooks):
    """Fan-out: forward every event to a list of hooks.

    Each child hook is called sequentially (so order is deterministic
    and a slow hook can't starve a fast one). If a child raises, the
    error is logged and the next child still runs — instrumentation
    bugs MUST NOT crash the agent.

    Example::

        hooks = CompositeHooks([
            LoggingHooks(level="INFO"),
            DatadogHooks(client=dd),
            LangfuseHooks(public_key=...),
        ])
        AgentEngine(llm_client=llm, hooks=hooks)
    """

    def __init__(self, hooks: List[AgentHooks]):
        self._hooks = list(hooks)

    def add(self, hook: AgentHooks) -> None:
        self._hooks.append(hook)

    async def _fanout(self, method: str, *args, **kwargs) -> None:
        for hook in self._hooks:
            fn = getattr(hook, method, None)
            if fn is None:
                continue
            try:
                await fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[HOOKS] %s.%s raised; continuing.",
                    type(hook).__name__, method,
                )

    async def on_iteration_start(self, iteration, messages):
        await self._fanout("on_iteration_start", iteration, messages)

    async def on_llm_start(self, iteration, messages, tools):
        await self._fanout("on_llm_start", iteration, messages, tools)

    async def on_llm_end(self, iteration, response, latency_ms):
        await self._fanout("on_llm_end", iteration, response, latency_ms)

    async def on_tool_start(self, skill, params, tool_call_id):
        await self._fanout("on_tool_start", skill, params, tool_call_id)

    async def on_tool_end(self, skill, params, tool_call_id, result, latency_ms):
        await self._fanout(
            "on_tool_end", skill, params, tool_call_id, result, latency_ms,
        )

    async def on_iteration_end(self, iteration):
        await self._fanout("on_iteration_end", iteration)

    async def on_final_reply(self, reply, total_iterations, tool_calls):
        await self._fanout("on_final_reply", reply, total_iterations, tool_calls)

    async def on_error(self, exc):
        await self._fanout("on_error", exc)


class LoggingHooks(NoOpHooks):
    """Drop-in observability: emit a structured log line at every step.

    Useful when you don't have Datadog/Langfuse wired up but still want
    a paper trail in the server logs. Cheap, zero-dep.

        hooks = LoggingHooks()        # INFO level
        hooks = LoggingHooks("DEBUG")  # DEBUG level
    """

    def __init__(self, level: str = "INFO"):
        self._level = getattr(logging, level.upper(), logging.INFO)

    def _log(self, msg: str, *args: Any) -> None:
        logger.log(self._level, msg, *args)

    async def on_iteration_start(self, iteration, messages):
        self._log("[HOOKS] iter=%d start (msgs=%d)", iteration, len(messages))

    async def on_llm_end(self, iteration, response, latency_ms):
        ok = response is not None
        usage = (response or {}).get("usage") or {}
        self._log(
            "[HOOKS] iter=%d llm done ok=%s latency=%.1fms tokens=%d/%d",
            iteration, ok, latency_ms,
            usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0),
        )

    async def on_tool_start(self, skill, params, tool_call_id):
        self._log("[HOOKS] tool start %s id=%s params=%s", skill, tool_call_id, params)

    async def on_tool_end(self, skill, params, tool_call_id, result, latency_ms):
        self._log(
            "[HOOKS] tool end   %s id=%s ok=%s latency=%.1fms",
            skill, tool_call_id, result.success, latency_ms,
        )

    async def on_final_reply(self, reply, total_iterations, tool_calls):
        self._log(
            "[HOOKS] final reply iters=%d tool_calls=%d reply_chars=%d",
            total_iterations, len(tool_calls), len(reply or ""),
        )

    async def on_error(self, exc):
        logger.exception("[HOOKS] error: %s", exc)


class _Stopwatch:
    """Tiny helper: ``with _Stopwatch() as sw: ...; sw.elapsed_ms``."""

    def __enter__(self) -> "_Stopwatch":
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed_ms = (time.monotonic() - self._t0) * 1000.0
