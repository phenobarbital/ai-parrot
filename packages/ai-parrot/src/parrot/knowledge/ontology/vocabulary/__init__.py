"""Versioned RDF vocabularies on PostgreSQL with SQLite snapshots (FEAT-824)."""

from typing import Any

_P = "parrot.knowledge.ontology.vocabulary"
_LAZY_ATTRS: dict[str, str] = {
    **{
        name: f"{_P}.contracts"
        for name in (
            "OntologyStore",
            "OntologyPublisher",
            "ConceptRef",
            "Resolution",
            "PublishResult",
            "StoreStatus",
            "OntologyContent",
            "VersionContent",
            "PublishDiff",
            "ValidationIssue",
            "ClosureRow",
        )
    },
    **{
        name: f"{_P}.exceptions"
        for name in (
            "VocabularyError",
            "OntologyNotFound",
            "OntologyVersionNotFound",
            "OntologyValidationError",
            "PublishConflict",
        )
    },
    **{
        name: f"{_P}.backends"
        for name in (
            "create_ontology_store",
            "register_vocabulary_backend",
            "VocabularyBackendSpec",
            "vocabulary_backend_names",
        )
    },
    "OntologyStoreSettings": f"{_P}.settings",
    "resolve_ontology_settings": f"{_P}.settings",
    "PostgresOntologyStore": f"{_P}.postgres_store",
    "PostgresOntologyPublisher": f"{_P}.publisher",
    "SnapshotOntologyStore": f"{_P}.snapshot",
}
__all__ = sorted(_LAZY_ATTRS)


def __getattr__(name: str) -> Any:
    """Resolve a public export on first access and cache it.

    Args:
        name: Attribute requested on the package.

    Returns:
        The object defined in the owning submodule.

    Raises:
        AttributeError: If ``name`` is not a public vocabulary export.
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
