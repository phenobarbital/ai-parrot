"""Unit tests for `PostgresTableSink` (FEAT-457, TASK-2422).

Uses a fake asyncpg-like pool that records executed SQL and simulates
`information_schema.columns` lookups — no real database required.
"""

import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.core.persistence import PostgresTableTarget, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry
from parrot_formdesigner.services.sinks.base import (
    SinkTargetMismatchError,
    SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.postgres_table import PostgresTableSink
from parrot_formdesigner.services.submissions import FormSubmission


class _FakeConn:
    def __init__(self, pool: "_FakePool") -> None:
        self.pool = pool

    async def execute(self, sql: str, *args: object) -> None:
        self.pool.executed.append(sql)

    async def fetch(self, sql: str, *args: object):
        if "information_schema.columns" in sql:
            return [{"column_name": k, "data_type": v} for k, v in self.pool.existing_columns.items()]
        return self.pool.fetch_rows

    async def fetchrow(self, sql: str, *args: object):
        return self.pool.fetchrow_result


class _AcquireCtx:
    def __init__(self, pool: "_FakePool") -> None:
        self.pool = pool

    async def __aenter__(self) -> _FakeConn:
        return _FakeConn(self.pool)

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self, existing_columns=None, fetchrow_result=None, fetch_rows=None):
        self.executed: list[str] = []
        self.existing_columns = existing_columns or {}
        self.fetchrow_result = fetchrow_result
        self.fetch_rows = fetch_rows or []

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self)

    async def close(self) -> None:
        return None


class _BrokenPool:
    def acquire(self):
        raise ConnectionError("simulated connection failure")

    async def close(self) -> None:
        return None


def _target() -> PostgresTableTarget:
    return PostgresTableTarget(
        type="postgres_table",
        connection="survey_db",
        schema_name="surveys",
        table="nps_2026",
    )


