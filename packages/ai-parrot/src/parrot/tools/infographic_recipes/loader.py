"""``load_transformer_module`` — host-side loader for a recipe's transformers (FEAT-528).

A host that wants to replay a recipe needs its ``@infographic_transformer``
functions registered in-process — and nothing else from the agent that ships
them: no class, no LLM, no toolkit. Today, registration is purely an import
side effect, and the only way to trigger it is a module import; this helper
imports a transformer module by file location so a host can register those
functions without owning a package named the same as the module's real
parent (spec §3 Module 2, item 3).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType

#: Serialises first loads. ``sys.modules`` check-then-act is not atomic, and a
#: second concurrent first load of the same path would re-execute the module
#: and make ``TransformerRegistry.register`` raise on the duplicate function
#: objects (code-review finding, 2026-09-05).
_LOAD_LOCK = threading.RLock()


def _already_loaded(file: Path) -> ModuleType | None:
    """Return the module already imported from ``file``, under ANY name.

    A host (or this repo's own tests) may have imported the sibling module
    through its ordinary package path — ``agents.flex_dashboard.transformers``
    — before the agent file is discovered and calls this loader. Loading it
    again under a synthetic name would re-execute the decorators and register
    DIFFERENT function objects under the same names, which
    ``TransformerRegistry.register`` refuses (code-review finding, 2026-09-05).

    Args:
        file: The resolved path of the module to look for.

    Returns:
        The existing module object, or ``None`` when nothing in
        ``sys.modules`` was loaded from that file.
    """
    target = str(file)
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if str(Path(module_file).resolve()) == target:
                return module
        except (OSError, RuntimeError):  # pragma: no cover — exotic loaders
            continue
    return None


def _digest(path: Path) -> str:
    """Return a short, deterministic, filesystem-path-derived digest.

    Args:
        path: The resolved path to key the synthetic module/package name on.

    Returns:
        The first 12 hex characters of the path's SHA-1 digest.
    """
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]


def load_transformer_module(path: str | Path, *, name: str | None = None) -> ModuleType:
    """Import a transformer module by file path so its transformers register.

    If the module's directory contains an ``__init__.py``, the module is
    loaded AS A SUBMODULE of a synthetic package (registered in
    ``sys.modules`` under a deterministic synthetic name) so that relative
    imports inside the module (e.g. ``from .normalize import ...``) resolve.
    Otherwise the file is loaded directly under a synthetic module name.

    Loading the same resolved path twice is idempotent: the second call
    returns the already-imported module from ``sys.modules`` without
    re-executing it (so its ``@infographic_transformer`` functions are never
    registered twice). The same holds when the module was FIRST imported
    through its ordinary package path (``import pkg.transformers``): the
    existing module is returned rather than re-executed under a synthetic
    name. First loads are serialised by a process-wide lock.

    Args:
        path: Path to the transformer module file (e.g.
            ``.../flex_dashboard/transformers.py``).
        name: Optional explicit synthetic name. Defaults to a deterministic
            name derived from the resolved path.

    Returns:
        The imported module.

    Raises:
        FileNotFoundError: If ``path`` does not resolve to an existing file.
        ImportError: Re-raised unchanged if importing the module fails.
    """
    file = Path(path).resolve()
    if not file.is_file():
        raise FileNotFoundError(file)

    with _LOAD_LOCK:
        existing = _already_loaded(file)
        if existing is not None:
            return existing
        return _load_under_synthetic_name(file, name)


def _load_under_synthetic_name(file: Path, name: str | None) -> ModuleType:
    """Load ``file`` under a deterministic synthetic (package or module) name.

    Caller holds ``_LOAD_LOCK`` and has verified nothing in ``sys.modules``
    was already loaded from ``file``.
    """
    pkg_init = file.parent / "__init__.py"
    if pkg_init.is_file():
        pkg = name or f"parrot_transformers_{_digest(file.parent)}"
        if pkg not in sys.modules:
            spec = importlib.util.spec_from_file_location(pkg, pkg_init, submodule_search_locations=[str(file.parent)])
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not build an import spec for package {pkg_init!r}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[pkg] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                # Mirror CPython's own import machinery: never leave a
                # poisoned entry behind — a failed first load would
                # otherwise permanently short-circuit every retry via the
                # `pkg not in sys.modules` check above.
                sys.modules.pop(pkg, None)
                raise
        return importlib.import_module(f"{pkg}.{file.stem}")

    mod_name = name or f"parrot_transformers_{_digest(file)}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not build an import spec for module {file!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    return module
