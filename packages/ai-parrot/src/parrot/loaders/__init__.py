"""
Document Loaders — load data from different sources for RAG.

Resolution chain for loader imports:
1. Core classes (always available — defined directly in this module)
2. parrot_loaders (ai-parrot-loaders installed package)
3. plugins.loaders (user/deploy-time plugin directory)
4. LOADER_REGISTRY (declarative registry from ai-parrot-loaders)
5. Legacy dynamic_import_helper (backward-compat submodule resolution)
"""
import importlib
import sys
from typing import Optional

from parrot.plugins import setup_plugin_importer, dynamic_import_helper

# ---------------------------------------------------------------------------
# Core base classes (always available)
# ---------------------------------------------------------------------------
from .abstract import AbstractLoader
from ..stores.models import Document

# ---------------------------------------------------------------------------
# Plugin importer setup (existing plugin system)
# ---------------------------------------------------------------------------
setup_plugin_importer('parrot.loaders', 'loaders')

# ---------------------------------------------------------------------------
# Resolution sources for external loaders (ai-parrot-loaders, plugins)
# ---------------------------------------------------------------------------
_LOADER_SOURCES = [
    "parrot_loaders",       # ai-parrot-loaders installed package
    "plugins.loaders",      # user/deploy-time plugin directory
]


def _resolve_from_sources(name: str) -> Optional[object]:
    """Try to import `name` as a submodule from each source in order."""
    for source in _LOADER_SOURCES:
        try:
            return importlib.import_module(f"{source}.{name}")
        except ImportError:
            continue
    return None


def _resolve_from_registry(name: str) -> Optional[object]:
    """Fallback: resolve from LOADER_REGISTRY in parrot_loaders."""
    try:
        from parrot_loaders import LOADER_REGISTRY
    except ImportError:
        return None

    dotted_path = LOADER_REGISTRY.get(name)
    if not dotted_path:
        return None

    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


__all__ = (
    # Base classes
    "AbstractLoader",
    "Document",
)


def __getattr__(name: str):
    """Resolve loader imports from external sources.

    Only fires for names NOT already defined above (core classes).
    Resolution order:
    1. parrot_loaders package (ai-parrot-loaders)
    2. plugins.loaders directory
    3. LOADER_REGISTRY declarative lookup
    4. Legacy dynamic_import_helper (submodule convention)
    """
    # Skip dunder/private names
    if name.startswith("_"):
        raise AttributeError(name)

    # --- External resolution (ai-parrot-loaders package) ---
    result = _resolve_from_sources(name)
    if result is not None:
        # Cache in module dict to avoid repeated __getattr__ calls
        setattr(sys.modules[__name__], name, result)
        return result

    # --- Registry fallback (class-level resolution) ---
    result = _resolve_from_registry(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result

    # --- Legacy: dynamic_import_helper (submodule convention) ---
    try:
        return dynamic_import_helper(__name__, name)
    except AttributeError:
        pass

    raise ImportError(
        f"Loader '{name}' not found. "
        f"Install with: pip install ai-parrot-loaders  or  "
        f"pip install ai-parrot-loaders[{name}]"
    )
