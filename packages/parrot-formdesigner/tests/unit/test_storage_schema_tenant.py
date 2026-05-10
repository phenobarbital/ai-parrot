"""Tests for configurable schema/table/tenant on the Postgres storages.

Covers:
- ``PostgresFormStorage`` and ``FormSubmissionStorage`` accept ``schema``,
  ``table_name`` and ``tenant`` kwargs.
- Identifier validation rejects unsafe values.
- Per-call ``tenant=`` overrides resolve to the right ``schema.table``
  in the generated SQL.
- ``FormSchema.tenant`` and ``FormSubmission.tenant`` flow through to
  the storage call sites.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.core.schema import FormSchema, FormSection
from parrot_formdesigner.services._identifiers import (
    qualified_table,
    validate_identifier,
)
from parrot_formdesigner.services.storage import PostgresFormStorage
from parrot_formdesigner.services.submissions import (
    FormSubmission,
    FormSubmissionStorage,
)


# ---------------------------------------------------------------------------
# asyncpg stubs that capture the SQL we issued
# ---------------------------------------------------------------------------


class _RecordingConn:
    """asyncpg connection stub that records every SQL statement issued."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.fetched: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return "INSERT 0 1"

    async def fetchrow(self, sql: str, *args):
        self.fetched.append((sql, args))
        return None

    async def fetch(self, sql: str, *args):
        self.fetched.append((sql, args))
        return []


class _RecordingPool:
    def __init__(self) -> None:
        self.conn = _RecordingConn()

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self_inner):
                return pool.conn

            async def __aexit__(self_inner, *args):
                return False

        return _Ctx()


# ---------------------------------------------------------------------------
# _identifiers
# ---------------------------------------------------------------------------


class TestIdentifierValidation:
    def test_accepts_basic(self) -> None:
        assert validate_identifier("navigator", kind="schema") == "navigator"
        assert validate_identifier("form_data") == "form_data"
        assert validate_identifier("epson_2") == "epson_2"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "1leading_digit",
            "has space",
            "has-dash",
            "drop;table",
            'quote"injected',
            "x" * 64,
        ],
    )
    def test_rejects_unsafe(self, bad: str) -> None:
        with pytest.raises(ValueError):
            validate_identifier(bad, kind="schema")

    def test_qualified_table_quotes_both_parts(self) -> None:
        assert qualified_table("navigator", "form_data") == '"navigator"."form_data"'


# ---------------------------------------------------------------------------
# PostgresFormStorage — schema/table/tenant
# ---------------------------------------------------------------------------


def _form(form_id: str = "f-1", tenant: str | None = None) -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title="Demo",
        sections=[FormSection(section_id="s", fields=[])],
        tenant=tenant,
    )


