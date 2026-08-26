"""Unit tests for FormSubmission.extra_data + the extra_data JSONB column
(FEAT-458 Module 4).

Covers the model field, the SQL builders (DDL, ALTER, insert cast),
store()'s serialization, and _row_to_submission's mapping — including the
"NULL never becomes {}" rule (spec AC23).
"""

import json
import uuid
from datetime import UTC, datetime

import pytest
from parrot_formdesigner.services.submissions import (
    FormSubmission,
    FormSubmissionStorage,
)


def _sub(**kw):
    return FormSubmission(
        form_uid=uuid.uuid4(),
        form_id="f",
        form_version="1.0",
        data={"name": "Ana"},
        is_valid=True,
        **kw,
    )


class TestModel:
    def test_extra_data_optional(self):
        assert _sub().extra_data is None

    def test_extra_data_roundtrip(self):
        s = _sub(extra_data={"legacy_id": 42})
        assert FormSubmission(**s.model_dump()).extra_data == {"legacy_id": 42}


class TestSQL:
    @pytest.fixture
    def storage(self):
        return FormSubmissionStorage(pool=object())

    def test_create_table_includes_column(self, storage):
        assert "extra_data JSONB" in storage._create_table_sql(None)

    def test_alter_table_adds_column(self, storage):
        assert "ADD COLUMN IF NOT EXISTS extra_data JSONB" in storage._alter_table_sql(None)

    def test_insert_casts_extra_data(self, storage):
        """The ::text::jsonb cast is mandatory — see :255-273."""
        sql = storage._insert_sql(None)
        assert "$22::text::jsonb" in sql
        assert "extra_data" in sql

    def test_select_columns_includes_extra_data(self, storage):
        assert "extra_data" in storage._SELECT_COLUMNS


class TestRowMapping:
    def _row(self, value):
        return {
            "submission_id": "s",
            "form_uid": uuid.uuid4(),
            "form_id": "f",
            "form_version": "1.0",
            "data": {"name": "Ana"},
            "is_valid": True,
            "forwarded": False,
            "forward_status": None,
            "forward_error": None,
            "tenant": None,
            "created_at": datetime.now(UTC),
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
            "extra_data": value,
        }

    def test_dict_passthrough(self):
        s = FormSubmissionStorage._row_to_submission(self._row({"a": 1}))
        assert s.extra_data == {"a": 1}

    def test_json_string_parsed(self):
        """Codec-registered pool hands back a str."""
        s = FormSubmissionStorage._row_to_submission(self._row(json.dumps({"a": 1})))
        assert s.extra_data == {"a": 1}

    def test_null_stays_none_not_empty_dict(self):
        """Spec AC23 — NULL must NOT become {}."""
        s = FormSubmissionStorage._row_to_submission(self._row(None))
        assert s.extra_data is None


class _FakeConn:
    def __init__(self, pool: "_FakePool") -> None:
        self.pool = pool

    async def execute(self, sql: str, *args: object) -> None:
        self.pool.last_sql = sql
        self.pool.last_args = args


class _AcquireCtx:
    def __init__(self, pool: "_FakePool") -> None:
        self.pool = pool

    async def __aenter__(self) -> _FakeConn:
        return _FakeConn(self.pool)

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    """asyncpg-pool double recording the last execute() call's args."""

    def __init__(self) -> None:
        self.last_sql: str | None = None
        self.last_args: tuple = ()

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self)


@pytest.fixture
def fake_pool():
    return _FakePool()


class TestStore:
    async def test_serializes_extra_data(self, fake_pool):
        storage = FormSubmissionStorage(pool=fake_pool)
        await storage.store(_sub(extra_data={"legacy_id": 42}))
        assert json.dumps({"legacy_id": 42}) in fake_pool.last_args

    async def test_none_passed_as_none(self, fake_pool):
        storage = FormSubmissionStorage(pool=fake_pool)
        await storage.store(_sub())
        assert fake_pool.last_args[-1] is None
