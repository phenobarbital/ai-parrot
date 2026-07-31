"""Tests for FormSubmissionStorage DDL + INSERT with metadata columns."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.services.submissions import (
    CORE_METADATA_COLUMNS,
    FormSubmission,
    FormSubmissionStorage,
)

from .test_storage_schema_tenant import _RecordingPool

_TEST_FORM_UID = "550e8400-e29b-41d4-a716-446655440000"


class TestInitializeDDL:
    @pytest.mark.asyncio
    async def test_initialize_emits_create_then_alter(self) -> None:
        """initialize() runs the CREATE block followed by the ALTER block."""
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        await storage.initialize()
        assert len(pool.conn.executed) == 2
        create_sql, _ = pool.conn.executed[0]
        alter_sql, _ = pool.conn.executed[1]
        assert "CREATE TABLE IF NOT EXISTS" in create_sql
        assert "ALTER TABLE" in alter_sql
        assert "ADD COLUMN IF NOT EXISTS user_id" in alter_sql

    @pytest.mark.asyncio
    async def test_create_table_declares_all_core_columns(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).initialize()
        create_sql = pool.conn.executed[0][0]
        for col in CORE_METADATA_COLUMNS:
            assert col in create_sql, f"missing column {col!r} in CREATE"

    @pytest.mark.asyncio
    async def test_alter_table_declares_all_core_columns(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).initialize()
        alter_sql = pool.conn.executed[1][0]
        for col in CORE_METADATA_COLUMNS:
            assert (
                f"ADD COLUMN IF NOT EXISTS {col}" in alter_sql
            ), f"alter does not add {col!r}"


class TestStoreInsertsMetadata:
    @pytest.mark.asyncio
    async def test_insert_has_twenty_one_placeholders(self) -> None:
        """form_uid (FEAT-389) + 17 metadata/revision columns = 21 placeholders."""
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool)
        await storage.store(
            FormSubmission(
                form_uid=_TEST_FORM_UID, form_id="f", form_version="1.0", data={}, is_valid=True
            )
        )
        sql, args = pool.conn.executed[0]
        assert "$21" in sql
        assert "$22" not in sql
        assert len(args) == 21

    @pytest.mark.asyncio
    async def test_insert_carries_metadata_values_in_order(self) -> None:
        ts = datetime(2026, 5, 18, 10, 0, tzinfo=timezone.utc)
        sub = FormSubmission(
            form_uid=_TEST_FORM_UID,
            form_id="f",
            form_version="1.0",
            data={"q1": "yes"},
            is_valid=True,
            created_at=ts,
            user_id="u-42",
            username="alice",
            org_id=7,
            submitted_at=ts,
            ip="203.0.113.5",
            user_agent="ParrotTest/1.0",
            locale="en-US",
        )
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).store(sub)
        _, args = pool.conn.executed[0]
        # Args layout (1-indexed, FEAT-389 inserted form_uid as #2):
        # 1 submission_id, 2 form_uid, 3 form_id, 4 form_version, 5 data,
        # 6 is_valid, 7 forwarded, 8 forward_status, 9 forward_error,
        # 10 tenant, 11 created_at,
        # 12 user_id, 13 username, 14 org_id, 15 submitted_at,
        # 16 ip, 17 user_agent, 18 locale
        assert args[11] == "u-42"
        assert args[12] == "alice"
        assert args[13] == 7
        assert args[14] == ts
        assert args[15] == "203.0.113.5"
        assert args[16] == "ParrotTest/1.0"
        assert args[17] == "en-US"

    @pytest.mark.asyncio
    async def test_insert_nulls_metadata_when_unset(self) -> None:
        """Submissions without metadata still insert NULLs for the new columns."""
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).store(
            FormSubmission(
                form_uid=_TEST_FORM_UID, form_id="f", form_version="1.0", data={}, is_valid=True
            )
        )
        _, args = pool.conn.executed[0]
        for idx in range(11, 18):
            assert args[idx] is None, f"arg ${idx + 1} should be NULL"


class TestFormSubmissionBackCompat:
    def test_minimal_construction_still_works(self) -> None:
        """Pre-metadata callers (only form_uid added) must keep constructing."""
        sub = FormSubmission(
            form_uid=_TEST_FORM_UID, form_id="f", form_version="1.0", data={}, is_valid=True
        )
        assert sub.user_id is None
        assert sub.username is None
        assert sub.org_id is None
        assert sub.submitted_at is None
        assert sub.ip is None
        assert sub.user_agent is None
        assert sub.locale is None

    def test_serialization_roundtrip_with_metadata(self) -> None:
        ts = datetime(2026, 5, 18, tzinfo=timezone.utc)
        sub = FormSubmission(
            form_uid=_TEST_FORM_UID,
            form_id="f",
            form_version="1.0",
            data={},
            is_valid=True,
            user_id="u-1",
            username="bob",
            org_id=3,
            submitted_at=ts,
            ip="1.2.3.4",
            user_agent="ua",
            locale="es-MX",
        )
        restored = FormSubmission.model_validate(sub.model_dump())
        assert restored.user_id == "u-1"
        assert restored.username == "bob"
        assert restored.org_id == 3
        assert restored.submitted_at == ts
        assert restored.ip == "1.2.3.4"
        assert restored.user_agent == "ua"
        assert restored.locale == "es-MX"
