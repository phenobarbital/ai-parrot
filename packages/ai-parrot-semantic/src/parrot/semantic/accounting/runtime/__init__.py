"""Accounting runtime targets (FEAT-713 M6): in-memory frames on DuckDB, or a database through the Executor.

Every public name resolves lazily, so importing this package loads neither DuckDB nor the governed stack.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "DuckDBRuntime": ".duckdb",
    "FrameProvider": ".duckdb",
    "DatabaseRuntime": ".database",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Import the defining module on first use.

    Args:
        name: Public name requested on the package.

    Returns:
        The resolved public object.

    Raises:
        AttributeError: Unknown name, or its module is not importable.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = getattr(importlib.import_module(module, __name__), name)
    except ModuleNotFoundError as exc:
        raise AttributeError(f"{name!r} lives in {module!r}, which is not available: {exc}") from exc
    globals()[name] = value
    return value
