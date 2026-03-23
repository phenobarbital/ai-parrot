"""
AI-Parrot pipelines proxy.

Resolution chain for pipeline imports:
1. ai-parrot-pipelines installed package (parrot_pipelines)
2. plugins.pipelines user/deploy-time plugin directory
3. PIPELINE_REGISTRY declarative lookup from ai-parrot-pipelines
4. Legacy dynamic_import_helper fallback
"""
import importlib
import sys
from typing import Optional

from parrot.plugins import setup_plugin_importer, dynamic_import_helper

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
