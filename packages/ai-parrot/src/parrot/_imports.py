"""Lazy Import Utility for AI-Parrot.

This module provides a canonical pattern for lazily importing optional
dependencies across the codebase. It replaces the ad-hoc try/except patterns
previously scattered across 40+ files.

Usage::

    from parrot._imports import lazy_import, require_extra

    # Import a module lazily — raises clear error if not installed
    weasyprint = lazy_import("weasyprint", extra="pdf")

    # Verify all modules for an extra are available
    require_extra("db", "querysource", "psycopg2")

This module uses only Python stdlib — no external dependencies.
"""

import importlib
from types import ModuleType


def lazy_import(
    module_path: str,
    package_name: str | None = None,
    extra: str | None = None,
) -> ModuleType:
    """Import a module lazily, raising a clear error if not installed.

    Imports ``module_path`` using ``importlib.import_module`` and returns the
    module object on success. If the module is not installed, raises an
    ``ImportError`` with an actionable install instruction.

    This function is thread-safe because ``importlib.import_module`` is
    thread-safe (it uses the module import lock internally).

    Args:
        module_path: Dotted Python module path to import, e.g. ``"weasyprint"``
            or ``"sentence_transformers"``.
        package_name: Human-readable pip package name. If omitted, the first
            segment of ``module_path`` is used. Use this when the pip name
            differs from the module name, e.g. ``package_name="sentence-transformers"``
            for ``module_path="sentence_transformers"``.
        extra: AI-Parrot extras group name. When provided, the error message
            will suggest ``pip install ai-parrot[<extra>]``. When omitted, the
            error message will suggest ``pip install <package_name>`` directly.

    Returns:
        The imported module object.

    Raises:
        ImportError: If ``module_path`` cannot be imported, with a message that
            includes the install instruction.

    Examples:
        >>> import json
        >>> mod = lazy_import("json")
        >>> mod.dumps({"key": "value"})
        '{"key": "value"}'

        >>> lazy_import("weasyprint", extra="pdf")  # if not installed
        ImportError: 'weasyprint' is required but not installed.
                     Install it with: pip install ai-parrot[pdf]
    """
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        pkg = package_name or module_path.split(".")[0]
        if extra:
            msg = (
                f"'{pkg}' is required but not installed. "
                f"Install it with: pip install ai-parrot[{extra}]"
            )
        else:
            msg = (
                f"'{pkg}' is required but not installed. "
                f"Install it with: pip install {pkg}"
            )
        raise ImportError(msg) from exc


def require_extra(extra: str, *modules: str) -> None:
    """Verify that all required modules for an extras group are importable.

    Iterates over ``modules`` and calls ``lazy_import`` on each. If any module
    is not importable, raises an ``ImportError`` with the install instruction
    for the given ``extra``.

    Useful as a guard at the top of a class or function that requires a full
    extras group, rather than doing per-module lazy imports inside each method.

    Args:
        extra: AI-Parrot extras group name, e.g. ``"db"``, ``"pdf"``, ``"ocr"``.
            Used in the error message: ``pip install ai-parrot[<extra>]``.
        *modules: One or more dotted Python module paths to check.

    Raises:
        ImportError: If any of the listed modules cannot be imported, with a
            message directing the user to install the extras group.

    Examples:
        >>> require_extra("core", "json", "os")  # both installed, no error

        >>> require_extra("db", "json", "nonexistent_xyz")
        ImportError: 'nonexistent_xyz' is required but not installed.
                     Install it with: pip install ai-parrot[db]
    """
    for mod in modules:
        lazy_import(mod, extra=extra)
