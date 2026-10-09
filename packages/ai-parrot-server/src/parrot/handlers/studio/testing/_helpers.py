"""Registry-class resolution and tool instantiation helpers of the Studio testing surface."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from parrot.tools.abstract import AbstractTool
from parrot.tools.resolver import get_toolkit_resolver

from ._models import _ServerManagedDepsError


def _resolve_registry_class(slug: str) -> type | None:
    """Resolve ``slug`` through the shared ToolkitResolver (FEAT-622 M2 shim)."""
    return get_toolkit_resolver().resolve(slug)


def _instantiate_tool(cls: type, app: Any, hook: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> AbstractTool:
    """Instantiate ``cls`` (an ``AbstractTool`` subclass) for deterministic execution.

    Every constructor parameter the class declares in ``server_managed_params`` with ``source="app"`` is filled from
    the aiohttp app context (e.g. ``app['artifact_store']``), whether or not the constructor gives it a default. The
    host toolkit-parameter hook (PA-9), when given, then sees those params and returns the FINAL ones (it may force
    confinement switches, or raise ``ToolParamRefused``). Any other required (no-default) constructor parameter is
    reported via :class:`_ServerManagedDepsError`.

    Args:
        cls: The resolved tool class.
        app: The aiohttp Application (source of server-managed deps).
        hook: ``params -> final params`` (the host hook bound to the slug and subject), or ``None``.

    Returns:
        An instantiated tool.

    Raises:
        _ServerManagedDepsError: One or more required constructor params could not be resolved.
        ToolParamRefused: The host hook refused the parameters.
    """
    sig = inspect.signature(cls.__init__)
    declared = getattr(cls, "server_managed_params", None) or {}
    kwargs: dict[str, Any] = {}
    missing: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "self" or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        param_decl = declared.get(pname)
        app_key = param_decl.key if param_decl is not None and param_decl.source == "app" else None
        resolved = app.get(app_key) if app_key else None
        if resolved is not None:
            kwargs[pname] = resolved
        elif param.default is inspect.Parameter.empty:
            missing.append(pname)
    if missing:
        raise _ServerManagedDepsError(missing)
    if hook is not None:
        kwargs = hook(kwargs)
    return cls(**kwargs)
