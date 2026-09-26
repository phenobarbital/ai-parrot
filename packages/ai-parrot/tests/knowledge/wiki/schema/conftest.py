"""Shared fixtures for FEAT-600 schema-plane tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.bots.database.models import Completeness, TableMetadata

DDL_CORPUS = Path("packages/ai-parrot/src/parrot/tools/working_memory/task_memory/migrations/001_task_memory.sql")


@pytest.fixture
def plane_dir(tmp_path: Path) -> Path:
    """Return a throwaway `.parrot/schema` directory."""
    return tmp_path / ".parrot" / "schema"


@pytest.fixture
def sales_metadata() -> TableMetadata:
    """Return epson.sales metadata with a store_id foreign key."""
    return TableMetadata(
        schema="epson",
        tablename="sales",
        table_type="BASE TABLE",
        full_name="epson.sales",
        comment="Daily sales",
        columns=[
            {"name": "id", "type": "INT64", "nullable": False},
            {"name": "store_id", "type": "INT64", "nullable": False, "comment": "T-ROC store id"},
            {"name": "amount", "type": "NUMERIC", "nullable": True},
        ],
        primary_keys=["id"],
        foreign_keys=[{"column": "store_id", "ref_schema": "epson", "ref_table": "stores", "ref_column": "id"}],
        completeness=Completeness.FULL,
        source="information_schema",
    )
