"""Dream-cycle package: episodic -> wiki brain consolidation (FEAT-390).

Exposes the data models, persistence helpers, and pipeline classes for the
dream-cycle. See ``sdd/specs/dream-cycle-brain-consolidation.spec.md`` for
the full design.

Exports are resolved lazily (PEP 562), mirroring ``parrot.knowledge.wiki``'s
own lazy-export pattern: ``BrainStore`` depends on the wiki retrieval plane
(``aiosqlite``-backed ``SQLiteWikiStore``), and importing this package must
NOT pull that plane in for callers who only need the dream models — nor for
callers of ``parrot.memory`` who never touch the brain at all (post-review
fix, code-reviewer finding on FEAT-390: eager imports here were reachable
from ``import parrot.memory`` unconditionally).
"""
# Map of exported name -> defining submodule (lazy import targets).
_EXPORT_MODULES: dict[str, str] = {
    "BrainStore": "parrot.memory.dream.brain",
    "DistilledKnowledge": "parrot.memory.dream.models",
    "DreamConfig": "parrot.memory.dream.models",
    "DreamCycleReport": "parrot.memory.dream.models",
    "DreamState": "parrot.memory.dream.models",
    "load_state": "parrot.memory.dream.models",
    "save_state": "parrot.memory.dream.models",
    "DreamCycleRunner": "parrot.memory.dream.runner",
    "DreamScheduler": "parrot.memory.dream.scheduler",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str):
    """Resolve a public export lazily on first attribute access.

    Args:
        name: Attribute requested on the package.

    Returns:
        The resolved object from its defining submodule.

    Raises:
        AttributeError: If ``name`` is not a public dream export.
    """
    module_path = _EXPORT_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to :func:`dir`."""
    return sorted(set(globals()) | set(__all__))
