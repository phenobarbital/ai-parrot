"""
AI-Parrot pipelines proxy.

Resolution chain for pipeline imports:
1. ai-parrot-pipelines installed package (parrot_pipelines)
2. plugins.pipelines user/deploy-time plugin directory
3. PIPELINE_REGISTRY declarative lookup from ai-parrot-pipelines
4. Legacy dynamic_import_helper fallback

Submodule redirector:
  ``from parrot.pipelines.handlers import X`` is transparently redirected
  to ``from parrot_pipelines.handlers import X`` when no local submodule
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
# MetaPath finder: redirect parrot.pipelines.<name> → parrot_pipelines.<name>
# ---------------------------------------------------------------------------

class _AliasLoader(importlib.abc.Loader):
    """Loader that returns an already-imported module from sys.modules."""

    def create_module(self, spec):
        return sys.modules.get(spec.name)

    def exec_module(self, module):
        pass


_CORE_PIPELINES_DIR = _Path(__file__).parent
_CORE_SUBMODULES: frozenset = frozenset(
    {p.stem for p in _CORE_PIPELINES_DIR.glob("*.py") if p.stem != "__init__"}
    | {p.name for p in _CORE_PIPELINES_DIR.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
)


class _ParrotPipelinesRedirector(importlib.abc.MetaPathFinder):
    """Redirect ``parrot.pipelines.<submodule>`` to ``parrot_pipelines.<submodule>``."""

    _PREFIX = "parrot.pipelines."
    _RESOLVING: set = set()
    _loader = _AliasLoader()

    def find_spec(self, fullname, path, target=None):
        if not fullname.startswith(self._PREFIX):
            return None
        if fullname in sys.modules or fullname in self._RESOLVING:
            return None

        rest = fullname[len(self._PREFIX):]
        top_submodule = rest.split(".")[0]

        if top_submodule.startswith("_") or top_submodule in _CORE_SUBMODULES:
            return None

        candidates = [f"parrot_pipelines.{rest}", f"plugins.pipelines.{rest}"]

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
                            f"Pipeline '{fullname}' found at '{target_name}' but failed to load: "
                            f"missing dependency '{missing}'. "
                            f"Install it with: uv pip install {missing}"
                        ) from exc
                    continue
            return None
        finally:
            self._RESOLVING.discard(fullname)


if not any(isinstance(f, _ParrotPipelinesRedirector) for f in sys.meta_path):
    sys.meta_path.insert(0, _ParrotPipelinesRedirector())

setup_plugin_importer('parrot.pipelines', 'pipelines')

_PIPELINE_SOURCES = [
    'parrot_pipelines',
    'plugins.pipelines',
]


def _resolve_from_sources(name: str) -> Optional[object]:
    for source in _PIPELINE_SOURCES:
        try:
            return importlib.import_module(f"{source}.{name}")
        except ImportError:
            continue
    return None


def _resolve_from_registry(name: str) -> Optional[object]:
    try:
        from parrot_pipelines import PIPELINE_REGISTRY
    except ImportError:
        return None

    dotted_path = PIPELINE_REGISTRY.get(name)
    if not dotted_path:
        return None

    module_path, attr_name = dotted_path.rsplit('.', 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, attr_name)


__all__ = ()


def __getattr__(name: str):
    if name.startswith('_'):
        raise AttributeError(name)

    result = _resolve_from_sources(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result

    result = _resolve_from_registry(name)
    if result is not None:
        setattr(sys.modules[__name__], name, result)
        return result

    try:
        return dynamic_import_helper(__name__, name)
    except AttributeError:
        pass

    raise ImportError(
        f"Pipeline '{name}' not found. "
        f"Install with: pip install ai-parrot-pipelines"
    )
