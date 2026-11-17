"""Name-keyed registry of vocabulary-store backends with lazy factories (FEAT-824)."""

from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel

from parrot._imports import lazy_import
from parrot.knowledge.ontology.vocabulary.contracts import OntologyStore


class VocabularyBackendSpec(BaseModel):
    """Registry entry for a lazily imported vocabulary backend factory."""

    name: str
    factory: str
    required_options: tuple[str, ...] = ()
    extra: str | None = None


_REGISTRY: dict[str, VocabularyBackendSpec] = {}


def register_vocabulary_backend(spec: VocabularyBackendSpec) -> None:
    """Register or replace a backend specification.

    Args:
        spec: Backend specification stored under its name.
    """
    _REGISTRY[spec.name] = spec


def vocabulary_backend_names() -> tuple[str, ...]:
    """Return registered names in registration order."""
    return tuple(_REGISTRY)


def _import_factory(spec: VocabularyBackendSpec) -> Any:
    """Import a backend factory, translating missing driver errors into install hints."""
    module_path, _, attr = spec.factory.partition(":")
    if not module_path or not attr:
        raise ValueError(f"vocabulary backend {spec.name!r} has an invalid factory path {spec.factory!r}")
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        missing = exc.name
        if missing and missing.split(".")[0] != "parrot":
            lazy_import(missing, extra=spec.extra)
        raise
    return getattr(module, attr)


def create_ontology_store(backend: str | None = None, **options: Any) -> OntologyStore:
    """Build a vocabulary store using a registered backend factory.

    Args:
        backend: Registered backend name. When omitted, resolve ``ONTOLOGY_BACKEND``.
        **options: Options passed to the selected backend factory.

    Returns:
        The constructed ontology store.

    Raises:
        ValueError: If the backend is unknown or a required option is missing.
        ImportError: If an optional backend driver is absent.
    """
    if backend is None:
        from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings

        backend = resolve_ontology_settings().backend

    try:
        spec = _REGISTRY[backend]
    except KeyError:
        raise ValueError(f"Unknown vocabulary backend {backend!r}; known: {', '.join(_REGISTRY)}") from None

    missing = [option for option in spec.required_options if options.get(option) is None]
    if missing:
        raise ValueError(f"vocabulary backend {backend!r} requires option(s): {', '.join(missing)}")
    factory = _import_factory(spec)
    return factory(**options)


register_vocabulary_backend(
    VocabularyBackendSpec(
        name="postgres",
        factory="parrot.knowledge.ontology.vocabulary.postgres_store:_create_postgres",
        extra="ontology-store",
    )
)
register_vocabulary_backend(
    VocabularyBackendSpec(
        name="snapshot",
        factory="parrot.knowledge.ontology.vocabulary.snapshot:_create_snapshot",
        extra="ontology-store",
    )
)
