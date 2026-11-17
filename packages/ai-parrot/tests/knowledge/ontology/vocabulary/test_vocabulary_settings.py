"""Tests for ontology vocabulary settings resolution."""

from pathlib import Path

import pytest

from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings


def test_settings_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit values override environment values, which override defaults."""
    monkeypatch.setenv("ONTOLOGY_BACKEND", "snapshot")
    monkeypatch.setenv("ONTOLOGY_PG_DSN", "postgresql://environment")
    monkeypatch.setenv("ONTOLOGY_PG_SCHEMA", "tenant_schema")
    monkeypatch.setenv("ONTOLOGY_EMBEDDING_DIM", "768")
    monkeypatch.setenv("ONTOLOGY_ANN_INDEX_KIND", "ivfflat")
    monkeypatch.setenv("ONTOLOGY_SNAPSHOT_DIR", "~/ontology-snapshots")
    monkeypatch.setenv("ONTOLOGY_SNAPSHOT_URL", "https://example.test/snapshots")
    monkeypatch.setenv("ONTOLOGY_DEFAULT_LANG", "en")

    settings = resolve_ontology_settings(backend="postgres", dsn="postgresql://explicit")

    assert settings.backend == "postgres"
    assert settings.dsn == "postgresql://explicit"
    assert settings.schema_name == "tenant_schema"
    assert settings.embedding_dim == 768
    assert settings.ann_index_kind == "ivfflat"
    assert settings.snapshot_dir == Path.home() / "ontology-snapshots"
    assert settings.snapshot_url == "https://example.test/snapshots"
    assert settings.default_lang == "en"


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults apply when no explicit or environment values are provided."""
    for key in (
        "ONTOLOGY_BACKEND",
        "ONTOLOGY_PG_DSN",
        "ONTOLOGY_PG_SCHEMA",
        "ONTOLOGY_EMBEDDING_DIM",
        "ONTOLOGY_ANN_INDEX_KIND",
        "ONTOLOGY_SNAPSHOT_DIR",
        "ONTOLOGY_SNAPSHOT_URL",
        "ONTOLOGY_DEFAULT_LANG",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = resolve_ontology_settings()

    assert settings.backend == "postgres"
    assert settings.schema_name == "ontology_store"
    assert settings.embedding_dim == 1024
    assert settings.ann_index_kind == "hnsw"
    assert settings.snapshot_dir == Path("~/.parrot/ontology").expanduser()
    assert settings.default_lang == "es"


def test_bad_schema_name_rejected() -> None:
    """Unsafe SQL schema names are rejected."""
    with pytest.raises(ValueError, match="Invalid ontology schema name"):
        resolve_ontology_settings(schema="Bad-Name")


def test_bad_ann_index_kind_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unsupported ANN index kinds are rejected."""
    monkeypatch.setenv("ONTOLOGY_ANN_INDEX_KIND", "flat")

    with pytest.raises(ValueError, match="expected hnsw or ivfflat"):
        resolve_ontology_settings()
