"""Unit tests for PostgresFormStorage form_uid rekeying (FEAT-389, TASK-1974).

Covers:
- DDL includes the new `form_uid` column and UNIQUE constraints.
- `save()`/`load()`/`delete()` operate on `form_uid` (not `form_id`).
- `load_by_slug()` — backward-compatible slug-based lookup.
- UPSERT conflict target is `(form_uid, version)`, and a rename (form_id
  change under the same form_uid) updates the stored slug.

Uses in-memory asyncpg stubs — no real PostgreSQL required.
"""

from __future__ import annotations

import uuid

import pytest
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.storage import PostgresFormStorage

# ---------------------------------------------------------------------------
# asyncpg stubs
# ---------------------------------------------------------------------------


class _Conn:
    """asyncpg connection stub recording execute()/fetchrow() calls.

    `fetchrow_queue` lets tests seed the row(s) that subsequent
    `fetchrow()` calls should return, FIFO.
    """

    def __init__(self, execute_result: str = "INSERT 0 1") -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.fetchrow_calls: list[tuple[str, tuple]] = []
        self.fetchrow_queue: list[dict | None] = []
        self._execute_result = execute_result

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return self._execute_result

    async def fetchrow(self, sql: str, *args):
        self.fetchrow_calls.append((sql, args))
        if self.fetchrow_queue:
            return self.fetchrow_queue.pop(0)
        return None


class _Pool:
    """asyncpg pool stub; returns a single reusable connection."""

    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool.conn

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()


def _make_storage(conn: _Conn | None = None) -> tuple[PostgresFormStorage, _Conn]:
    conn = conn or _Conn()
    return PostgresFormStorage(pool=_Pool(conn)), conn


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------


def test_create_table_sql_includes_form_uid_column_and_constraints() -> None:
    """DDL adds form_uid NOT NULL plus both UNIQUE constraints."""
    storage, _ = _make_storage()
    sql = storage._create_table_sql(None)
    assert "form_uid VARCHAR(36) NOT NULL" in sql
    assert "UNIQUE(form_uid, version)" in sql
    assert "UNIQUE(tenant, form_id, version)" in sql


def test_list_sql_distinct_on_form_uid() -> None:
    """_list_sql groups by DISTINCT ON (form_uid), not form_id."""
    storage, _ = _make_storage()
    sql = storage._list_sql(None)
    assert "DISTINCT ON (form_uid)" in sql


def test_upsert_sql_conflict_target_is_form_uid_version() -> None:
    """_upsert_sql's ON CONFLICT target is (form_uid, version)."""
    storage, _ = _make_storage()
    sql = storage._upsert_sql(None)
    assert "ON CONFLICT (form_uid, version)" in sql


def test_upsert_sql_updates_form_id_on_conflict() -> None:
    """A rename (form_id change under the same form_uid) updates the slug
    column on UPSERT — renaming a form must not orphan its storage row."""
    storage, _ = _make_storage()
    sql = storage._upsert_sql(None)
    assert "form_id = EXCLUDED.form_id" in sql


# ---------------------------------------------------------------------------
# save() / load()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_passes_form_uid_as_first_param() -> None:
    """save() includes form.form_uid as the first positional query param."""
    storage, conn = _make_storage()
    uid = str(uuid.uuid4())
    form = FormSchema(form_uid=uid, form_id="my-form", title="My Form", sections=[])
    await storage.save(form)

    _, args = conn.executed[0]
    # TASK-2008: form_uid column is VARCHAR(36) until migrated — the storage
    # boundary binds the canonical UUID string, not the uuid.UUID object.
    assert args[0] == uid
    assert args[1] == "my-form"


@pytest.mark.asyncio
async def test_save_and_load_by_form_uid() -> None:
    """Save a form, then load it back by form_uid."""
    uid = str(uuid.uuid4())
    form = FormSchema(form_uid=uid, form_id="my-form", title="My Form", sections=[])
    storage, conn = _make_storage()

    await storage.save(form)

    conn.fetchrow_queue.append({"schema_json": form.model_dump_json(), "created_at": None})
    loaded = await storage.load(uuid.UUID(uid))

    assert loaded is not None
    assert loaded.form_uid == uuid.UUID(uid)

    sql, load_args = conn.fetchrow_calls[0]
    assert "form_uid" in sql
    assert load_args[0] == uid


@pytest.mark.asyncio
async def test_load_with_version_queries_form_uid_and_version() -> None:
    """load(form_uid, version=...) uses the versioned query."""
    uid = str(uuid.uuid4())
    form = FormSchema(form_uid=uid, form_id="versioned", title="V", sections=[], version="2.0")
    storage, conn = _make_storage()
    conn.fetchrow_queue.append({"schema_json": form.model_dump_json(), "created_at": None})

    loaded = await storage.load(uuid.UUID(uid), version="2.0")

    assert loaded is not None
    sql, args = conn.fetchrow_calls[0]
    assert "form_uid" in sql and "version" in sql
    assert args == (uid, "2.0")


# ---------------------------------------------------------------------------
# load_by_slug()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_by_slug() -> None:
    """load_by_slug() resolves a form by (tenant, form_id)."""
    uid = str(uuid.uuid4())
    form = FormSchema(form_uid=uid, form_id="slug-form", title="Slug Form", sections=[])
    storage, conn = _make_storage()
    conn.fetchrow_queue.append({"schema_json": form.model_dump_json(), "created_at": None})

    loaded = await storage.load_by_slug("slug-form", tenant="default")

    assert loaded is not None
    assert loaded.form_uid == uuid.UUID(uid)

    sql, args = conn.fetchrow_calls[0]
    assert "form_id" in sql and "tenant" in sql
    assert args == ("default", "slug-form")


@pytest.mark.asyncio
async def test_load_by_slug_not_found_returns_none() -> None:
    """load_by_slug() returns None when no row matches."""
    storage, _ = _make_storage()
    result = await storage.load_by_slug("missing-slug", tenant="default")
    assert result is None


@pytest.mark.asyncio
async def test_load_by_slug_stamps_tenant_when_missing() -> None:
    """load_by_slug() stamps the resolved tenant onto forms with tenant=None."""
    form = FormSchema(form_uid=str(uuid.uuid4()), form_id="no-tenant-form", title="T", sections=[])
    assert form.tenant is None
    storage, conn = _make_storage()
    conn.fetchrow_queue.append({"schema_json": form.model_dump_json(), "created_at": None})

    loaded = await storage.load_by_slug("no-tenant-form", tenant="epson")

    assert loaded is not None
    assert loaded.tenant == "epson"


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_by_form_uid() -> None:
    """delete() queries and deletes by form_uid, returning True on success."""
    conn = _Conn(execute_result="DELETE 1")
    storage, _ = _make_storage(conn)

    result = await storage.delete("test-uid-004")

    assert result is True
    sql, args = conn.executed[0]
    assert "form_uid" in sql
    assert args[0] == "test-uid-004"


@pytest.mark.asyncio
async def test_delete_by_form_uid_not_found() -> None:
    """delete() returns False when no row matched the form_uid."""
    conn = _Conn(execute_result="DELETE 0")
    storage, _ = _make_storage(conn)

    result = await storage.delete("nonexistent-uid")

    assert result is False
