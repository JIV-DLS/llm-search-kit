"""Tests for #3 — ``@skill`` decorator.

Pins the contract:
  * Function signature → JSON Schema (types, required vs. optional).
  * ``Field(..., description=...)`` survives into the schema.
  * Pydantic validates / coerces inputs (``"42"`` → ``42``).
  * Validation errors come back as ``SkillResult(success=False)`` so the
    LLM can self-correct on the next iteration instead of crashing.
  * The returned object is a real ``BaseSkill`` and can be registered
    on ``AgentEngine`` exactly like a hand-written skill.
  * The optional ``ctx`` parameter receives the engine's per-request
    context dict.
"""
from __future__ import annotations

from typing import List, Optional

import pytest
from pydantic import Field

from llm_search_kit import (
    AgentEngine,
    BaseSkill,
    SkillResult,
    skill,
)

from .conftest import ScriptedLLMClient, make_tool_call


def test_decorator_returns_baseskill_instance():
    @skill(description="echo")
    async def echo(text: str = Field(..., description="text to echo")):
        return {"echoed": text}

    assert isinstance(echo, BaseSkill)
    assert echo.name == "echo"
    assert echo.description == "echo"


def test_schema_contains_types_descriptions_and_required():
    @skill(description="add two numbers")
    async def add(
        a: int = Field(..., description="first operand"),
        b: int = Field(0, description="second operand, defaults to 0"),
    ):
        return {"sum": a + b}

    schema = add.parameters_schema
    assert schema["type"] == "object"
    assert schema["properties"]["a"]["type"] == "integer"
    assert schema["properties"]["a"]["description"] == "first operand"
    assert schema["properties"]["b"]["type"] == "integer"
    assert schema["properties"]["b"]["default"] == 0
    assert schema["required"] == ["a"]


def test_schema_handles_optional_and_lists():
    @skill(description="search")
    async def search(
        q: str = Field(..., description="query"),
        tags: Optional[List[str]] = Field(None, description="tags filter"),
        limit: int = Field(10, description="max items"),
    ):
        return {"q": q, "tags": tags, "limit": limit}

    schema = search.parameters_schema
    assert schema["required"] == ["q"]
    tags_schema = schema["properties"]["tags"]
    assert "anyOf" in tags_schema or "type" in tags_schema


@pytest.mark.asyncio
async def test_execute_validates_and_coerces():
    """Pydantic v2 lax mode coerces ``"42"`` -> 42 for ints (LLMs often
    send numerics as strings) but rejects loss-of-information coercions
    like int -> str."""

    @skill(description="add")
    async def add(a: int = Field(..., description="a")):
        return {"a": a}

    ok = await add.execute(a="42")  # str -> int OK in lax mode
    assert ok.success is True
    assert ok.data == {"a": 42}

    bad = await add.execute(a="not-a-number")
    assert bad.success is False
    assert bad.error and "Invalid parameters" in bad.error


@pytest.mark.asyncio
async def test_execute_rejects_invalid_payload_with_skillresult_error():
    @skill(description="add")
    async def add(a: int = Field(..., description="a"), b: int = Field(..., description="b")):
        return {"sum": a + b}

    res = await add.execute(a="not-a-number", b=2)
    assert res.success is False
    assert res.error and "Invalid parameters" in res.error


@pytest.mark.asyncio
async def test_function_returning_skillresult_is_passed_through():
    @skill(description="explicit")
    async def explicit(x: int = Field(..., description="x")):
        return SkillResult(success=False, error="custom err", data={"x": x})

    out = await explicit.execute(x=7)
    assert out.success is False
    assert out.error == "custom err"
    assert out.data == {"x": 7}


@pytest.mark.asyncio
async def test_wrap_result_false_forces_explicit_skillresult():
    @skill(description="strict", wrap_result=False)
    async def strict(x: int = Field(..., description="x")):
        return {"x": x}  # not a SkillResult on purpose

    with pytest.raises(TypeError, match="expected SkillResult"):
        await strict.execute(x=1)


@pytest.mark.asyncio
async def test_ctx_parameter_receives_engine_context():
    captured: dict = {}

    @skill(description="captures ctx")
    async def grab(
        message: str = Field(..., description="msg"),
        ctx: Optional[dict] = None,
    ):
        captured["ctx"] = ctx
        return {"echoed": message}

    res = await grab.execute(message="hi", __context__={"user_id": "u-1"})
    assert res.success is True
    assert captured["ctx"] == {"user_id": "u-1"}


@pytest.mark.asyncio
async def test_decorated_skill_works_end_to_end_in_agent_engine():
    """Plug a @skill-decorated function into AgentEngine and verify routing."""

    @skill(description="echo back the given text")
    async def my_echo(text: str = Field(..., description="text to echo")):
        return {"echoed": text}

    llm = ScriptedLLMClient(
        responses=[
            [make_tool_call("c1", "my_echo", {"text": "ping"})],
            "all good",
        ],
    )
    engine = AgentEngine(llm_client=llm, system_prompt="t")
    engine.register_skill(my_echo)

    result = await engine.process("please echo ping")
    assert result["reply"] == "all good"
    assert result["tool_calls"][0]["skill"] == "my_echo"
    assert result["data"] == {"echoed": "ping"}


def test_missing_description_raises_helpful_error():
    with pytest.raises(ValueError, match="missing description"):
        @skill()
        async def no_doc(x: int = Field(..., description="x")):
            return {"x": x}


def test_description_falls_back_to_docstring():
    @skill()
    async def has_doc(x: int = Field(..., description="x")):
        """List active customers in the tenant.

        Long form ignored.
        """
        return {"x": x}

    assert has_doc.description == "List active customers in the tenant."


@pytest.mark.asyncio
async def test_default_required_list_is_present_when_all_optional():
    @skill(description="all optional")
    async def opt(
        a: int = Field(0, description="a"),
        b: int = Field(0, description="b"),
    ):
        return {"a+b": a + b}

    schema = opt.parameters_schema
    assert "required" in schema
    assert schema["required"] == []
    out = await opt.execute()
    assert out.data == {"a+b": 0}
