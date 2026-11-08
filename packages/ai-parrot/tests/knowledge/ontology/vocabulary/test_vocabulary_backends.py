"""Tests for the ontology vocabulary backend registry."""

from typing import Any

import pytest

from parrot.knowledge.ontology.vocabulary.backends import (
    VocabularyBackendSpec,
    create_ontology_store,
    register_vocabulary_backend,
    vocabulary_backend_names,
)


def _fake_factory(**options: Any) -> dict[str, Any]:
    """Return factory options for registry testing."""
    return options


def test_builtin_names() -> None:
    """Built-in backends are registered first in stable order."""
    assert vocabulary_backend_names()[:2] == ("postgres", "snapshot")


def test_registry_unknown_backend() -> None:
    """An unknown backend error names all known choices."""
    with pytest.raises(ValueError, match=r"Unknown vocabulary backend 'nope'; known: postgres, snapshot"):
        create_ontology_store("nope")


def test_registered_fake_backend() -> None:
    """A registered factory is imported lazily and receives its options."""
    register_vocabulary_backend(
        VocabularyBackendSpec(
            name="fake",
            factory=f"{__name__}:_fake_factory",
            required_options=("token",),
        )
    )

    store = create_ontology_store("fake", token="secret", retries=2)

    assert store == {"token": "secret", "retries": 2}


def test_required_options_are_checked_before_import() -> None:
    """Missing required options produce a focused error before factory import."""
    register_vocabulary_backend(
        VocabularyBackendSpec(name="required-test", factory="does.not.exist:factory", required_options=("dsn",))
    )

    with pytest.raises(ValueError, match=r"requires option\(s\): dsn"):
        create_ontology_store("required-test")
