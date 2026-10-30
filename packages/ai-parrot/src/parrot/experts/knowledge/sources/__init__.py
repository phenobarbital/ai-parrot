"""Knowledge source adapters, one per KnowledgeSourceKind (FEAT-778 M5)."""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "KnowledgeSource": "parrot.experts.knowledge.sources.base",
    "BundledSource": "parrot.experts.knowledge.sources.bundled",
    "WorkspaceSource": "parrot.experts.knowledge.sources.workspace",
    "ADRSource": "parrot.experts.knowledge.sources.adr",
    "WikiSource": "parrot.experts.knowledge.sources.wiki",
    "BookstoreSource": "parrot.experts.knowledge.sources.bookstore",
    "GraphIndexSource": "parrot.experts.knowledge.sources.graphindex",
    "LegacyKBSource": "parrot.experts.knowledge.sources.kb",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the owning module on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'parrot.experts.knowledge.sources' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
