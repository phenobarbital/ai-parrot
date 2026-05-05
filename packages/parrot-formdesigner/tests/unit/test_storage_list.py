"""Unit tests for PostgresFormStorage.list_forms() enriched output (TASK-1031).

Tests use in-memory stubs for the asyncpg pool and connection so no real
PostgreSQL is required. Covers the dict shape introduced by TASK-1030:
form_id, version, title, description, created_at.
"""

import json
from datetime import datetime, timezone

import pytest

from parrot.formdesigner.services.registry import FormStorage
from parrot.formdesigner.services.storage import PostgresFormStorage


# ---------------------------------------------------------------------------
# asyncpg stubs — duck-typed doubles
# ---------------------------------------------------------------------------

class _StubRow(dict):
    """asyncpg.Record duck-type — supports row['key'] indexing."""


class _StubConn:
    """Minimal asyncpg connection stub."""

    def __init__(self, rows: list[_StubRow]) -> None:
        """Initialise with a fixed list of rows to return from fetch().

        Args:
            rows: Rows returned by ``conn.fetch()``.
        """
        self._rows = rows

    async def fetch(self, sql: str) -> list[_StubRow]:
        """Return the preconfigured rows regardless of SQL.

        Args:
            sql: Ignored SQL string.

        Returns:
            List of pre-configured stub rows.
        """
        return list(self._rows)

    async def execute(self, sql: str) -> str:
        """No-op execute stub.

        Args:
            sql: Ignored SQL string.

        Returns:
            Fake asyncpg execute result string.
        """
        return "EXECUTE 0"

    async def __aenter__(self) -> "_StubConn":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _StubAcquireCtx:
    """Async context manager wrapping a _StubConn."""

    def __init__(self, conn: _StubConn) -> None:
        """Initialise with an underlying connection.

        Args:
            conn: The stub connection to expose.
        """
        self._conn = conn

    async def __aenter__(self) -> _StubConn:
        return self._conn

    async def __aexit__(self, *args) -> bool:
        return False


class _StubPool:
    """asyncpg pool stub; returns a single reusable connection."""

    def __init__(self, rows: list[_StubRow]) -> None:
        """Initialise the pool with the rows the connection should return.

        Args:
            rows: Rows returned by the connection's ``fetch()`` method.
        """
        self._conn = _StubConn(rows)

    def acquire(self) -> _StubAcquireCtx:
        """Return an async context manager that yields the stub connection.

        Returns:
            Async context manager producing the stub connection.
        """
        return _StubAcquireCtx(self._conn)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def storage_factory():
    """Factory fixture that creates a PostgresFormStorage with stubbed pool.

    Returns:
        Callable accepting a list of rows and returning a configured storage.
    """
    def make(rows: list[_StubRow]) -> PostgresFormStorage:
        return PostgresFormStorage(pool=_StubPool(rows))
    return make


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_forms_localized_title_flattens(storage_factory) -> None:
    """Localized title dict should be flattened to the first value."""
    rows = [_StubRow(
        form_id="f-1",
        version="1.0",
        schema_json=json.dumps({
            "title": {"en": "Hello", "es": "Hola"},
            "description": "Daily report",
        }),
        created_at=datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 12, 10, 31, tzinfo=timezone.utc),
    )]
    out = await storage_factory(rows).list_forms()
    assert out == [{
        "form_id": "f-1",
        "version": "1.0",
        "title": "Hello",
        "description": "Daily report",
        "created_at": "2026-04-12T10:31:00+00:00",
    }]


@pytest.mark.asyncio
async def test_list_forms_description_missing_or_none(storage_factory) -> None:
    """Missing or null description should produce None in the result dict."""
    rows = [
        _StubRow(
            form_id="a",
            version="1.0",
            schema_json=json.dumps({"title": "A"}),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        _StubRow(
            form_id="b",
            version="1.0",
            schema_json=json.dumps({"title": "B", "description": None}),
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
    ]
    out = await storage_factory(rows).list_forms()
    assert out[0]["description"] is None
    assert out[1]["description"] is None


@pytest.mark.asyncio
async def test_list_forms_created_at_none_defensive(storage_factory) -> None:
    """NULL created_at in the row (defensive case) should produce None."""
    rows = [_StubRow(
        form_id="x",
        version="1.0",
        schema_json=json.dumps({"title": "X"}),
        created_at=None,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )]
    out = await storage_factory(rows).list_forms()
    assert out[0]["created_at"] is None


@pytest.mark.asyncio
async def test_list_forms_malformed_schema_json(storage_factory) -> None:
    """Malformed schema_json should fall back to title='', description=None."""
    rows = [_StubRow(
        form_id="bad",
        version="1.0",
        schema_json="not-json",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )]
    out = await storage_factory(rows).list_forms()
    assert out[0]["title"] == ""
    assert out[0]["description"] is None
    # created_at is set before the try/except so it should still be present
    assert out[0]["created_at"] == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_list_forms_multiple_rows_preserve_order(storage_factory) -> None:
    """Multiple rows should be returned in the same order the DB provides."""
    rows = [
        _StubRow(
            form_id="a",
            version="1.0",
            schema_json=json.dumps({"title": "A"}),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        _StubRow(
            form_id="b",
            version="1.0",
            schema_json=json.dumps({"title": "B"}),
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
    ]
    out = await storage_factory(rows).list_forms()
    assert [d["form_id"] for d in out] == ["a", "b"]


def test_form_storage_list_forms_docstring_contract() -> None:
    """FormStorage.list_forms docstring must document the rich keys."""
    doc = FormStorage.list_forms.__doc__ or ""
    for key in ("form_id", "version", "title", "description", "created_at"):
        assert key in doc, f"docstring should mention {key}"
    assert "ISO-8601" in doc or "isoformat" in doc.lower()