class TestPostgresFormStorageConfig:
    def test_defaults_to_navigator_form_schemas(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        assert storage._schema == "navigator"
        assert storage._table == "form_schemas"
        assert storage._tenant is None

    def test_invalid_schema_rejected_at_init(self) -> None:
        with pytest.raises(ValueError):
            PostgresFormStorage(pool=_RecordingPool(), schema="bad schema")

    def test_invalid_tenant_rejected_at_init(self) -> None:
        with pytest.raises(ValueError):
            PostgresFormStorage(pool=_RecordingPool(), tenant="evil; DROP")

    @pytest.mark.asyncio
    async def test_initialize_targets_default_schema(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        await storage.initialize()
        sql = pool.conn.executed[0][0]
        assert '"navigator"."form_schemas"' in sql

    @pytest.mark.asyncio
    async def test_initialize_targets_custom_table(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(
            pool=pool, schema="public", table_name="my_forms"
        )
        await storage.initialize()
        sql = pool.conn.executed[0][0]
        assert '"public"."my_forms"' in sql

    @pytest.mark.asyncio
    async def test_save_uses_per_call_tenant(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        await storage.save(_form(), tenant="epson")
        sql, args = pool.conn.executed[0]
        assert '"epson"."form_schemas"' in sql
        # tenant value persisted into the row (5th positional, 1-indexed)
        assert args[4] == "epson"

    @pytest.mark.asyncio
    async def test_save_uses_form_tenant_when_no_override(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        await storage.save(_form(tenant="pokemon"))
        sql, args = pool.conn.executed[0]
        assert '"pokemon"."form_schemas"' in sql
        assert args[4] == "pokemon"

    @pytest.mark.asyncio
    async def test_save_uses_default_tenant_when_form_has_none(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool, tenant="acme")
        await storage.save(_form())
        sql, _ = pool.conn.executed[0]
        assert '"acme"."form_schemas"' in sql

    @pytest.mark.asyncio
    async def test_load_uses_tenant_override(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        await storage.load("f-1", tenant="epson")
        sql, _ = pool.conn.fetched[0]
        assert '"epson"."form_schemas"' in sql

    @pytest.mark.asyncio
    async def test_delete_uses_tenant_override(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        await storage.delete("f-1", tenant="epson")
        sql, _ = pool.conn.executed[0]
        assert '"epson"."form_schemas"' in sql

    @pytest.mark.asyncio
    async def test_list_forms_uses_tenant_override(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        await storage.list_forms(tenant="epson")
        sql, _ = pool.conn.fetched[0]
        assert '"epson"."form_schemas"' in sql

    @pytest.mark.asyncio
    async def test_per_call_tenant_does_not_mutate_default(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool, tenant="acme")
        await storage.save(_form(), tenant="epson")
        await storage.save(_form())  # back to instance default
        sql_first = pool.conn.executed[0][0]
        sql_second = pool.conn.executed[1][0]
        assert '"epson"."form_schemas"' in sql_first
        assert '"acme"."form_schemas"' in sql_second

    @pytest.mark.asyncio
    async def test_invalid_per_call_tenant_rejected(self) -> None:
        pool = _RecordingPool()
        storage = PostgresFormStorage(pool=pool)
        with pytest.raises(ValueError):
            await storage.save(_form(), tenant="bad tenant")


# ---------------------------------------------------------------------------
# FormSubmissionStorage — schema/table/tenant
# ---------------------------------------------------------------------------


def _submission(tenant: str | None = None) -> FormSubmission:
    return FormSubmission(
        form_id="f-1",
        form_version="1.0",
        data={"x": 1},
        is_valid=True,
        created_at=datetime(2026, 5, 8, tzinfo=timezone.utc),
        tenant=tenant,
    )


class TestFormSubmissionStorageConfig:
    def test_defaults_to_navigator_form_data(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        assert storage._schema == "navigator"
        assert storage._table == "form_data"

    def test_default_table_name_is_form_data_not_form_submissions(self) -> None:
        # Locks in the rename agreed on with the user.
        from parrot_formdesigner.services.submissions import DEFAULT_TABLE
        assert DEFAULT_TABLE == "form_data"

    @pytest.mark.asyncio
    async def test_initialize_targets_default(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        await storage.initialize()
        sql = pool.conn.executed[0][0]
        assert '"navigator"."form_data"' in sql
        assert "idx_form_data_form_id" in sql

    @pytest.mark.asyncio
    async def test_store_uses_per_call_tenant(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        await storage.store(_submission(), tenant="epson")
        sql, args = pool.conn.executed[0]
        assert '"epson"."form_data"' in sql
        # tenant column is 9th positional in INSERT
        assert args[8] == "epson"

    @pytest.mark.asyncio
    async def test_store_uses_submission_tenant_when_no_override(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        await storage.store(_submission(tenant="pokemon"))
        sql, args = pool.conn.executed[0]
        assert '"pokemon"."form_data"' in sql
        assert args[8] == "pokemon"

    @pytest.mark.asyncio
    async def test_invalid_per_call_tenant_rejected(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        with pytest.raises(ValueError):
            await storage.store(_submission(), tenant="bad tenant")


# ---------------------------------------------------------------------------
# FormSchema / FormSubmission models — tenant field
# ---------------------------------------------------------------------------


class TestModelsTenant:
    def test_form_schema_tenant_defaults_none(self) -> None:
        f = FormSchema(
            form_id="f",
            title="t",
            sections=[FormSection(section_id="s", fields=[])],
        )
        assert f.tenant is None

    def test_form_schema_tenant_settable(self) -> None:
        f = FormSchema(
            form_id="f",
            title="t",
            sections=[FormSection(section_id="s", fields=[])],
            tenant="epson",
        )
        assert f.tenant == "epson"

    def test_form_submission_tenant_defaults_none(self) -> None:
        s = FormSubmission(
            form_id="f", form_version="1.0", data={}, is_valid=True
        )
        assert s.tenant is None

    def test_form_submission_tenant_roundtrip(self) -> None:
        s = FormSubmission(
            form_id="f",
            form_version="1.0",
            data={},
            is_valid=True,
            tenant="acme",
        )
        restored = FormSubmission.model_validate(s.model_dump())
        assert restored.tenant == "acme"
