"""Regression tests for #7 — parallel tool-call execution.

Before the fix, ``AgentEngine._execute_tool_calls`` ran tool calls in a
``for`` loop, so 3 independent tools called by the same assistant turn
took ~3× longer than the slowest one. We now run them under
``asyncio.gather`` capped by a semaphore.

These tests pin both the *correctness* (results match the call order so
``tool_call_id``s line up with OpenAI's expectations) and the *parallelism*
(measured wall time of N concurrent ~50ms tools is closer to 50ms than
to N×50ms).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest

from llm_search_kit import AgentEngine, BaseSkill, SkillResult

from .conftest import ScriptedLLMClient, make_tool_call


class _SleepSkill(BaseSkill):
    """Skill whose ``execute`` sleeps for ``delay_s`` seconds.

    Records its concurrent in-flight count so we can assert the engine
    really runs several at once.
    """

    def __init__(self, name: str, delay_s: float, concurrency_log: List[int]):
        self._name = name
        self._delay = delay_s
        self._inflight = 0
        self._concurrency_log = concurrency_log

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "sleep for delay_s seconds"

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> SkillResult:
        self._inflight += 1
        self._concurrency_log.append(self._inflight)
        try:
            await asyncio.sleep(self._delay)
            return SkillResult(success=True, data={"slept": self._delay}, message="ok")
        finally:
            self._inflight -= 1


@pytest.mark.asyncio
async def test_three_independent_tools_run_concurrently():
    delay = 0.1
    concurrency_log: List[int] = []
    skill = _SleepSkill("sleep_a", delay, concurrency_log)

    llm = ScriptedLLMClient(
        responses=[
            [
                make_tool_call("c1", "sleep_a", {}),
                make_tool_call("c2", "sleep_a", {}),
                make_tool_call("c3", "sleep_a", {}),
            ],
            "all done",
        ],
    )
    engine = AgentEngine(
        llm_client=llm,
        system_prompt="t",
        tool_call_concurrency=5,
    )
    engine.register_skill(skill)

    started = time.monotonic()
    result = await engine.process("kick three sleeps")
    elapsed = time.monotonic() - started

    assert result["reply"] == "all done"
    assert len(result["tool_calls"]) == 3
    # Sequential would be >= 3*delay; concurrent must be ~delay (with margin).
    assert elapsed < delay * 2.0, (
        f"Tools were not run concurrently: elapsed={elapsed:.3f}s, expected≈{delay:.3f}s"
    )
    assert max(concurrency_log) >= 2, (
        "At least 2 in-flight executions expected; got log: " + str(concurrency_log)
    )


@pytest.mark.asyncio
async def test_results_are_appended_in_call_order():
    """tool_call_id ordering MUST match the LLM's original order.

    OpenAI strictly checks that every assistant ``tool_calls[i].id``
    is followed by a matching ``tool`` message with the same id.
    Out-of-order replies trigger a 400 ``unexpected role`` error.
    """
    concurrency_log: List[int] = []
    fast = _SleepSkill("fast", 0.005, concurrency_log)
    slow = _SleepSkill("slow", 0.05, concurrency_log)

    llm = ScriptedLLMClient(
        responses=[
            [
                make_tool_call("call-slow", "slow", {}),
                make_tool_call("call-fast", "fast", {}),
            ],
            "ok",
        ],
    )
    engine = AgentEngine(llm_client=llm, system_prompt="t")
    engine.register_skill(fast)
    engine.register_skill(slow)
    await engine.process("two")

    second_request = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_request if m.get("role") == "tool"]
    ids_in_order = [m["tool_call_id"] for m in tool_msgs]
    assert ids_in_order == ["call-slow", "call-fast"], (
        f"tool_call_id ordering broken: {ids_in_order}"
    )


@pytest.mark.asyncio
async def test_concurrency_is_capped_by_semaphore():
    delay = 0.05
    concurrency_log: List[int] = []
    skill = _SleepSkill("s", delay, concurrency_log)

    n = 6
    llm = ScriptedLLMClient(
        responses=[
            [make_tool_call(f"c{i}", "s", {}) for i in range(n)],
            "done",
        ],
    )
    engine = AgentEngine(
        llm_client=llm,
        system_prompt="t",
        tool_call_concurrency=2,
    )
    engine.register_skill(skill)

    started = time.monotonic()
    await engine.process("burst")
    elapsed = time.monotonic() - started

    # 6 tools at concurrency=2 -> at least 3 batches -> ≈ 3*delay.
    assert elapsed >= delay * 2.5, (
        f"Concurrency cap ignored: elapsed={elapsed:.3f}s for {n} tools at cap=2"
    )
    assert max(concurrency_log) <= 2, (
        f"Semaphore breached: peak in-flight={max(concurrency_log)}"
    )


@pytest.mark.asyncio
async def test_single_tool_call_still_works_unchanged():
    """Smoke test: the single-tool path must not regress."""
    skill = _SleepSkill("s", 0.001, [])
    llm = ScriptedLLMClient(
        responses=[
            [make_tool_call("only", "s", {})],
            "single done",
        ],
    )
    engine = AgentEngine(llm_client=llm, system_prompt="t")
    engine.register_skill(skill)
    result = await engine.process("one")
    assert result["reply"] == "single done"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["skill"] == "s"
