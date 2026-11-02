"""Knowledge resolution for domain experts (FEAT-778 M4–M6)."""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "KnowledgeResolver": "parrot.experts.knowledge.resolver",
    "LAYER_ORDER": "parrot.experts.knowledge.resolver",
    "TRIM_ORDER": "parrot.experts.knowledge.resolver",
    "KNOWLEDGE_FRACTION": "parrot.experts.knowledge.budget",
    "knowledge_budget": "parrot.experts.knowledge.budget",
    "sha256_revision": "parrot.experts.knowledge.budget",
    "render_rules": "parrot.experts.knowledge.render",
    "render_knowledge": "parrot.experts.knowledge.render",
    "install_layers": "parrot.experts.knowledge.render",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Import the owning module on first access (PEP 562)."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'parrot.experts.knowledge' has no attribute {name!r}")
    return getattr(importlib.import_module(module), name)
