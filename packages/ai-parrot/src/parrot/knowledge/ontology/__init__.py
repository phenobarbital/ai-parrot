"""Ontological Graph RAG — composable ontology-driven retrieval augmented generation."""

from typing import Any

_LAZY_ATTRS: dict[str, str] = {
    "OntologyCache": "parrot.knowledge.ontology.cache",
    "OntologyGraphStore": "parrot.knowledge.ontology.graph_store",
    "OntologyIntentResolver": "parrot.knowledge.ontology.intent",
    "OntologyRAGMixin": "parrot.knowledge.ontology.mixin",
    "TenantOntologyManager": "parrot.knowledge.ontology.tenant",
    "EnrichedContext": "parrot.knowledge.ontology.schema",
    "MergedOntology": "parrot.knowledge.ontology.schema",
    "ResolvedIntent": "parrot.knowledge.ontology.schema",
    "TenantContext": "parrot.knowledge.ontology.schema",
}

__all__ = [
    "OntologyCache",
    "OntologyGraphStore",
    "OntologyIntentResolver",
    "OntologyRAGMixin",
    "TenantOntologyManager",
    "EnrichedContext",
    "MergedOntology",
    "ResolvedIntent",
    "TenantContext",
]


def __getattr__(name: str) -> Any:
    """Resolve a public ontology export on first access and cache it.

    Args:
        name: Attribute requested on the package.

    Returns:
        The object defined in the owning submodule.

    Raises:
        AttributeError: If ``name`` is not a public ontology export.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()``."""
    return sorted(set(globals()) | set(__all__))
