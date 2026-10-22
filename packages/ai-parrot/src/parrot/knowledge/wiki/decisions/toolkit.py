"""Lazy compatibility exports for the moved decisions plane toolkit (FEAT-540 M3)."""

from typing import Any

_TARGET = "parrot_tools.wiki.decisions"
_NAMES: frozenset[str] = frozenset(
    {
        "AbstractToolkit",
        "Any",
        "BaseWikiStore",
        "DecisionService",
        "DecisionToolkit",
        "Path",
        "WikiProjectConfig",
        "create_wiki_store",
        "find_project_root",
        "load_effective_config",
        "sqlite_policy_from_config",
    }
)

__all__ = sorted(n for n in _NAMES if not n.startswith("_"))


def __getattr__(name: str) -> Any:
    """Resolve a moved name from ``parrot_tools.wiki`` only when requested."""
    if name not in _NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(_TARGET), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the moved names."""
    return sorted(_NAMES)
