"""Tests for the AgentEngine tool-calling loop."""
from __future__ import annotations

from .conftest import EchoSkill, make_tool_call


async def test_no_tool_calls_returns_reply_directly(make_engine):
    engine = make_engine(responses=["Hello there!"])
    result = await engine.process("hi")
    assert result["reply"] == "Hello there!"
    assert result["tool_calls"] == []
    assert result["data"] is None


async def test_single_tool_call_then_final_reply(make_engine):
    skill = EchoSkill()
    engine = make_engine(
        responses=[
            [make_tool_call("c1", "echo", {"text": "ping"})],
            "I echoed it.",
        ],
        skills=[skill],
    )
    result = await engine.process("please echo ping")
    assert result["reply"] == "I echoed it."
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["skill"] == "echo"
    assert result["tool_calls"][0]["params"] == {"text": "ping"}
    assert result["data"] == {"echoed": "ping"}
    assert skill.calls == [{"text": "ping"}]


async def test_two_tool_calls_in_sequence(make_engine):
    skill = EchoSkill()
    engine = make_engine(
        responses=[
            [make_tool_call("c1", "echo", {"text": "first"})],
            [make_tool_call("c2", "echo", {"text": "second"})],
            "All done.",
        ],
        skills=[skill],
    )
    result = await engine.process("do both")
    assert result["reply"] == "All done."
    assert [tc["params"]["text"] for tc in result["tool_calls"]] == ["first", "second"]
    assert result["data"] == {"echoed": "second"}


async def test_unknown_skill_returns_error_in_tool_message(make_engine):
    engine = make_engine(
        responses=[
            [make_tool_call("c1", "does_not_exist", {})],
            "Sorry I tried.",
        ],
    )
    result = await engine.process("call ghost tool")
    assert result["reply"] == "Sorry I tried."
    assert result["tool_calls"][0]["result"]["success"] is False
    assert "Unknown skill" in (result["tool_calls"][0]["result"]["error"] or "")


async def test_max_iterations_breaks_infinite_loop(make_engine):
    skill = EchoSkill()
    engine = make_engine(
        responses=[
            [make_tool_call(f"c{i}", "echo", {"text": str(i)})]
            for i in range(20)
        ],
        skills=[skill],
        max_iterations=3,
    )
    result = await engine.process("loop forever")
    assert len(result["tool_calls"]) == 3
    assert result["reply"]


async def test_llm_returns_none_yields_technical_error(make_engine):
    engine = make_engine(responses=[None])
    result = await engine.process("hi")
    assert "technical" in result["reply"].lower()


async def test_history_is_forwarded_to_llm(make_engine):
    engine = make_engine(responses=["ok"])
    await engine.process(
        "current",
        conversation_history=[
            {"role": "user", "content": "previous user"},
            {"role": "assistant", "content": "previous assistant"},
        ],
    )
    sent = engine._test_llm.calls[0]["messages"]
    roles = [m["role"] for m in sent]
    contents = [m["content"] for m in sent]
    assert roles == ["system", "user", "assistant", "user"]
    assert contents == ["test system", "previous user", "previous assistant", "current"]


async def test_context_is_injected_into_skill_params(make_engine):
    skill = EchoSkill()
    engine = make_engine(
        responses=[
            [make_tool_call("c1", "echo", {"text": "with-ctx"})],
            "done",
        ],
        skills=[skill],
    )
    await engine.process("go", context={"user_id": "u-42", "locale": "fr"})
    assert skill.calls == [{"text": "with-ctx"}]
    # The engine strips __context__ before logging it in the tool_calls output,
    # but it is forwarded into the skill kwargs.
    # Recreate without the strip to assert injection happened:
    # (We re-run with a fresh skill that captures EVERYTHING.)


async def test_context_kwarg_reaches_skill():
    """Dedicated test that asserts __context__ actually arrives in execute()."""
    from llm_search_kit import AgentEngine, SkillResult
    from llm_search_kit.agent.base_skill import BaseSkill
    from .conftest import ScriptedLLMClient, make_tool_call

    seen: dict = {}

    class CapturingSkill(BaseSkill):
        @property
        def name(self) -> str:
            return "capture"

        @property
        def description(self) -> str:
            return "capture"

        @property
        def parameters_schema(self):
            return {"type": "object", "properties": {}, "required": []}

        async def execute(self, **kwargs):
            seen.update(kwargs)
            return SkillResult(success=True, data={}, message="")

    llm = ScriptedLLMClient([
        [make_tool_call("c1", "capture", {})],
        "done",
    ])
    engine = AgentEngine(llm_client=llm, system_prompt="t")
    engine.register_skill(CapturingSkill())
    await engine.process("x", context={"user_id": "u-7", "tenant": "acme"})
    assert seen.get("__context__") == {"user_id": "u-7", "tenant": "acme"}
