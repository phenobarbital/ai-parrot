"""Agent-method MCP exposure declaration (FEAT-477, Module 1).

Defines the ``@mcp_tool`` decorator and the ``MCPToolDeclaration`` model
used to mark a bound agent method as externally callable over MCP.

This module is **core-only** (G9): it must be importable with no extras
installed, so it MUST NOT import anything from ``ai-parrot-server``
(``parrot.mcp.transports``, ``parrot.mcp.oauth_server``, etc.).

The decorator only *marks* the function — it attaches an
``MCPToolDeclaration`` to it via the ``MCP_TOOL_ATTR`` dunder attribute and
returns the function unchanged. Reification into a real ``AbstractTool``
(the ``AgentMethodTool`` wrapper) happens later, at agent ``configure()``
time (TASK-2600) — this module does not build tools, register anything,
or maintain any global state.
"""
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, field_validator

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


__all__ = ["MCP_TOOL_ATTR", "MCPToolDeclaration", "mcp_tool"]
