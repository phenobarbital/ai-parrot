"""Agent-method MCP exposure declaration and reification (FEAT-477, Module 1).

Defines the ``@mcp_tool`` decorator and ``MCPToolDeclaration`` model used to
mark a bound agent method as externally callable over MCP, plus the
reification machinery — ``AgentMethodTool`` (a real ``AbstractTool`` wrapper)
and ``build_exposure_set()`` (the configure-time scan that turns an agent's
``@mcp_tool``-marked methods into a separate, MCP-only collection).

This module is **core-only** (G9): it must be importable with no extras
installed, so it MUST NOT import anything from ``ai-parrot-server``
(``parrot.mcp.transports``, ``parrot.mcp.oauth_server``, etc.).

**OQ2 — the single most important invariant in this feature**: the exposure
set built by :func:`build_exposure_set` is a plain list, deliberately never
registered into the owning agent's ``ToolManager``. Decorating a method
changes what MCP clients can call and nothing else — it does not make the
method LLM-callable inside its own agent.
"""
import inspect
import weakref
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, field_validator

from parrot.tools.abstract import AbstractTool

MCP_TOOL_ATTR = "__mcp_tool_declaration__"

F = TypeVar("F", bound=Callable[..., Any])


class MCPToolDeclaration(BaseModel):
    """Declaration metadata attached by ``@mcp_tool``.

    All fields except the hint/limit flags are mandatory — there is no
    schema inference in v1 (spec §1 Non-Goals). Registration must fail
    loudly if any mandatory field is missing.

    Attributes:
        name: MCP tool name exposed to clients.
        description: Human-readable tool description surfaced to MCP clients.
        args_schema: Pydantic model describing the tool's call arguments.
        returns: Pydantic model describing the tool's return payload.
        scope: PBAC action/resource scope enforced when the tool is invoked.
        read_only_hint: Maps to the MCP ``readOnlyHint`` annotation.
        idempotent_hint: Maps to the MCP ``idempotentHint`` annotation.
        requires_confirmation: Maps to ``routing_meta["requires_confirmation"]``,
            which ``MCPToolAdapter`` already honors (destructiveHint precedent).
        max_result_tokens: Per-tool result-size cap; ``None`` falls back to the
            mount default.
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    returns: type[BaseModel]
    scope: str
    read_only_hint: bool = False
    idempotent_hint: bool = False
    requires_confirmation: bool = False
    max_result_tokens: int | None = None

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("args_schema", "returns")
    @classmethod
    def _validate_basemodel_subclass(cls, value: Any) -> type[BaseModel]:
        """Ensure `args_schema`/`returns` are BaseModel subclasses.

        Args:
            value: The candidate type provided for the field.

        Returns:
            The validated `Type[BaseModel]`.

        Raises:
            TypeError: If `value` is not a class, or not a `BaseModel` subclass.
        """
        if not (inspect.isclass(value) and issubclass(value, BaseModel)):
            raise TypeError(
                "args_schema/returns must be a Pydantic BaseModel subclass, "
                f"got {value!r}"
            )
        return value

    @field_validator("name", "description", "scope")
    @classmethod
    def _validate_non_empty_str(cls, value: str, info) -> str:
        """Ensure mandatory string fields are non-empty.

        Args:
            value: The candidate string value.
            info: Pydantic validation context (used for the field name).

        Returns:
            The validated string.

        Raises:
            TypeError: If `value` is empty or not a string.
        """
        if not isinstance(value, str) or not value.strip():
            raise TypeError(f"@mcp_tool: {info.field_name!r} is mandatory and cannot be empty")
        return value


def mcp_tool(
    *,
    name: str,
    description: str,
    args_schema: type[BaseModel],
    returns: type[BaseModel],
    scope: str,
    read_only_hint: bool = False,
    idempotent_hint: bool = False,
    requires_confirmation: bool = False,
    max_result_tokens: int | None = None,
) -> Callable[[F], F]:
    """Mark a bound agent method as externally callable over MCP.

    Marks only. Reification into an ``AgentMethodTool`` happens at
    ``configure()`` time (TASK-2600). The decorated method is NEVER
    registered into the owning agent's ``ToolManager`` and does not become
    LLM-callable inside that agent (spec OQ2 — the single most important
    invariant of this feature).

    Args:
        name: MCP tool name exposed to clients.
        description: Human-readable tool description.
        args_schema: Pydantic model describing the call arguments. Mandatory
            — no schema inference in v1.
        returns: Pydantic model describing the return payload. Mandatory.
        scope: PBAC action/resource scope enforced at call time.
        read_only_hint: MCP ``readOnlyHint`` annotation. Defaults to `False`.
        idempotent_hint: MCP ``idempotentHint`` annotation. Defaults to `False`.
        requires_confirmation: Whether MCP callers must pass `confirm=true`;
            maps to `routing_meta["requires_confirmation"]` /
            `destructiveHint`. Defaults to `False`.
        max_result_tokens: Per-tool result-size cap overriding the mount
            default. Defaults to `None`.

    Returns:
        A decorator that attaches an `MCPToolDeclaration` to the decorated
        async method and returns it unchanged.

    Raises:
        TypeError: If the decorated callable is not an `async def` method,
            if a mandatory field is missing/empty, or if `args_schema` /
            `returns` is not a `BaseModel` subclass.
    """

    def decorator(fn: F) -> F:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(
                f"@mcp_tool requires an async method: {fn.__qualname__}"
            )
        declaration = MCPToolDeclaration(
            name=name,
            description=description,
            args_schema=args_schema,
            returns=returns,
            scope=scope,
            read_only_hint=read_only_hint,
            idempotent_hint=idempotent_hint,
            requires_confirmation=requires_confirmation,
            max_result_tokens=max_result_tokens,
        )
        setattr(fn, MCP_TOOL_ATTR, declaration)
        return fn

    return decorator


class AgentMethodTool(AbstractTool):
    """An agent method reified as a real `AbstractTool`.

    Built by :func:`build_exposure_set` from a `@mcp_tool`-marked method.
    `name`, `description` and `args_schema` come from the method's
    `MCPToolDeclaration`; `_execute()` invokes the bound method on the
    owning agent. The agent is held by **weak reference only** so this
    tool never drags the agent into tool-serialization paths and never
    creates a reference cycle (spec §7 Risks).

    The agent is resolved **per call**, never cached as a bound method, so
    a reloaded agent (`BotManager.reload_agent()`) is picked up transparently
    by any mount holding this tool (spec OQ5).
    """

    def __init__(self, agent: Any, method_name: str, declaration: MCPToolDeclaration) -> None:
        """Initialize the reified tool.

        Args:
            agent: The owning agent instance. Held by weak reference only.
            method_name: Name of the async method on `agent` to invoke.
            declaration: The `MCPToolDeclaration` attached by `@mcp_tool`.
        """
        self._agent_ref: weakref.ReferenceType[Any] = weakref.ref(agent)
        self._method_name = method_name
        self._declaration = declaration
        super().__init__(
            name=declaration.name,
            description=declaration.description,
            routing_meta={
                "requires_confirmation": declaration.requires_confirmation,
                "read_only_hint": declaration.read_only_hint,
                "idempotent_hint": declaration.idempotent_hint,
            },
        )
        self.args_schema = declaration.args_schema

    async def _execute(self, **kwargs: Any) -> Any:
        """Invoke the bound agent method.

        Args:
            **kwargs: Call arguments, already validated against
                `args_schema` by the caller (e.g. `MCPToolAdapter`).

        Returns:
            Whatever the bound agent method returns.

        Raises:
            RuntimeError: If the owning agent has been garbage-collected.
        """
        agent = self._agent_ref()
        if agent is None:
            raise RuntimeError(
                f"agent for MCP tool {self.name!r} has been garbage-collected"
            )
        method = getattr(agent, self._method_name)
        return await method(**kwargs)


def build_exposure_set(agent: Any) -> list[AgentMethodTool]:
    """Scan `agent` for `@mcp_tool`-marked methods and build its exposure set.

    Walks the agent's class for coroutine methods carrying an
    `MCPToolDeclaration` (attached via `MCP_TOOL_ATTR`), validates there are
    no name collisions — neither among the decorated methods themselves nor
    against tools already registered in `agent.tool_manager` — and reifies
    each into an `AgentMethodTool`.

    The returned exposure set is a plain list. It is **never** registered
    into `agent.tool_manager` (OQ2) — callers (the MCP mount, TASK-2602)
    are responsible for what they do with it.

    Args:
        agent: The agent instance to scan. Must expose `tool_manager` if it
            has any `@mcp_tool`-decorated method (used for the collision
            check); agents with none are never asked for it.

    Returns:
        The agent's exposure set — one `AgentMethodTool` per decorated
        method. Empty if the agent declares none.

    Raises:
        ValueError: If two decorated methods declare the same MCP tool
            name, or a decorated name collides with an existing
            `agent.tool_manager` tool. The message names the agent class
            and the offending method(s).
    """
    agent_cls_name = type(agent).__name__
    declared_by_method: dict[str, MCPToolDeclaration] = {}
    name_to_method: dict[str, str] = {}

    for method_name, member in inspect.getmembers(
        type(agent), predicate=inspect.iscoroutinefunction
    ):
        declaration = getattr(member, MCP_TOOL_ATTR, None)
        if declaration is None:
            continue
        if declaration.name in name_to_method:
            raise ValueError(
                f"agent {agent_cls_name!r}: duplicate @mcp_tool name "
                f"{declaration.name!r} declared on methods "
                f"{name_to_method[declaration.name]!r} and {method_name!r}"
            )
        name_to_method[declaration.name] = method_name
        declared_by_method[method_name] = declaration

    if not declared_by_method:
        return []

    existing_tool_names = set(agent.tool_manager.list_tools())
    exposure_set: list[AgentMethodTool] = []
    for method_name, declaration in declared_by_method.items():
        if declaration.name in existing_tool_names:
            raise ValueError(
                f"agent {agent_cls_name!r}: @mcp_tool name {declaration.name!r} "
                f"on method {method_name!r} collides with an existing "
                "tool_manager tool"
            )
        exposure_set.append(AgentMethodTool(agent, method_name, declaration))

    return exposure_set


__all__ = [
    "MCP_TOOL_ATTR",
    "AgentMethodTool",
    "MCPToolDeclaration",
    "build_exposure_set",
    "mcp_tool",
]
