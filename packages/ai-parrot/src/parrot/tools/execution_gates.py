"""Execution gates of :class:`AbstractTool` (FEAT-622 M3b/M4/M8) — kept out of ``abstract.py`` on purpose.

Everything here runs *before* a tool does any work: the tenant scope gate, the approval token check, the
server-managed argument drop/fill and the subclass/constructor refusals. ``AbstractTool.execute`` calls these
helpers; the public import paths (``parrot.tools.abstract``, ``parrot.auth.confirmation``) are unchanged.
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional

from .scope import ToolScopeUnavailable, is_tenant_bound, require_tool_scope
from .server_params import ServerParam, method_server_params, validate_custom_args_schema, validate_server_params

if TYPE_CHECKING:
    from .abstract import AbstractTool, ToolResult


def validate_tool_subclass(cls: type) -> None:
    """``AbstractTool.__init_subclass__`` body: declared server params and custom ``args_schema`` are validated."""
    if "server_managed_params" in cls.__dict__:
        validate_server_params(cls)
    if cls.server_managed_params and ("server_managed_params" in cls.__dict__ or "args_schema" in cls.__dict__):
        validate_custom_args_schema(getattr(cls, "args_schema", None), cls.server_managed_params, cls.__name__)


def refuse_remote_executor(tool: object, executor: object) -> None:
    """A tenant-bound tool (or toolkit) never runs on a remote worker: the scope lives in this process only."""
    if executor is not None and is_tenant_bound(tool):
        raise TypeError(f"{type(tool).__name__}: a tenant-bound tool cannot use a remote executor")


def server_param_owner(tool: "AbstractTool") -> type:
    """The class declaring the tool's ``server_managed_params``: the owning toolkit for a ``ToolkitTool``."""
    owner = getattr(getattr(tool, "bound_method", None), "__self__", None)
    return type(owner) if owner is not None else type(tool)


