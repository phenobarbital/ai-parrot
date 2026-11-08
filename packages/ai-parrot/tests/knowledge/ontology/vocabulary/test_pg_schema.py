"""Tests for the vocabulary-store PostgreSQL schema (FEAT-824 TASK-5256)."""

from __future__ import annotations

import pytest

from parrot.knowledge.ontology.vocabulary import pg_schema


def test_ddl_is_idempotent_text() -> None:
    """The static schema DDL is idempotent and interpolates the vector dimension."""
    ddl = pg_schema._ddl("s", 8)
    creates = [line.strip() for line in ddl.splitlines() if line.strip().startswith("CREATE")]

    assert creates
    assert all("IF NOT EXISTS" in statement for statement in creates)
    assert "vector(8)" in ddl


def test_schema_name_validated() -> None:
    """Unsafe schema identifiers are rejected before SQL is constructed."""
    with pytest.raises(ValueError):
        pg_schema.validate_schema_name("ontology-store")


async def test_ensure_schema_twice(pg_pool, pg_schema_name: str) -> None:
    """Schema setup is idempotent and remains isolated from the ontology schema."""
    async with pg_pool.acquire() as conn:
        ontology_tables_before = {
            row["table_name"]
            for row in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = $1", "ontology"
            )
        }

    await pg_schema.ensure_schema(pg_pool, schema=pg_schema_name)
    await pg_schema.ensure_schema(pg_pool, schema=pg_schema_name)

    async with pg_pool.acquire() as conn:
        target_tables = {
            row["table_name"]
            for row in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = $1", pg_schema_name
            )
        }
        ontology_tables_after = {
            row["table_name"]
            for row in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = $1", "ontology"
            )
        }

    assert target_tables == {
        "ontology",
        "version",
        "concept_identity",
        "concept",
        "label",
        "relation",
        "statement",
        "closure",
        "publication_outbox",
    }
    assert ontology_tables_after == ontology_tables_before
