"""Tests for the Opaque-Source Resolvers (FEAT-228 / TASK-1492)."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from parrot.tools.dataset_manager.sources.opaque import resolve_opaque_source


class TestResolveOpaqueSource:
    """Verify per-type resource extraction for non-SQL DataSource subclasses."""

    def test_mongo_source(self) -> None:
        """MongoSource resolves to source:mongo:<database>.<collection>."""
        from parrot.tools.dataset_manager.sources.mongo import MongoSource

        source = MongoSource(
            collection="transactions",
            name="test",
            database="finance_db",
        )
        result = resolve_opaque_source(source)
        assert result.source_type == "mongo"
        assert result.source_id == "finance_db.transactions"
        assert result.driver is None
        assert result.tables == set()

    def test_airtable_source(self) -> None:
        """AirtableSource resolves to source:airtable:<base_id>.<table>."""
        from parrot.tools.dataset_manager.sources.airtable import AirtableSource

        source = AirtableSource(base_id="appXYZ", table="Contacts")
        result = resolve_opaque_source(source)
        assert result.source_type == "airtable"
        assert result.source_id == "appXYZ.Contacts"

    def test_smartsheet_source(self) -> None:
        """SmartsheetSource resolves to source:smartsheet:<sheet_id>."""
        from parrot.tools.dataset_manager.sources.smartsheet import SmartsheetSource

        source = SmartsheetSource(sheet_id="12345")
        result = resolve_opaque_source(source)
        assert result.source_type == "smartsheet"
        assert result.source_id == "12345"

    def test_unknown_source_returns_empty(self) -> None:
        """Unknown source type → empty PhysicalResources (fail-open)."""
        # Mock a source that is not any known type
        source = MagicMock(spec=[])
        result = resolve_opaque_source(source)
        assert result.source_type is None
        assert result.source_id is None
        assert result.driver is None
        assert result.tables == set()

    def test_unknown_source_has_empty_tables(self) -> None:
        """Opaque resolvers always return empty tables set."""
        from parrot.tools.dataset_manager.sources.mongo import MongoSource

        source = MongoSource(collection="col", name="n", database="db")
        result = resolve_opaque_source(source)
        assert result.tables == set()
