"""Tests for ``FormSubmissionStorage.has_submissions``.

``has_submissions`` answers one question — does this form have at least one
submission row? — so that ``FormVersionService`` can enforce the FEAT-300 §8
invariant ("a form with >=1 response can never be deleted") through its
``has_responses`` hook.

These tests reuse the recording asyncpg stubs from
``test_storage_schema_tenant`` / ``test_submission_revisions``, so the
connection surface stays the one the rest of the suite already models:
``execute`` / ``fetchrow`` / ``fetch``. No real PostgreSQL is required.
"""

from __future__ import annotations

import uuid

from parrot_formdesigner.services.submissions import FormSubmissionStorage

from .test_storage_schema_tenant import _RecordingPool
from .test_submission_revisions import _RowsPool

_TEST_FORM_UID = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


class TestHasSubmissionsResult:
    """The boolean contract."""

    async def test_false_when_no_row_matches(self) -> None:
        # _RecordingConn.fetchrow() returns None — the "no submissions" case.
        storage = FormSubmissionStorage(pool=_RecordingPool())
        assert await storage.has_submissions(_TEST_FORM_UID) is False

    async def test_true_when_a_row_matches(self) -> None:
        storage = FormSubmissionStorage(pool=_RowsPool(row={"exists": 1}))
        assert await storage.has_submissions(_TEST_FORM_UID) is True


class TestHasSubmissionsQuery:
    """The SQL it issues."""

    async def test_binds_form_uid_as_the_only_parameter(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).has_submissions(_TEST_FORM_UID)

        sql, args = pool.conn.fetched[0]
        assert args == (_TEST_FORM_UID,)
        assert "WHERE form_uid = $1" in sql

    async def test_stops_at_the_first_row(self) -> None:
        """An existence probe must not scan the whole partition."""
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).has_submissions(_TEST_FORM_UID)

        sql, _ = pool.conn.fetched[0]
        assert "LIMIT 1" in sql

    async def test_matches_form_uid_not_the_slug(self) -> None:
        """``form_id`` is renameable; ``form_uid`` is the stable identity."""
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).has_submissions(_TEST_FORM_UID)

        sql, _ = pool.conn.fetched[0]
        assert "form_id" not in sql

    async def test_counts_invalid_submissions_too(self) -> None:
        """An invalid submission is still a response.

        Filtering on ``is_valid`` would let a form be deleted out from under
        rows that failed validation, orphaning them.
        """
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).has_submissions(_TEST_FORM_UID)

        sql, _ = pool.conn.fetched[0]
        assert "is_valid" not in sql


class TestHasSubmissionsSchemaResolution:
    """Tenant / schema resolution, consistent with the other read methods."""

    async def test_defaults_to_navigator_form_data(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).has_submissions(_TEST_FORM_UID)

        sql, _ = pool.conn.fetched[0]
        assert '"navigator"."form_data"' in sql

    async def test_per_call_tenant_overrides_the_schema(self) -> None:
        pool = _RecordingPool()
        await FormSubmissionStorage(pool=pool).has_submissions(_TEST_FORM_UID, tenant="epson")

        sql, _ = pool.conn.fetched[0]
        assert '"epson"."form_data"' in sql

    async def test_constructor_tenant_is_the_default(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool, tenant="epson")
        await storage.has_submissions(_TEST_FORM_UID)

        sql, _ = pool.conn.fetched[0]
        assert '"epson"."form_data"' in sql

    async def test_configured_table_name_is_honoured(self) -> None:
        pool = _RecordingPool()
        storage = FormSubmissionStorage(pool=pool, table_name="form_submissions")
        await storage.has_submissions(_TEST_FORM_UID)

        sql, _ = pool.conn.fetched[0]
        assert '"navigator"."form_submissions"' in sql
