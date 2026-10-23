"""pg_schema imports clean; settings lazy (FEAT-540 M4)."""

from __future__ import annotations

import asyncio

import pytest

from tests.knowledge._support.import_probe import run_import_probe

_MODULE = "parrot.knowledge.graphindex.pg_schema"
_KEYS = (
    "GRAPHINDEX_PG_DSN",
    "GRAPHINDEX_PG_SCHEMA",
    "GRAPHINDEX_EMBEDDING_DIM",
    "GRAPHINDEX_ANN_INDEX_KIND",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every GRAPHINDEX_* key so resolution is deterministic."""
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_import_clean() -> None:
    result = run_import_probe(_MODULE)
    assert result.error is None, result.error
    assert not result.loaded_forbidden, result.loaded_forbidden


def test_lazy_dsn_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GRAPHINDEX_PG_DSN", "postgres://x")
    from parrot.knowledge.graphindex import pg_schema

    assert pg_schema.GRAPHINDEX_PG_DSN == "postgres://x"


def test_lazy_names_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GRAPHINDEX_PG_SCHEMA", "custom_schema")
    clean_env.setenv("GRAPHINDEX_EMBEDDING_DIM", "384")
    clean_env.setenv("GRAPHINDEX_ANN_INDEX_KIND", "hnsw")
    from parrot.knowledge.graphindex import pg_schema

    assert pg_schema.GRAPHINDEX_PG_SCHEMA == "custom_schema"
    assert pg_schema.GRAPHINDEX_EMBEDDING_DIM == 384
    assert pg_schema.GRAPHINDEX_ANN_INDEX_KIND == "hnsw"


def test_unknown_attribute_raises() -> None:
    from parrot.knowledge.graphindex import pg_schema

    with pytest.raises(AttributeError):
        pg_schema.NOT_A_SETTING  # noqa: B018


def test_resolve_explicit_wins(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GRAPHINDEX_PG_DSN", "postgres://env")
    from parrot.knowledge.graphindex.pg_schema import resolve_pg_settings

    settings = resolve_pg_settings(dsn="postgres://explicit", schema="other")
    assert settings.dsn == "postgres://explicit"
    assert settings.schema_name == "other"


def test_resolve_rejects_unsafe_schema(clean_env: pytest.MonkeyPatch) -> None:
    from parrot.knowledge.graphindex.pg_schema import resolve_pg_settings

    with pytest.raises(ValueError):
        resolve_pg_settings(schema="Bad-Name")


def test_create_pg_pool_missing_dsn_fails_before_io(clean_env: pytest.MonkeyPatch) -> None:
    from parrot.knowledge.graphindex import pg_schema

    # Defeat navconfig fallback: resolution must come back without a DSN.
    clean_env.setattr(pg_schema, "resolve_pg_settings", lambda **_: pg_schema.PgSettings(dsn=None))
    with pytest.raises(ValueError, match="GRAPHINDEX_PG_DSN"):
        asyncio.run(pg_schema.create_pg_pool())