def drop_server_managed(tool: "AbstractTool", kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Drop kwargs naming a server-managed method param (the LLM never sets them), with one warning."""
    managed = method_server_params(server_param_owner(tool))
    dropped = sorted(set(kwargs) & set(managed))
    if not dropped:
        return kwargs
    tool.logger.warning("Tool %s: dropped server-managed argument(s) supplied by the caller: %s", tool.name, dropped)
    return {key: value for key, value in kwargs.items() if key not in managed}


def inject_server_managed(tool: "AbstractTool", resolved: Dict[str, Any]) -> Dict[str, Any]:
    """Fill ``tenant`` / ``caller`` / ``agent`` method params from the bound ``studio_scope`` (per call)."""
    managed = method_server_params(server_param_owner(tool))
    if not managed:
        return resolved
    tenant, scope = require_tool_scope(tool_name=tool.name)
    values = {"tenant": tenant, "caller": scope.caller, "agent": scope.agent}
    return {**resolved, **{name: values[param.source] for name, param in managed.items() if param.source in values}}


def mark_host_write(tool: "AbstractTool") -> None:
    """Host standalone write tools are strictly confirmed and approvable via ToolManager (FEAT-622 M8)."""
    from parrot.auth.confirmation import is_enforced_write_class  # pylint: disable=import-outside-toplevel

    if is_enforced_write_class(type(tool)):
        tool.routing_meta.update(
            {"requires_confirmation": True, "confirmation_enforced": True, "confirm_window_seconds": 0}
        )


def check_approval(tool: "AbstractTool", kwargs: Dict[str, Any]) -> Optional["ToolResult"]:
    """Refuse a ``confirmation_enforced`` tool unless ToolManager approved exactly this call (FEAT-622 M8).

    Only the ContextVar token set by ``ToolManager`` after a ``confirmed`` guard decision counts: it must name
    this tool instance and the hash of the kwargs received here. Never a kwarg, never an instance flag.

    Returns:
        A ``forbidden`` ``ToolResult`` (``error_code="confirmation_required"``), or ``None`` when allowed.
    """
    from parrot.auth.confirmation import (  # pylint: disable=import-outside-toplevel
        consume_confirmed_call,
        is_enforced_write_class,
    )
    from .abstract import ToolResult  # pylint: disable=import-outside-toplevel

    enforced = (tool.routing_meta or {}).get("confirmation_enforced") or is_enforced_write_class(type(tool))
    if not enforced or consume_confirmed_call(tool, kwargs):
        return None
    reason = "write tool requires an explicit human confirmation for this exact call"
    return ToolResult(
        success=False,
        status="forbidden",
        result=None,
        error=f"Confirmation required: '{tool.name}' {reason}",
        metadata={
            "tool_name": tool.name,
            "error_type": "ConfirmationRequired",
            "error_code": "confirmation_required",
            "reason": reason,
        },
    )


def scope_metadata(tool: "AbstractTool", exc: BaseException) -> Dict[str, Any]:
    """Result metadata of a failed call; a :class:`ToolScopeUnavailable` carries its stable code and reason."""
    meta: Dict[str, Any] = {"tool_name": tool.name, "error_type": type(exc).__name__}
    if isinstance(exc, ToolScopeUnavailable):
        meta.update({"error_code": exc.code, "reason": exc.reason})
    return meta


def scope_refusal(tool: "AbstractTool", exc: ToolScopeUnavailable) -> "ToolResult":
    """The structured ``tool_scope_unavailable`` refusal (never an exception to the agent loop)."""
    from .abstract import ToolResult  # pylint: disable=import-outside-toplevel

    return ToolResult(success=False, status="error", result=None, error=str(exc), metadata=scope_metadata(tool, exc))


def enforce_scope_and_approval(tool: "AbstractTool", kwargs: Dict[str, Any]) -> Optional["ToolResult"]:
    """Scope gate for EVERY tenant-bound tool (with or without scope-sourced params), then the approval token.

    Runs before the permission resolver, lifecycle events, ``_ensure_open``, validation and ``_execute``.
    """
    if is_tenant_bound(tool):
        try:
            require_tool_scope(tool_name=tool.name)
        except ToolScopeUnavailable as exc:
            return scope_refusal(tool, exc)
    return check_approval(tool, kwargs)


async def pre_execute_refusal(
    tool: "AbstractTool", kwargs: Dict[str, Any], pctx: Any, resolver: Any
) -> Optional["ToolResult"]:
    """Scope gate, approval check (FEAT-622) then the Layer 2 permission safety net; ``None`` when all allow."""
    from .abstract import ToolResult  # pylint: disable=import-outside-toplevel

    refused = enforce_scope_and_approval(tool, kwargs)
    if refused is not None or pctx is None or resolver is None:
        return refused
    required = getattr(tool, "_required_permissions", set())
    if await resolver.can_execute(pctx, tool.name, required):
        return None
    tool.logger.warning("Permission denied: user=%s tool=%s required=%s", pctx.user_id, tool.name, required)
    return ToolResult(
        success=False,
        status="forbidden",
        result=None,
        error=f"Permission denied: '{tool.name}' requires {required}",
        metadata={"tool_name": tool.name, "user_id": pctx.user_id, "required_permissions": list(required)},
    )


def gate_options(raw: Any, owner_name: str) -> Any:
    """Wrap a tenant-bound toolkit's ``config_options`` (plain, class- or staticmethod) with the scope gate.

    The gate runs before the original acquires anything, so a direct call outside a valid scope never reaches it.
    """
    wrapper = type(raw) if isinstance(raw, (classmethod, staticmethod)) else None
    fn = raw.__func__ if wrapper is not None else raw
    if getattr(fn, "__scope_gated__", False):
        return raw

    @functools.wraps(fn)
    async def gated(*args: Any, **kwargs: Any) -> Any:
        require_tool_scope(tool_name=f"{owner_name}.config_options")
        result = fn(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    gated.__scope_gated__ = True  # type: ignore[attr-defined]
    return wrapper(gated) if wrapper is not None else gated


class ServerManagedToolkit:
    """Mixin of ``AbstractToolkit`` (FEAT-622 M3b/M4): declared server params and the scope-gated ``config_options``."""

    #: Params the server fills (never client JSON, never the LLM). See parrot.tools.server_params.
    server_managed_params: ClassVar[Mapping[str, ServerParam]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "server_managed_params" in cls.__dict__:
            validate_server_params(cls)
        raw = inspect.getattr_static(cls, "config_options", None)
        if raw is not None and is_tenant_bound(cls):
            cls.config_options = gate_options(raw, cls.__name__)  # type: ignore[attr-defined]


def toolkit_server_params(bound_method: Any) -> Dict[str, ServerParam]:
    """Server-managed method params of the toolkit owning ``bound_method`` (never offered to the LLM)."""
    return method_server_params(type(getattr(bound_method, "__self__", None)))


def checked_args_schema(toolkit: Any, bound_method: Any, name: str) -> Any:
    """The method's custom ``_args_schema`` (or ``None``); ``TypeError`` when it exposes a server-managed name."""
    schema = getattr(bound_method, "_args_schema", None)
    if schema:
        validate_custom_args_schema(schema, toolkit.server_managed_params, f"{type(toolkit).__name__}.{name}")
    return schema


def checked_executor(toolkit: Any, executor: Any) -> Any:
    """``executor`` unchanged; ``TypeError`` when a tenant-bound toolkit carries a remote executor."""
    refuse_remote_executor(toolkit, executor)
    return executor
