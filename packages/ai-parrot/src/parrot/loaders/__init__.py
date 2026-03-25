"""
Document Loaders — load data from different sources for RAG.

Resolution chain for loader imports:
1. Core classes (always available — defined directly in this module)
2. parrot_loaders (ai-parrot-loaders installed package)
3. plugins.loaders (user/deploy-time plugin directory)
4. LOADER_REGISTRY (declarative registry from ai-parrot-loaders)
5. Legacy dynamic_import_helper (backward-compat submodule resolution)

Submodule redirector:
  ``from parrot.loaders.audio import X`` is transparently redirected
  to ``from parrot_loaders.audio import X`` when no local submodule
  exists.  This is done via a sys.meta_path finder installed at import time.
"""
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path as _Path
from typing import Optional

from parrot.plugins import setup_plugin_importer, dynamic_import_helper


# ---------------------------------------------------------------------------
# MetaPath finder: redirect parrot.loaders.<name> → parrot_loaders.<name>
# ---------------------------------------------------------------------------

class _AliasLoader(importlib.abc.Loader):
    """Loader that returns an already-imported module from sys.modules."""

    def create_module(self, spec):
        return sys.modules.get(spec.name)

    def exec_module(self, module):
        pass  # Module is already fully loaded


# Build the set of core submodule names (files and dirs that exist locally)
# so the redirector never hijacks them.
_CORE_LOADERS_DIR = _Path(__file__).parent
_CORE_SUBMODULES: frozenset = frozenset(
    {p.stem for p in _CORE_LOADERS_DIR.glob("*.py") if p.stem != "__init__"}
    | {p.name for p in _CORE_LOADERS_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
)


class _ParrotLoadersRedirector(importlib.abc.MetaPathFinder):
    """Redirect ``parrot.loaders.<submodule>`` imports to ``parrot_loaders.<submodule>``.

    Only activates when:
    - The requested module starts with ``parrot.loaders.``
    - The top-level submodule name does NOT exist as a core file/package
    - ``parrot_loaders.<submodule>`` is importable
    """

    _PREFIX = "parrot.loaders."
    _RESOLVING: set = set()  # guard against recursion
    _loader = _AliasLoader()

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith(self._PREFIX):
            return None
        if fullname in sys.modules or fullname in self._RESOLVING:
            return None

        # Extract the first component after parrot.loaders.
        # e.g. "parrot.loaders.audio.AudioLoader" → "audio"
        rest = fullname[len(self._PREFIX):]
        top_submodule = rest.split(".")[0]

        # Never redirect core submodules — let the normal finder handle them
        if top_submodule.startswith("_") or top_submodule in _CORE_SUBMODULES:
            return None

        # Try parrot_loaders first, then plugins.loaders
        candidates = [f"parrot_loaders.{rest}", f"plugins.loaders.{rest}"]

        self._RESOLVING.add(fullname)
        try:
            for target_name in candidates:
                try:
                    mod = importlib.import_module(target_name)
                    sys.modules[fullname] = mod
                    return importlib.util.spec_from_loader(
                        fullname,
                        loader=self._loader,
                        origin=getattr(mod, "__file__", None),
                    )
                except ImportError as exc:
                    missing = getattr(exc, "name", None) or ""
                    if missing and missing != target_name and not missing.startswith(fullname):
                        raise ImportError(
                            f"Loader '{fullname}' found at '{target_name}' but failed to load: "
                            f"missing dependency '{missing}'. "
                            f"Install it with: uv pip install {missing}"
                        ) from exc
                    continue
            return None
        finally:
            self._RESOLVING.discard(fullname)


# Install the redirector at the FRONT of sys.meta_path so it runs
# before the filesystem finders (which would return "not found" for
# submodules that only exist in parrot_loaders).
if not any(isinstance(f, _ParrotLoadersRedirector) for f in sys.meta_path):
    sys.meta_path.insert(0, _ParrotLoadersRedirector())

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
