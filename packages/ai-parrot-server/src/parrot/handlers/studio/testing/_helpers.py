"""Registry-class resolution and tool instantiation helpers of the Studio testing surface."""

from __future__ import annotations

import inspect
from typing import Any

from parrot.tools.abstract import AbstractTool
from parrot.tools.discovery import resolve_class

from ._models import _KNOWN_APP_DEPS, _ServerManagedDepsError


def _resolve_registry_class(slug: str) -> type | None:
    """Resolve ``slug`` to a class via ``discover_all()`` + ``resolve_class()``.

    Matches case-insensitively, mirroring
    ``ToolManager._load_tool_from_registry``. Deliberately bypasses the
    deprecated ``ToolkitRegistry`` string lookup (see TASK-2517 Codebase
    Contract "Does NOT Exist").

    Args:
        slug: Candidate tool/toolkit slug.

    Returns:
        The resolved class, or ``None`` if the slug is unknown or
        resolution fails.
    """
    # read from the package at call time: tests patch ``studio.testing.discover_all``
    from parrot.handlers.studio import testing as _testing_pkg

    registry = _testing_pkg.discover_all()
    entry = registry.get(slug)
    if entry is None:
        lowered = {key.lower(): value for key, value in registry.items()}
        entry = lowered.get(slug.lower())
    if entry is None:
        return None
    if isinstance(entry, str):
        try:
            return resolve_class(entry)
        except (ImportError, AttributeError):
            return None
    return entry


def _instantiate_tool(cls: type, app: Any) -> AbstractTool:
    """Instantiate ``cls`` (an ``AbstractTool`` subclass) for deterministic execution.

    Zero-arg tools instantiate directly. Tools whose constructor requires a
    parameter listed in :data:`_KNOWN_APP_DEPS` are wired from the aiohttp
    app context (e.g. ``app['artifact_store']``). Any other required
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
        app_key = _KNOWN_APP_DEPS.get(pname)
        resolved = app.get(app_key) if app_key else None
        if resolved is not None:
            kwargs[pname] = resolved
        else:
            missing.append(pname)
    if missing:
        raise _ServerManagedDepsError(missing)
    return cls(**kwargs)
