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
import sys
from types import ModuleType


# Modules whose package-level import eagerly pulls in ``torchcodec`` and can
# therefore fail on machines with a missing/incomplete FFmpeg install.
_TORCHCODEC_HOSTS = ("sentence_transformers",)


def _ensure_torchcodec_optional() -> None:
    """Make a broken/missing ``torchcodec`` non-fatal to import.

    ``sentence_transformers`` (>=5.x) eagerly runs
    ``from torchcodec.decoders import AudioDecoder, VideoDecoder`` at package
    import time, guarding it with ``except (ImportError, OSError)``. When the
    FFmpeg shared libraries are missing or incomplete (e.g. ``libavdevice.so``
    is absent), ``torchcodec`` raises a ``RuntimeError`` while loading its C
    extension — which slips past that guard and aborts the whole
    ``sentence_transformers`` import, crashing agent startup even though
    ``torchcodec`` (audio/video decoding) is irrelevant to text embeddings.

    This probes the import once. If ``torchcodec`` loads cleanly, nothing is
    changed and callers get the real module. If it is installed but fails to
    load, lightweight stub modules exposing ``AudioDecoder``/``VideoDecoder`` as
    ``None`` are registered so that the downstream guarded import resolves to
    ``None`` (the same outcome ``sentence_transformers`` intends for the
    optional-dependency-absent case). If ``torchcodec`` is not installed at all,
    nothing is stubbed — the host library's own ``ImportError`` guard handles
    that.

    Idempotent and cheap after the first call: once ``torchcodec`` (real or
    stub) is in ``sys.modules`` this returns immediately. Relies on the import
    lock held by ``importlib.import_module`` for thread safety.
    """
    if "torchcodec" in sys.modules:
        return
    try:
        importlib.import_module("torchcodec")
        return  # real torchcodec loaded fine — leave it in place
    except ModuleNotFoundError:
        return  # not installed — let the host library's own guard handle it
    except Exception:  # noqa: BLE001 — installed but failed to load (e.g. RuntimeError)
        pass
    # Register minimal stubs so ``from torchcodec.decoders import ...`` succeeds.
    # A valid ``__spec__`` is required because other libraries (e.g.
    # ``transformers``) probe availability via ``importlib.util.find_spec``,
    # which raises ``ValueError`` if a live module's ``__spec__`` is ``None``.
    from importlib.machinery import ModuleSpec

    torchcodec = ModuleType("torchcodec")
    torchcodec.__all__ = []
    torchcodec.__spec__ = ModuleSpec("torchcodec", loader=None)
    torchcodec.__spec__.submodule_search_locations = []  # mark as a package
    torchcodec.__path__ = []
    decoders = ModuleType("torchcodec.decoders")
    decoders.__spec__ = ModuleSpec("torchcodec.decoders", loader=None)
    decoders.AudioDecoder = None
    decoders.VideoDecoder = None
    torchcodec.decoders = decoders
    sys.modules["torchcodec"] = torchcodec
    sys.modules["torchcodec.decoders"] = decoders


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
    if module_path.split(".")[0] in _TORCHCODEC_HOSTS:
        # Neutralize a broken/missing torchcodec so importing this host module
        # (which pulls torchcodec in eagerly) does not crash on FFmpeg issues.
        _ensure_torchcodec_optional()
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
