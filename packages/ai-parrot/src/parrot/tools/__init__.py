"""
Tools infrastructure for building Agents.

Resolution chain for tool imports:
1. Core tools (always available — defined directly in this module)
2. parrot_tools (ai-parrot-tools installed package)
3. plugins.tools (user/deploy-time plugin directory)
4. TOOL_REGISTRY (declarative registry from ai-parrot-tools)
5. Legacy dynamic_import_helper (backward-compat submodule resolution)

Submodule redirector:
  ``from parrot.tools.prophetforecast import X`` is transparently redirected
  to ``from parrot_tools.prophetforecast import X`` when no local submodule
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
# MetaPath finder: redirect parrot.tools.<name> → parrot_tools.<name>
# ---------------------------------------------------------------------------

class _AliasLoader(importlib.abc.Loader):
    """Loader that returns an already-imported module from sys.modules."""

    def create_module(self, spec):
        return sys.modules.get(spec.name)

    def exec_module(self, module):
        pass  # Module is already fully loaded


# Build the set of core submodule names (files and dirs that exist locally)
# so the redirector never hijacks them.
_CORE_TOOLS_DIR = _Path(__file__).parent
_CORE_SUBMODULES: frozenset = frozenset(
    {p.stem for p in _CORE_TOOLS_DIR.glob("*.py") if p.stem != "__init__"}
    | {p.name for p in _CORE_TOOLS_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
)


class _ParrotToolsRedirector(importlib.abc.MetaPathFinder):
    """Redirect ``parrot.tools.<submodule>`` imports to ``parrot_tools.<submodule>``.

    Only activates when:
    - The requested module starts with ``parrot.tools.``
    - The top-level submodule name does NOT exist as a core file/package
    - ``parrot_tools.<submodule>`` is importable
    """

    _PREFIX = "parrot.tools."
    _RESOLVING: set = set()  # guard against recursion
    _loader = _AliasLoader()

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith(self._PREFIX):
            return None
        if fullname in sys.modules or fullname in self._RESOLVING:
            return None

        # Extract the first component after parrot.tools.
        # e.g. "parrot.tools.calculator.tool" → "calculator"
        rest = fullname[len(self._PREFIX):]
        top_submodule = rest.split(".")[0]

        # Never redirect core submodules — let the normal finder handle them
        if top_submodule.startswith("_") or top_submodule in _CORE_SUBMODULES:
            return None

        # Try parrot_tools first, then plugins.tools
        candidates = [f"parrot_tools.{rest}", f"plugins.tools.{rest}"]

        self._RESOLVING.add(fullname)
        try:
            for target_name in candidates:
                try:
                    mod = sys.modules.get(target_name)
                    if mod is None:
                        mod = importlib.import_module(target_name)
                    # Always read the canonical version from sys.modules
                    mod = sys.modules.get(target_name, mod)
                    sys.modules[fullname] = mod

                    # Synchronise ALL parrot_tools.* modules that were
                    # loaded as side-effects to their parrot.tools.*
                    # aliases.  This prevents Pydantic model classes
                    # from being duplicated across import paths.
                    _pt = "parrot_tools."
                    for _k, _v in list(sys.modules.items()):
                        if _k.startswith(_pt):
                            _alias = self._PREFIX + _k[len(_pt):]
                            if sys.modules.get(_alias) is not _v:
                                sys.modules[_alias] = _v

                    return importlib.util.spec_from_loader(
                        fullname,
                        loader=self._loader,
                        origin=getattr(mod, "__file__", None),
                    )
                except ImportError as exc:
                    # Distinguish "module doesn't exist" from
                    # "module exists but a dependency is missing".
                    # If the missing module IS the target itself, keep trying
                    # candidates.  If it's something else, the tool exists
                    # but has an unmet dependency — re-raise with context.
                    missing = getattr(exc, "name", None) or ""
                    if (
                        missing
                        and missing != target_name
                        and not missing.startswith(fullname)
                        and not target_name.startswith(missing + ".")
                    ):
                        raise ImportError(
                            f"Tool '{fullname}' found at '{target_name}' but failed to load: "
                            f"missing dependency '{missing}'. "
                            f"Install it with: uv pip install {missing}"
                        ) from exc
                    continue
            return None
        finally:
            self._RESOLVING.discard(fullname)


# Install the redirector at the FRONT of sys.meta_path so it runs
# before the filesystem finders (which would return "not found" for
# submodules that only exist in parrot_tools).
if not any(isinstance(f, _ParrotToolsRedirector) for f in sys.meta_path):
    sys.meta_path.insert(0, _ParrotToolsRedirector())

# ---------------------------------------------------------------------------
# Core base classes (always available)
# ---------------------------------------------------------------------------
from .abstract import AbstractTool, ToolResult
from .toolkit import AbstractToolkit, ToolkitTool
from .decorators import tool_schema, tool
from .registry import ToolkitRegistry, get_supported_toolkits

# ---------------------------------------------------------------------------
# Core tools that stay in ai-parrot (lightweight deps only)
# ---------------------------------------------------------------------------
from .mcp_mixin import MCPToolManagerMixin
from .json_tool import ToJsonTool
from .agent import AgentTool

# ---------------------------------------------------------------------------
# Plugin importer setup (existing plugin system)
# ---------------------------------------------------------------------------
setup_plugin_importer('parrot.tools', 'tools')

# ---------------------------------------------------------------------------
# Resolution sources for external tools (ai-parrot-tools, plugins)
# ---------------------------------------------------------------------------
_TOOL_SOURCES = [
    "parrot_tools",       # ai-parrot-tools installed package
    "plugins.tools",      # user/deploy-time plugin directory
]


def _resolve_from_sources(name: str) -> Optional[object]:
    """Try to import `name` as a submodule from each source in order."""
    for source in _TOOL_SOURCES:
        try:
            return importlib.import_module(f"{source}.{name}")
        except ImportError:
            continue
    return None


def _resolve_from_registry(name: str) -> Optional[object]:
    """Fallback: resolve from TOOL_REGISTRY in parrot_tools.

    Supports both slug-based lookup (e.g. ``"cloud_posture"``) and
    class-name lookup (e.g. ``"CloudPostureToolkit"``).
    """
    try:
        from parrot_tools import TOOL_REGISTRY
    except ImportError:
        return None

    dotted_path = TOOL_REGISTRY.get(name)

    # If not found by slug, search by class name (the last component
    # of the dotted path).  This allows ``from parrot.tools import
    # CloudPostureToolkit`` to resolve even though the registry key
    # is ``"cloud_posture"``.
    if not dotted_path:
        for _slug, _path in TOOL_REGISTRY.items():
            if _path.rsplit(".", 1)[-1] == name:
                dotted_path = _path
                break
    if not dotted_path:
        return None

    module_path, class_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


__all__ = (
    # Base classes
    "AbstractTool",
    "ToolResult",
    "AbstractToolkit",
    "ToolkitTool",
    "tool_schema",
    "tool",
    "ToolkitRegistry",
    "get_supported_toolkits",
    # Core tools
    "VectorStoreSearchTool",
    "MultiStoreSearchTool",
    "PythonREPLTool",
    "PythonPandasTool",
    "DatasetManager",
    "OpenAPIToolkit",
    "FileManagerTool",
    "FileManagerFactory",
    "MCPToolManagerMixin",
    "ToJsonTool",
    "AgentTool",
)


_LAZY_CORE_TOOLS = {
    "VectorStoreSearchTool": ".vectorstoresearch",
    "MultiStoreSearchTool": ".multistoresearch",
    "PythonREPLTool": ".pythonrepl",
    "PythonPandasTool": ".pythonpandas",
    "OpenAPIToolkit": ".openapitoolkit",
    "FileManagerTool": ".filemanager",
    "FileManagerFactory": ".filemanager",
    "DatasetManager": ".dataset_manager",
}


def __getattr__(name: str):
    """Resolve tool imports from external sources.

    Only fires for names NOT already defined above (core tools, base classes).
    Resolution order:
    0. Lazy core tools (require optional deps like sqlalchemy)
    1. parrot_tools package (ai-parrot-tools)
    2. plugins.tools directory
    3. TOOL_REGISTRY declarative lookup
    4. Legacy dynamic_import_helper (submodule convention)
    """
    # Skip dunder/private names
    if name.startswith("_"):
        raise AttributeError(name)

    # --- Lazy core tools (optional heavy deps) ---
    if name in _LAZY_CORE_TOOLS:
        mod = importlib.import_module(_LAZY_CORE_TOOLS[name], __name__)
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj

    # --- External resolution (ai-parrot-tools package) ---
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
        f"Tool '{name}' not found. "
        f"Install with: pip install ai-parrot-tools  or  "
        f"pip install ai-parrot-tools[{name}]"
    )