def _submission() -> FormSubmission:
    return FormSubmission(
        submission_id=str(uuid.uuid4()),
        form_uid=uuid.uuid4(),
        form_id="nps",
        form_version="1.0",
        data={"comment": "great"},
        is_valid=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def fake_pool():
    return _FakePool()


@pytest.fixture
def sink(fake_pool):
    return PostgresTableSink(
        _target(),
        alias_registry=SinkAliasRegistry(),
        tenant="navigator",
        pool=fake_pool,
    )


@pytest.fixture
def form_with_extra_field():
    section = FormSection(
        section_id="s1",
        fields=[
            FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
            FormField(field_id="rating", field_type=FieldType.INTEGER, label="Rating"),
        ],
    )
    return FormSchema(form_id="nps", title="NPS", sections=[section])


@pytest.fixture
def form_with_fewer_fields():
    section = FormSection(
        section_id="s1",
        fields=[
            FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
        ],
    )
    return FormSchema(form_id="nps", title="NPS", sections=[section])


@pytest.fixture
def sink_with_broken_pool():
    return PostgresTableSink(
        _target(),
        alias_registry=SinkAliasRegistry(),
        tenant="navigator",
        pool=_BrokenPool(),
    )


@pytest.fixture
def submission():
    return _submission()


@pytest.fixture
def sink_with_int_column():
    pool = _FakePool(existing_columns={"age": "integer"})
    return PostgresTableSink(
        _target(),
        alias_registry=SinkAliasRegistry(),
        tenant="navigator",
        pool=pool,
    )


@pytest.fixture
def form_sending_text():
    section = FormSection(
        section_id="s1",
        fields=[FormField(field_id="age", field_type=FieldType.TEXT, label="Age")],
    )
    return FormSchema(form_id="nps", title="NPS", sections=[section])


class TestDDL:
    def test_create_is_idempotent_sql(self, sink):
        assert "CREATE TABLE IF NOT EXISTS" in sink._create_table_sql()

    def test_no_destructive_sql_anywhere(self, sink):
        for sql in sink._all_sql_for_test():
            assert "DROP" not in sql.upper()
            assert "RENAME" not in sql.upper()

    def test_jsonb_uses_text_cast(self, sink):
        assert "::text::jsonb" in sink._insert_sql()

    def test_extra_data_column_is_jsonb_not_text(self, sink):
        """FEAT-458 — the reserved extra_data column must be JSONB, matching
        `context`, not fall through to the TEXT default."""
        create_sql = sink._create_table_sql()
        assert '"extra_data" JSONB' in create_sql

    def test_full_capability_set(self, sink):
        assert sink.capabilities == frozenset(
            {
                SinkCapability.WRITE,
                SinkCapability.READ,
                SinkCapability.LIST,
                SinkCapability.PROVISION,
                SinkCapability.EXTEND,
            }
        )

    async def test_new_field_adds_column(self, sink, fake_pool, form_with_extra_field):
        await sink.ensure_target(form_with_extra_field)
        assert any("ADD COLUMN IF NOT EXISTS" in s and "rating" in s for s in fake_pool.executed)

    async def test_removed_field_emits_nothing(self, sink, fake_pool, form_with_extra_field, form_with_fewer_fields):
        await sink.ensure_target(form_with_extra_field)
        fake_pool.existing_columns = {"comment": "text", "rating": "integer"}
        fake_pool.executed.clear()
        await sink.ensure_target(form_with_fewer_fields)
        assert not any("DROP" in s.upper() for s in fake_pool.executed)
        assert not any("ADD COLUMN" in s for s in fake_pool.executed)


class TestFailure:
    async def test_connection_error_maps_unavailable(self, sink_with_broken_pool, submission):
        with pytest.raises(SinkUnavailableError):
            await sink_with_broken_pool.write(submission, {"comment": "hi"})

    async def test_type_mismatch_raises(self, sink_with_int_column, form_sending_text):
        with pytest.raises(SinkTargetMismatchError):
            await sink_with_int_column.ensure_target(form_sending_text)


class TestReadWrite:
    async def test_write_returns_submission_id(self, sink, submission):
        result = await sink.write(submission, {"comment": "great"})
        assert result == submission.submission_id

    async def test_write_casts_extra_data_column(self, sink, fake_pool, submission):
        """FEAT-458 — writing an "extra_data" column uses the ::text::jsonb
        cast, the same double-encoding-hazard fix as "context"."""
        import json as json_module

        await sink.write(
            submission,
            {"comment": "great", "extra_data": json_module.dumps({"legacy_id": 42})},
        )
        insert_sql = fake_pool.executed[-1]
        assert '"extra_data"' in insert_sql
        # The placeholder position for extra_data must carry the cast.
        columns = ["comment", "extra_data"]
        placeholder_index = columns.index("extra_data") + 1
        assert f"${placeholder_index}::text::jsonb" in insert_sql

    async def test_write_read_roundtrip(self, sink, fake_pool, submission):
        await sink.write(
            submission,
            {"submission_id": submission.submission_id, "comment": "great"},
        )
        fake_pool.fetchrow_result = {
            "submission_id": submission.submission_id,
            "form_uid": submission.form_uid,
            "form_id": submission.form_id,
            "form_version": submission.form_version,
            "created_at": submission.created_at,
            "tenant": None,
            "user_id": None,
            "username": None,
            "org_id": None,
            "submitted_at": None,
            "ip": None,
            "user_agent": None,
            "locale": None,
            "root_submission_id": None,
            "revision": None,
            "context": None,
            "comment": "great",
        }
        result = await sink.read(submission.submission_id)
        assert result is not None
        assert result.submission_id == submission.submission_id
        assert result.data == {"comment": "great"}

    async def test_read_missing_returns_none(self, sink, fake_pool):
        fake_pool.fetchrow_result = None
        assert await sink.read("nonexistent") is None

    async def test_read_reconstructs_extra_data_dict(self, sink, fake_pool, submission):
        """Code-review fix — _row_to_submission previously dropped
        extra_data entirely on read, even though write() stores it."""
        fake_pool.fetchrow_result = {
            "submission_id": submission.submission_id,
            "form_uid": submission.form_uid,
            "form_id": submission.form_id,
            "form_version": submission.form_version,
            "created_at": submission.created_at,
            "tenant": None,
            "user_id": None,
            "username": None,
            "org_id": None,
            "submitted_at": None,
            "ip": None,
            "user_agent": None,
            "locale": None,
            "root_submission_id": None,
            "revision": None,
            "context": None,
            "extra_data": {"legacy_id": 42},
            "comment": "great",
        }
        result = await sink.read(submission.submission_id)
        assert result is not None
        assert result.extra_data == {"legacy_id": 42}

    async def test_read_reconstructs_extra_data_from_json_string(self, sink, fake_pool, submission):
        """A codec-less pool hands back JSONB as a str — must still parse."""
        import json

        fake_pool.fetchrow_result = {
            "submission_id": submission.submission_id,
            "form_uid": submission.form_uid,
            "form_id": submission.form_id,
            "form_version": submission.form_version,
            "created_at": submission.created_at,
            "tenant": None,
            "user_id": None,
            "username": None,
            "org_id": None,
            "submitted_at": None,
            "ip": None,
            "user_agent": None,
            "locale": None,
            "root_submission_id": None,
            "revision": None,
            "context": None,
            "extra_data": json.dumps({"legacy_id": 42}),
            "comment": "great",
        }
        result = await sink.read(submission.submission_id)
        assert result is not None
        assert result.extra_data == {"legacy_id": 42}

    async def test_read_extra_data_null_stays_none(self, sink, fake_pool, submission):
        fake_pool.fetchrow_result = {
            "submission_id": submission.submission_id,
            "form_uid": submission.form_uid,
            "form_id": submission.form_id,
            "form_version": submission.form_version,
            "created_at": submission.created_at,
            "tenant": None,
            "user_id": None,
            "username": None,
            "org_id": None,
            "submitted_at": None,
            "ip": None,
            "user_agent": None,
            "locale": None,
            "root_submission_id": None,
            "revision": None,
            "context": None,
            "extra_data": None,
            "comment": "great",
        }
        result = await sink.read(submission.submission_id)
        assert result is not None
        assert result.extra_data is None
