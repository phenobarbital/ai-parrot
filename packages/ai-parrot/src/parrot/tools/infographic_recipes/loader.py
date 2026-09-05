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
from pathlib import Path
from types import ModuleType


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
    registered twice).

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

    pkg_init = file.parent / "__init__.py"
    if pkg_init.is_file():
        pkg = name or f"parrot_transformers_{_digest(file.parent)}"
        if pkg not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                pkg, pkg_init, submodule_search_locations=[str(file.parent)]
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not build an import spec for package {pkg_init!r}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[pkg] = module
            spec.loader.exec_module(module)
        return importlib.import_module(f"{pkg}.{file.stem}")

    mod_name = name or f"parrot_transformers_{_digest(file)}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not build an import spec for module {file!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module
