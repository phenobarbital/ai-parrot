"""Registry-class resolution and tool instantiation helpers of the Studio testing surface."""

from __future__ import annotations

import inspect
from typing import Any

from parrot.tools.abstract import AbstractTool
from parrot.tools.resolver import get_toolkit_resolver

from ._models import _ServerManagedDepsError


def _resolve_registry_class(slug: str) -> type | None:
    """Resolve ``slug`` through the shared ToolkitResolver (FEAT-622 M2 shim)."""
    return get_toolkit_resolver().resolve(slug)


def _instantiate_tool(cls: type, app: Any) -> AbstractTool:
    """Instantiate ``cls`` (an ``AbstractTool`` subclass) for deterministic execution.

    Zero-arg tools instantiate directly. Tools whose constructor requires a
    parameter the class declares ``server_managed_params`` with ``source="app"``
    are wired from the aiohttp app context (e.g. ``app['artifact_store']``). Any other required
    (no-default) constructor parameter is reported via
    :class:`_ServerManagedDepsError`.

    Args:
        cls: The resolved tool class.
        app: The aiohttp Application (source of server-managed deps).

    Returns:
        An instantiated tool.

    Raises:
        _ServerManagedDepsError: One or more required constructor params
            could not be resolved.
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
        if param.default is not inspect.Parameter.empty:
            continue
        param_decl = declared.get(pname)
        app_key = param_decl.key if param_decl is not None and param_decl.source == "app" else None
        resolved = app.get(app_key) if app_key else None
        if resolved is not None:
            kwargs[pname] = resolved
        else:
            missing.append(pname)
    if missing:
        raise _ServerManagedDepsError(missing)
    return cls(**kwargs)
