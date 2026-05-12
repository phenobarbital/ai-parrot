"""Tests for PostgresS3SecurityReportStore.

Unit tests use mock FileManagerInterface and a mock asyncdb connection.
Integration tests are gated on TEST_PG_DSN env var and require a live Postgres.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.storage.security_reports import (
    PostgresS3SecurityReportStore,
    ReportFilter,
    ReportKind,
    ReportRef,
    SecurityReportStore,
    SeverityBreakdown,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ref(produced_at: datetime | None = None, scope: dict | None = None) -> ReportRef:
    return ReportRef(
        report_kind=ReportKind.SCAN,
        scanner="cloudsploit",
        framework="HIPAA",
        provider="aws",
        scope=scope or {"account_id": "123456789012", "region": "us-east-1"},
        severity_summary=SeverityBreakdown(critical=1, high=2),
        uri="",
        produced_at=produced_at or datetime.now(timezone.utc),
        produced_by="test",
        parser_version="1.0.0",
    )


# ---------------------------------------------------------------------------
# Unit tests (mock file manager + db)
# ---------------------------------------------------------------------------

class TestProtocolInterface:
    def test_protocol_is_runtime_checkable(self):
        """SecurityReportStore is a @runtime_checkable Protocol."""
        # PostgresS3SecurityReportStore should satisfy the protocol
        fm = MagicMock()
        with patch("parrot.storage.security_reports.store.AsyncDB"):
            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
        assert isinstance(store, SecurityReportStore)


class TestBuildKey:
    def test_key_structure(self, tmp_path):
        fm = MagicMock()
        with patch("parrot.storage.security_reports.store.AsyncDB"):
            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
        ref = _ref(produced_at=datetime(2026, 5, 12, 6, 0, tzinfo=timezone.utc))
        key = store._build_key(ref)
        assert key.startswith("security-reports/cloudsploit/HIPAA/2026/05/12/")
        assert str(ref.report_id) in key
        assert key.endswith(".json")

    def test_key_none_framework(self, tmp_path):
        fm = MagicMock()
        with patch("parrot.storage.security_reports.store.AsyncDB"):
            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
        ref = _ref()
        ref = ref.model_copy(update={"framework": None})
        key = store._build_key(ref)
        assert "/none/" in key


class TestSaveReportUnit:
    async def test_save_uploads_and_inserts(self, tmp_path):
        """save_report: S3 upload first, then Postgres INSERT."""
        fm = AsyncMock()
        fm.create_file = AsyncMock(return_value=True)

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=None)

        with patch("parrot.storage.security_reports.store.AsyncDB", create=True) as mock_db_cls:
            mock_db = MagicMock()
            mock_db.connection = AsyncMock(return_value=mock_conn)
            mock_db_cls.return_value = mock_db

            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
            ref = _ref()
            saved = await store.save_report(ref, b'{"test": true}')

        # URI must be populated
        assert saved.uri != ""
        # S3 upload was called
        fm.create_file.assert_called_once()
        # Postgres insert was called
        mock_conn.execute.assert_called_once()

    async def test_save_bytes_uses_create_file(self):
        fm = AsyncMock()
        fm.create_file = AsyncMock(return_value=True)

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=None)

        with patch("parrot.storage.security_reports.store.AsyncDB", create=True) as mock_db_cls:
            mock_db = MagicMock()
            mock_db.connection = AsyncMock(return_value=mock_conn)
            mock_db_cls.return_value = mock_db

            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
            await store.save_report(_ref(), b"content bytes")

        fm.create_file.assert_called_once()
        fm.upload_file.assert_not_called()

    async def test_save_path_uses_upload_file(self, tmp_path):
        tmp_file = tmp_path / "report.json"
        tmp_file.write_bytes(b"{}")

        fm = AsyncMock()
        fm.upload_file = AsyncMock(return_value=MagicMock())

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=None)

        with patch("parrot.storage.security_reports.store.AsyncDB", create=True) as mock_db_cls:
            mock_db = MagicMock()
            mock_db.connection = AsyncMock(return_value=mock_conn)
            mock_db_cls.return_value = mock_db

            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
            await store.save_report(_ref(), tmp_file)

        fm.upload_file.assert_called_once()
        fm.create_file.assert_not_called()


class TestQueryNoImplicitSince:
    async def test_no_since_in_filter_builds_no_since_clause(self):
        """query(ReportFilter()) must NOT add a since clause."""
        fm = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("parrot.storage.security_reports.store.AsyncDB", create=True) as mock_db_cls:
            mock_db = MagicMock()
            mock_db.connection = AsyncMock(return_value=mock_conn)
            mock_db_cls.return_value = mock_db

            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
            await store.query(ReportFilter(limit=10))

        # The SQL passed to fetch must NOT contain a WHERE clause with produced_at
        call_args = mock_conn.fetch.call_args
        sql = call_args.args[0] if call_args.args else ""
        # No implicit time filter — the WHERE clause should be empty or absent
        # (if clauses is empty, "where" is "")
        assert "produced_at >=" not in sql, (
            "query() must NOT apply an implicit since filter on produced_at"
        )


class TestBootstrapSchema:
    async def test_bootstrap_reads_schema_sql(self):
        """bootstrap_schema() executes the schema.sql DDL."""
        fm = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=None)

        with patch("parrot.storage.security_reports.store.AsyncDB", create=True) as mock_db_cls:
            mock_db = MagicMock()
            mock_db.connection = AsyncMock(return_value=mock_conn)
            mock_db_cls.return_value = mock_db

            store = PostgresS3SecurityReportStore(dsn="pg://localhost/test", file_manager=fm)
            await store.bootstrap_schema()

        # Execute was called with the schema SQL
        mock_conn.execute.assert_called_once()
        schema_sql = mock_conn.execute.call_args.args[0]
        assert "CREATE TABLE IF NOT EXISTS security_reports" in schema_sql


# ---------------------------------------------------------------------------
# Integration tests (gated on TEST_PG_DSN)
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.skipif(
    not os.environ.get("TEST_PG_DSN"),
    reason="Set TEST_PG_DSN=postgres://... to run store integration tests",
)
