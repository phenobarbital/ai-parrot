"""GraphIndexLoader backend precedence (FEAT-540 M6/M7)."""

from unittest.mock import MagicMock

import pytest

import parrot.loaders.graphindex as loader_mod
from parrot.loaders.graphindex import GraphIndexLoader


@pytest.fixture(autouse=True)
def patch_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid loading embedding providers while testing constructor selection."""
    monkeypatch.setattr(loader_mod, "GraphIndexEmbedder", MagicMock())


def test_explicit_backend_wins() -> None:
    """An explicit backend is selected without incompatible legacy input."""
    assert GraphIndexLoader(backend="postgres")._backend == "postgres"


def test_sqlite_dir_selects_sqlite(tmp_path) -> None:
    """The legacy SQLite directory selects the SQLite registry backend."""
    assert GraphIndexLoader(sqlite_dir=tmp_path)._backend == "sqlite"


def test_arango_params_select_arangodb() -> None:
    """Legacy Arango parameters select the ArangoDB registry backend."""
    assert GraphIndexLoader(arango={"database": "graph"})._backend == "arangodb"


def test_persistence_disabled_selects_null() -> None:
    """An explicit persistence disable selects the null backend."""
    loader = GraphIndexLoader(persist_enabled=False)
    assert loader._backend == "null"
    assert loader.persist_enabled is False


def test_sqlite_dir_conflicts_with_explicit_postgres(tmp_path) -> None:
    """Legacy SQLite options cannot silently override an explicit backend."""
    with pytest.raises(ValueError, match="sqlite_dir"):
        GraphIndexLoader(sqlite_dir=tmp_path, backend="postgres")


def test_sqlite_dir_conflicts_with_arango_params(tmp_path) -> None:
    """The two incompatible legacy persistence configurations are rejected."""
    with pytest.raises(ValueError, match="sqlite_dir"):
        GraphIndexLoader(sqlite_dir=tmp_path, arango={"database": "graph"})
