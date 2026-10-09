"""Unit tests for `UserInfoService.get_profile_by_email` (FEAT-647 / TASK-4179)."""

import pytest

from parrot.auth.userinfo import UserInfoService


def _vw_users_row(**overrides):
    row = {
        "user_id": 42,
        "username": "jlara",
        "display_name": "Jesus Lara",
        "email": "jlara@example.com",
        "job_code": "ENG-3",
        "title": "Sr Engineer",
        "department_code": "TECH",
        "worker_type": "FTE",
        "manager_id": None,
        "groups": ["curators"],
        "programs": [],
    }
    row.update(overrides)
    return row


class _FakeConnection:
    """Fake asyncdb connection with independent multi- and single-row queues."""

    def __init__(self, all_rows: list, one_rows: list):
        self._all_rows = list(all_rows)
        self._one_rows = list(one_rows)
        self.fetch_all_calls: list = []
        self.fetch_one_calls: list = []

    async def fetch_all(self, query, *params):
        self.fetch_all_calls.append((query, params))
        return list(self._all_rows)

    async def fetch_one(self, query, *params):
        self.fetch_one_calls.append((query, params))
        return self._one_rows.pop(0) if self._one_rows else None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConnectionCtx:
    """Mimics `await db.connection()` returning an async context manager."""

    def __init__(self, conn):
        self._conn = conn

    def __await__(self):
        async def _inner():
            return self._conn

        return _inner().__await__()


class _FakeDB:
    """Fake AsyncDB that returns one shared connection."""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return _FakeConnectionCtx(self._conn)


def _make_service(all_rows, one_rows):
    service = UserInfoService()
    conn = _FakeConnection(all_rows, one_rows)
    service._db = _FakeDB(conn)
    return service, conn


class TestGetProfileByEmail:
    """Tests for case-insensitive email-to-profile resolution."""

    @pytest.mark.asyncio
    async def test_single_match_returns_profile(self):
        service, conn = _make_service([{"user_id": 42}], [_vw_users_row()])

        profile = await service.get_profile_by_email("JLara@Example.com")

        assert profile is not None
        assert profile.username == "jlara"
        assert "lower(email) = lower($1)" in conn.fetch_all_calls[0][0]
        assert conn.fetch_all_calls[0][1] == ("JLara@Example.com",)

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        service, _ = _make_service([], [])

        assert await service.get_profile_by_email("nobody@example.com") is None

    @pytest.mark.asyncio
    async def test_ambiguous_returns_none(self):
        service, conn = _make_service([{"user_id": 1}, {"user_id": 2}], [_vw_users_row()])

        assert await service.get_profile_by_email("dup@example.com") is None
        assert conn.fetch_one_calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("email", ["", "   "])
    async def test_blank_email_skips_db(self, email):
        service, conn = _make_service([{"user_id": 42}], [_vw_users_row()])

        assert await service.get_profile_by_email(email) is None
        assert conn.fetch_all_calls == []

    @pytest.mark.asyncio
    async def test_profile_cache_reused(self):
        service, conn = _make_service([{"user_id": 42}], [_vw_users_row()])

        await service.get_profile_by_email("jlara@example.com")
        await service.get_profile_by_email("jlara@example.com")

        assert len(conn.fetch_one_calls) == 1
