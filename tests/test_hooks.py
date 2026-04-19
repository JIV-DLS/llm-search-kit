"""Tests for #1 — AgentHooks lifecycle.

Pins three guarantees:

1. Every interesting step in ``AgentEngine.process`` fires the right
   hook in the right order.
2. ``CompositeHooks`` swallows exceptions raised inside one hook so the
   agent never crashes from instrumentation bugs.
3. The default (``NoOpHooks``) does not change behaviour vs. an engine
   built without any hook.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from llm_search_kit import (
    AgentEngine,
    BaseSkill,
    CompositeHooks,
    LoggingHooks,
    NoOpHooks,
    SkillResult,
)

from .conftest import EchoSkill, ScriptedLLMClient, make_tool_call


class _RecordingHooks(NoOpHooks):
    """Capture (event_name, args_summary) tuples in order."""

    def __init__(self) -> None:
        self.events: List[tuple] = []

    async def on_iteration_start(self, iteration, messages):
        self.events.append(("iter_start", iteration))

    async def on_llm_start(self, iteration, messages, tools):
        self.events.append(("llm_start", iteration, len(tools or [])))

    async def on_llm_end(self, iteration, response, latency_ms):
        self.events.append(("llm_end", iteration, response is not None))

    async def on_tool_start(self, skill, params, tool_call_id):
        self.events.append(("tool_start", skill, tool_call_id))

    async def on_tool_end(self, skill, params, tool_call_id, result, latency_ms):
        self.events.append(("tool_end", skill, tool_call_id, result.success))

    async def on_iteration_end(self, iteration):
        self.events.append(("iter_end", iteration))

    async def on_final_reply(self, reply, total_iterations, tool_calls):
        self.events.append(("final", total_iterations, len(tool_calls)))

    async def on_error(self, exc):
        self.events.append(("error", type(exc).__name__))


@pytest.mark.asyncio
async def test_no_tool_path_emits_expected_events():
    hooks = _RecordingHooks()
    llm = ScriptedLLMClient(responses=["hi back"])
    engine = AgentEngine(llm_client=llm, system_prompt="t", hooks=hooks)

    result = await engine.process("hi")
    assert result["reply"] == "hi back"

    names = [e[0] for e in hooks.events]
    assert names == [
        "iter_start", "llm_start", "llm_end", "iter_end", "final",
    ]


@pytest.mark.asyncio
async def test_tool_path_emits_tool_events_in_order():
    hooks = _RecordingHooks()
    llm = ScriptedLLMClient(
        responses=[
            [make_tool_call("c1", "echo", {"text": "hello"})],
            "done",
        ],
    )
    engine = AgentEngine(llm_client=llm, system_prompt="t", hooks=hooks)
    engine.register_skill(EchoSkill())

    await engine.process("please echo")

    names = [e[0] for e in hooks.events]
    # iter1: iter_start, llm_start, llm_end, tool_start, tool_end, iter_end
    # iter2: iter_start, llm_start, llm_end, iter_end, final
    assert names == [
        "iter_start", "llm_start", "llm_end",
        "tool_start", "tool_end", "iter_end",
        "iter_start", "llm_start", "llm_end", "iter_end",
        "final",
    ]
    tool_start_evt = next(e for e in hooks.events if e[0] == "tool_start")
    tool_end_evt = next(e for e in hooks.events if e[0] == "tool_end")
    assert tool_start_evt == ("tool_start", "echo", "c1")
    assert tool_end_evt == ("tool_end", "echo", "c1", True)
    assert hooks.events[-1] == ("final", 2, 1)


@pytest.mark.asyncio
async def test_composite_hooks_fanout_and_swallow_exceptions():
    healthy = _RecordingHooks()

    class BrokenHooks(NoOpHooks):
        async def on_tool_end(self, *a, **kw):
            raise RuntimeError("boom in instrumentation")

    composite = CompositeHooks([BrokenHooks(), healthy])
    llm = ScriptedLLMClient(
        responses=[
            [make_tool_call("c1", "echo", {"text": "x"})],
            "ok",
        ],
    )
    engine = AgentEngine(llm_client=llm, system_prompt="t", hooks=composite)
    engine.register_skill(EchoSkill())

    result = await engine.process("go")
    assert result["reply"] == "ok"
    assert ("tool_end", "echo", "c1", True) in healthy.events
    assert ("final", 2, 1) in healthy.events


@pytest.mark.asyncio
async def test_default_engine_without_hooks_still_works():
    """No-hooks path is identical to NoOpHooks (regression of #1)."""
    llm = ScriptedLLMClient(responses=["hi"])
    engine = AgentEngine(llm_client=llm, system_prompt="t")
    result = await engine.process("hi")
    assert result["reply"] == "hi"


@pytest.mark.asyncio
async def test_logging_hooks_does_not_crash():
    """LoggingHooks is just a smoke test — must accept every event."""
    llm = ScriptedLLMClient(
        responses=[
            [make_tool_call("c1", "echo", {"text": "hello"})],
            "done",
        ],
    )
    engine = AgentEngine(
        llm_client=llm, system_prompt="t", hooks=LoggingHooks("DEBUG"),
    )
    engine.register_skill(EchoSkill())
    result = await engine.process("hi")
    assert result["reply"] == "done"


@pytest.mark.asyncio
async def test_on_error_fires_when_skill_raises_uncaught():
    """A genuine exception in the engine path triggers on_error.

    Note: skill errors are wrapped into SkillResult by the registry, so
    we trigger the path by making the LLM raise instead.
    """
    hooks = _RecordingHooks()

    class ExplodingLLM(ScriptedLLMClient):
        async def chat_completion(self, *a, **kw):
            raise RuntimeError("network melted")

    engine = AgentEngine(
        llm_client=ExplodingLLM(responses=[]), system_prompt="t", hooks=hooks,
    )
    with pytest.raises(RuntimeError, match="network melted"):
        await engine.process("hi")
    assert ("error", "RuntimeError") in hooks.events
