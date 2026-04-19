"""``@skill`` decorator: write a tool as a plain async function.

Role in the architecture
------------------------
Sugar on top of :class:`BaseSkill`. Lets callers expose a tool to the
LLM by writing a normal async function — the decorator inspects its
signature with :mod:`inspect` + Pydantic and synthesises the JSON
Schema, the validation, and the ``BaseSkill`` plumbing automatically.

Inspired by ``langchain.tools.tool``, ``llama_index.core.tools.FunctionTool``,
and Pydantic-AI ``@agent.tool``.

Before / after
--------------

Before — hand-written ``BaseSkill`` subclass::

    class CategoriesSkill(BaseSkill):
        @property
        def name(self): return "list_categories"
        @property
        def description(self): return "List the catalog categories."
        @property
        def parameters_schema(self):
            return {"type": "object", "properties": {
                "parent_id": {"type": "integer", "description": "..."},
                "limit":     {"type": "integer", "description": "..."},
            }, "required": []}
        async def execute(self, **kwargs):
            parent_id = kwargs.get("parent_id")
            limit = kwargs.get("limit", 50)
            ...

After — same thing with ``@skill``::

    @skill(description="List the catalog categories.")
    async def list_categories(
        parent_id: Optional[int] = Field(None, description="Parent id."),
        limit: int = Field(50, description="Max items."),
    ) -> SkillResult:
        ...

Why Pydantic and not raw ``inspect``?
-------------------------------------
Pydantic gives us, for free:
  * coerce JSON-ish primitives sent by the LLM (``"42"`` → ``42``);
  * reject malformed payloads with a precise error;
  * generate OpenAI-grade JSON Schema (``$ref`` for nested models, etc.);
  * serialise enums / Literals correctly.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional, get_type_hints

from pydantic import BaseModel, ValidationError, create_model

from .base_skill import BaseSkill, SkillResult


# Parameters whose names carry special meaning and MUST NOT become fields
# in the auto-generated argument model (they're either Python's ``self`` /
# ``cls`` or the engine-injected context).
_RESERVED_PARAMS = {"self", "cls", "ctx", "context", "__context__"}


# =============================================================================
# Public API — the @skill decorator
# =============================================================================


def skill(
    name: Optional[str] = None,
    *,
    description: Optional[str] = None,
    wrap_result: bool = True,
) -> Callable[[Callable[..., Any]], "_DecoratedSkill"]:
    """Promote an async function to a ``BaseSkill``.

    Parameters
    ----------
    name:
        Tool name exposed to the LLM. Defaults to the function name.
    description:
        Human-readable description used by the LLM to decide when to
        call this tool. Defaults to the function's docstring (first
        line). **You should always provide one** — the LLM uses it
        verbatim to route requests.
    wrap_result:
        If ``True`` (default), a non-``SkillResult`` return value is
        wrapped: ``dict`` → ``SkillResult(success=True, data=dict)``,
        scalar → ``SkillResult(success=True, data={"result": value})``.
        Set to ``False`` to enforce returning a ``SkillResult`` yourself.

    The decorated function MAY accept an extra parameter named ``ctx``
    (or ``context``) to receive the per-request context dict that
    ``AgentEngine.process(..., context=...)`` forwards.

    Example::

        @skill(description="Look up a customer by id.")
        async def get_customer(
            customer_id: int = Field(..., description="Internal customer id."),
            include_orders: bool = Field(False, description="Embed orders."),
            ctx: dict | None = None,
        ) -> SkillResult:
            tenant = (ctx or {}).get("tenant", "default")
            ...
            return SkillResult(success=True, data={"customer": ...})
    """

    def decorator(func: Callable[..., Any]) -> "_DecoratedSkill":
        resolved_name = name or func.__name__
        resolved_desc = _resolve_description(description, func, resolved_name)
        arg_model = _build_arg_model(func, model_name=f"{resolved_name}_Args")
        return _DecoratedSkill(
            func=func,
            name=resolved_name,
            description=resolved_desc,
            arg_model=arg_model,
            wrap_result=wrap_result,
        )

    return decorator


# =============================================================================
# Adapter: function → BaseSkill
# =============================================================================


class _DecoratedSkill(BaseSkill):
    """Adapter (Adapter pattern) that turns a decorated function into a
    :class:`BaseSkill`.

    The function may be a plain coroutine ``async def fn(...)`` or a
    callable that returns an awaitable / value (we ``await`` if needed).
    """

    def __init__(
        self,
        *,
        func: Callable[..., Any],
        name: str,
        description: str,
        arg_model: type[BaseModel],
        wrap_result: bool,
    ) -> None:
        self._func = func
        self._name = name
        self._description = description
        self._arg_model = arg_model
        self._schema = _pydantic_to_openai_schema(arg_model)
        self._wrap_result = wrap_result

    # ----- BaseSkill contract ------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return self._schema

    def validate_params(self, params: Dict[str, Any]) -> Optional[str]:
        """Override the base check: use Pydantic for full validation."""
        clean = {k: v for k, v in params.items() if k != "__context__"}
        try:
            self._arg_model.model_validate(clean)
            return None
        except ValidationError as exc:
            return f"Invalid parameters: {exc.errors()}"

    async def execute(self, **kwargs: Any) -> SkillResult:
        """Validate the LLM payload, invoke the wrapped function,
        normalise the return value into a :class:`SkillResult`."""
        ctx = kwargs.pop("__context__", None)

        validation = self._validate_payload(kwargs)
        if validation is not None:
            return validation

        call_kwargs = self._build_call_kwargs(kwargs, ctx)
        raw_result = await self._invoke(call_kwargs)
        return self._normalise_return(raw_result)

    # ----- internal: execute() phases ---------------------------------------

    def _validate_payload(self, kwargs: Dict[str, Any]) -> Optional[SkillResult]:
        """Reject malformed input with a structured error the LLM can fix."""
        try:
            self._arg_model.model_validate(kwargs)
            return None
        except ValidationError as exc:
            return SkillResult(
                success=False, error=f"Invalid parameters: {exc.errors()}",
            )

    def _build_call_kwargs(
        self, kwargs: Dict[str, Any], ctx: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Coerce inputs through Pydantic and inject ``ctx`` if requested."""
        validated = self._arg_model.model_validate(kwargs)
        call_kwargs = validated.model_dump()
        sig = inspect.signature(self._func)
        if "ctx" in sig.parameters:
            call_kwargs["ctx"] = ctx
        elif "context" in sig.parameters:
            call_kwargs["context"] = ctx
        return call_kwargs

    async def _invoke(self, call_kwargs: Dict[str, Any]) -> Any:
        """Call the wrapped function, awaiting it if it returned an awaitable."""
        result = self._func(**call_kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _normalise_return(self, result: Any) -> SkillResult:
        """Wrap ``dict`` / scalar returns into a :class:`SkillResult`.

        If ``wrap_result=False`` was passed to ``@skill``, a non-SkillResult
        return triggers a :class:`TypeError` so callers see the bug early.
        """
        if isinstance(result, SkillResult):
            return result
        if not self._wrap_result:
            raise TypeError(
                f"Skill {self._name!r} returned {type(result).__name__}, "
                "expected SkillResult. Either return a SkillResult yourself "
                "or pass wrap_result=True to @skill (then any return value "
                "is wrapped into SkillResult.data)."
            )
        if isinstance(result, dict):
            return SkillResult(success=True, data=result, message="")
        return SkillResult(success=True, data={"result": result}, message="")


# =============================================================================
# Internal helpers — used by the decorator at definition time
# =============================================================================


def _resolve_description(
    explicit: Optional[str],
    func: Callable[..., Any],
    skill_name: str,
) -> str:
    """Pick the LLM-facing description: explicit kw → docstring → error."""
    if explicit:
        return explicit
    docstring = (func.__doc__ or "").strip()
    if docstring:
        return docstring.splitlines()[0]
    raise ValueError(
        f"@skill on {skill_name!r}: missing description. Provide "
        "either a docstring or description='...'."
    )


def _build_arg_model(
    func: Callable[..., Any], model_name: str,
) -> type[BaseModel]:
    """Turn a function signature into a Pydantic model for its arguments.

    Each parameter becomes a model field. ``pydantic.Field`` defaults are
    preserved verbatim, which is how we keep ``description`` / constraints
    in the generated JSON Schema.
    """
    sig = inspect.signature(func)
    hints = get_type_hints(func, include_extras=True)
    fields: Dict[str, tuple] = {}

    for pname, param in sig.parameters.items():
        if pname in _RESERVED_PARAMS:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = hints.get(pname, Any)
        default = param.default if param.default is not param.empty else ...
        fields[pname] = (annotation, default)

    return create_model(model_name, **fields)  # type: ignore[arg-type]


def _pydantic_to_openai_schema(model: type[BaseModel]) -> Dict[str, Any]:
    """Adapt the Pydantic JSON Schema to the strict shape OpenAI wants.

    OpenAI tool-calling expects::

        {"type": "object", "properties": {...}, "required": [...]}

    Pydantic's ``model_json_schema()`` returns extra keys (``title``,
    ``$defs``, etc.) that are harmless but we strip the obvious ones to
    keep the payload tight.
    """
    schema = model.model_json_schema()
    schema.pop("title", None)
    properties: Dict[str, Any] = schema.get("properties") or {}
    for prop_schema in properties.values():
        if isinstance(prop_schema, dict):
            prop_schema.pop("title", None)
    schema["properties"] = properties
    schema.setdefault("required", schema.get("required", []))
    schema.setdefault("type", "object")
    return schema
