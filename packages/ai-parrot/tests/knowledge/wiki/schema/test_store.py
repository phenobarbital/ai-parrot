"""Tests for the schema SQLite store."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.schema.models import ColumnRecord
from parrot.knowledge.wiki.schema.store import SchemaStore
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
def store(plane_dir):
    """Return a writable schema store."""
    plane_dir.mkdir(parents=True)
    return SchemaStore(plane_dir / "schema.db")


async def test_upsert_columns_replaces(store):
    """A table's second column slice replaces its first slice."""
    table_id = "table:o/public.users"
    await store.upsert_columns([ColumnRecord(table_id=table_id, ordinal=0, name="id", data_type="int")])
    await store.upsert_columns([ColumnRecord(table_id=table_id, ordinal=0, name="uid", data_type="uuid")])
    assert [column.name for column in await store.columns_for(table_id)] == ["uid"]


async def test_find_columns_by_fk_target_prefix(store):
    """Foreign-key prefix searches return matching columns."""
    await store.upsert_columns(
        [
            ColumnRecord(
                table_id="table:o/epson.sales",
                ordinal=0,
                name="store_id",
                data_type="int",
                fk_target="table:o/epson.stores.id",
            )
        ]
    )
    result = await store.find_columns(fk_target_prefix="table:o/epson.stores")
    assert [column.name for column in result] == ["store_id"]


async def test_replace_schema_slice_removes_dropped_table_columns(store):
    """Replacing a source removes dropped table pages and their columns."""
    source_id = "schema:o"
    kept = WikiPageRecord(concept_id="table:o/public.kept", category="table", source_id=source_id)
    dropped = WikiPageRecord(concept_id="table:o/public.dropped", category="table", source_id=source_id)
    await store.replace_schema_slice(
        "o",
        [kept, dropped],
        [
            ColumnRecord(table_id=kept.concept_id, ordinal=0, name="id", data_type="int"),
            ColumnRecord(table_id=dropped.concept_id, ordinal=0, name="id", data_type="int"),
        ],
        [],
    )
    await store.replace_schema_slice(
        "o",
        [kept],
        [ColumnRecord(table_id=kept.concept_id, ordinal=0, name="id", data_type="int")],
        [],
    )
    assert await store.get_page(dropped.concept_id) is None
    assert await store.columns_for(dropped.concept_id) == []


async def test_read_only_refuses(plane_dir):
    """Read-only schema stores reject column writes."""
    plane_dir.mkdir(parents=True)
    writable = SchemaStore(plane_dir / "schema.db")
    await writable.upsert_columns([])
    read_only = SchemaStore(plane_dir / "schema.db", read_only=True)
    with pytest.raises(PermissionError):
        await read_only.upsert_columns(
            [ColumnRecord(table_id="table:o/s.t", ordinal=0, name="x", data_type="int")]
        )
