"""Unit tests for PostgresFormStorage."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.forms import (
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    PostgresFormStorage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_conn():
    """Build an asyncpg connection mock."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    return conn


def _make_mock_pool(conn=None):
    """Build an asyncpg pool mock that yields a connection via acquire()."""
    if conn is None:
        conn = _make_mock_conn()

    pool = MagicMock()
    # async context manager: async with pool.acquire() as conn
    acquire_ctx = AsyncMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool, conn


@pytest.fixture
def conn():
    return _make_mock_conn()


@pytest.fixture
def mock_pool(conn):
    pool, _ = _make_mock_pool(conn)
    return pool


@pytest.fixture
def storage(mock_pool):
    return PostgresFormStorage(pool=mock_pool)


@pytest.fixture
def sample_form():
    return FormSchema(
        form_id="persist-test",
        title="Persist Test",
        version="1.0",
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(field_id="f", field_type=FieldType.TEXT, label="F")
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# DDL / structure tests
# ---------------------------------------------------------------------------

class TestPostgresFormStorageSQL:
    """Tests for SQL constants."""

    def test_create_table_sql_valid(self, storage):
        """CREATE_TABLE_SQL contains expected elements."""
        assert "CREATE TABLE IF NOT EXISTS" in storage.CREATE_TABLE_SQL
        assert "form_schemas" in storage.CREATE_TABLE_SQL
        assert "form_id" in storage.CREATE_TABLE_SQL
        assert "schema_json JSONB" in storage.CREATE_TABLE_SQL
        assert "UNIQUE" in storage.CREATE_TABLE_SQL

    def test_upsert_sql_has_on_conflict(self, storage):
        """UPSERT_SQL handles conflicts."""
        assert "ON CONFLICT" in storage.UPSERT_SQL
        assert "DO UPDATE" in storage.UPSERT_SQL


# ---------------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------------

class TestPostgresFormStorageInitialize:
    """Tests for initialize()."""

    async def test_initialize_calls_execute(self, storage, conn):
        """initialize() executes the CREATE TABLE SQL."""
        await storage.initialize()
        conn.execute.assert_called_once_with(storage.CREATE_TABLE_SQL)


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------

class TestPostgresFormStorageSave:
    """Tests for save()."""

    async def test_save_calls_execute(self, storage, sample_form, conn):
        """save() calls conn.execute with UPSERT SQL."""
        await storage.save(sample_form)
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args[0]
        assert call_args[0] == storage.UPSERT_SQL
        # First positional arg after SQL is form_id
        assert call_args[1] == "persist-test"

    async def test_save_returns_form_id(self, storage, sample_form):
        """save() returns the form_id."""
        result = await storage.save(sample_form)
        assert result == "persist-test"

    async def test_save_serializes_schema_json(self, storage, sample_form, conn):
        """save() passes schema_json as a JSON string."""
        await storage.save(sample_form)
        call_args = conn.execute.call_args[0]
        # 3rd arg (index 2) is schema_json
        schema_str = call_args[3]
        data = json.loads(schema_str)
        assert data["form_id"] == "persist-test"

    async def test_save_with_style(self, storage, sample_form, conn):
        """save() passes style_json when StyleSchema provided."""
        from parrot.forms import StyleSchema, LayoutType
        style = StyleSchema(layout=LayoutType.TWO_COLUMN)
        await storage.save(sample_form, style=style)
        call_args = conn.execute.call_args[0]
        # 4th arg (index 3) is style_json
        style_str = call_args[4]
        assert style_str is not None
        style_data = json.loads(style_str)
        assert style_data["layout"] == "two_column"


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

class TestPostgresFormStorageLoad:
    """Tests for load()."""

    async def test_load_returns_none_on_miss(self, storage, conn):
        """load() returns None when form not found."""
        conn.fetchrow.return_value = None
        result = await storage.load("nonexistent")
        assert result is None

    async def test_load_returns_form_schema(self, storage, sample_form, conn):
        """load() deserializes JSON to FormSchema."""
        schema_json = json.dumps(sample_form.model_dump())
        conn.fetchrow.return_value = {"schema_json": schema_json}
        result = await storage.load("persist-test")
        assert result is not None
        assert result.form_id == "persist-test"

    async def test_load_latest_uses_load_sql(self, storage, conn):
        """load() without version uses LOAD_SQL (latest)."""
        conn.fetchrow.return_value = None
        await storage.load("some-form")
        call_args = conn.fetchrow.call_args[0]
        assert call_args[0] == storage.LOAD_SQL

    async def test_load_version_uses_version_sql(self, storage, conn):
        """load() with version uses LOAD_VERSION_SQL."""
        conn.fetchrow.return_value = None
        await storage.load("some-form", version="2.0")
        call_args = conn.fetchrow.call_args[0]
        assert call_args[0] == storage.LOAD_VERSION_SQL
        assert call_args[2] == "2.0"


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------

class TestPostgresFormStorageDelete:
    """Tests for delete()."""

    async def test_delete_returns_true_on_deletion(self, storage, conn):
        """delete() returns True when row was deleted."""
        conn.execute.return_value = "DELETE 1"
        result = await storage.delete("some-form")
        assert result is True

    async def test_delete_returns_false_on_miss(self, storage, conn):
        """delete() returns False when form not found."""
        conn.execute.return_value = "DELETE 0"
        result = await storage.delete("nonexistent")
        assert result is False


# ---------------------------------------------------------------------------
# list_forms()
# ---------------------------------------------------------------------------

class TestPostgresFormStorageListForms:
    """Tests for list_forms()."""

    async def test_list_empty(self, storage, conn):
        """list_forms() returns empty list when no forms stored."""
        conn.fetch.return_value = []
        result = await storage.list_forms()
        assert result == []

    async def test_list_returns_form_metadata(self, storage, sample_form, conn):
        """list_forms() returns form_id, version, title."""
        schema_json = json.dumps(sample_form.model_dump())
        conn.fetch.return_value = [
            {
                "form_id": "persist-test",
                "version": "1.0",
                "schema_json": schema_json,
            }
        ]
        result = await storage.list_forms()
        assert len(result) == 1
        assert result[0]["form_id"] == "persist-test"
        assert result[0]["version"] == "1.0"
        assert "title" in result[0]
