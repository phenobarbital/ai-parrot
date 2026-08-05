"""Unit tests for `UserInfoService` + `EmployeeProfile` (FEAT-406 / TASK-2112).

Covers curated field exposure, nested `ManagerRef`, TTL cache hit (single DB
query), and missing-row handling (`None`, never an exception).

`AsyncDB.connection()` is mocked as an async context manager yielding a fake
connection whose `fetch_one()` is driven by a queue of canned rows — the
first call returns the main `auth.vw_users` row, the second (if the row has
a `manager_id`) returns the manager sub-lookup row.
"""
import pytest

from parrot.auth.userinfo import EmployeeProfile, ManagerRef, UserInfoService

# ── Fixtures ─────────────────────────────────────────────────────────────────


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
        "manager_id": 10,
        "groups": ["engineering", "platform"],
        "programs": ["ai-parrot"],
    }
    row.update(overrides)
    return row


def _manager_row(**overrides):
    row = {"user_id": 10, "display_name": "Manager Name", "email": "mgr@example.com"}
    row.update(overrides)
    return row


class _FakeConnection:
    """Fake asyncdb connection whose fetch_one() pops from a queue of rows."""

    def __init__(self, rows: list):
        self._rows = list(rows)
        self.fetch_one_calls: list = []

    async def fetch_one(self, query, *params):
        self.fetch_one_calls.append((query, params))
        if not self._rows:
            return None
        return self._rows.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConnectionCtx:
    """Mimics `await db.connection()` returning an async context manager."""

    def __init__(self, conn: _FakeConnection):
        self._conn = conn

    def __await__(self):
        async def _inner():
            return self._conn
        return _inner().__await__()


class _FakeDB:
    """Fake AsyncDB — `connection()` returns the same `_FakeConnection` every call."""

    def __init__(self, conn: _FakeConnection):
        self._conn = conn

    def connection(self):
        return _FakeConnectionCtx(self._conn)


def _make_service(rows: list) -> tuple[UserInfoService, _FakeConnection]:
    service = UserInfoService()
    conn = _FakeConnection(rows)
    service._db = _FakeDB(conn)
    return service, conn


# ── EmployeeProfile / ManagerRef shape ───────────────────────────────────────


class TestEmployeeProfile:
    def test_profile_curated_fields(self):
        profile = EmployeeProfile(
            user_id=42,
            username="jlara",
            display_name="Jesus Lara",
            email="jlara@example.com",
            job_code="ENG-3",
            title="Sr Engineer",
            department_code="TECH",
            groups=["engineering"],
            programs=["ai-parrot"],
            worker_type="FTE",
            manager=ManagerRef(user_id=10, display_name="Manager Name", email="mgr@example.com"),
        )
        assert profile.user_id == 42
        assert profile.username == "jlara"
        assert profile.groups == ["engineering"]
        assert profile.programs == ["ai-parrot"]
        assert profile.manager.user_id == 10
        assert profile.manager.display_name == "Manager Name"
        assert profile.manager.email == "mgr@example.com"

    def test_manager_ref_nested(self):
        ref = ManagerRef(user_id=10, display_name="Manager Name", email="mgr@example.com")
        assert ref.user_id == 10
        assert ref.display_name == "Manager Name"
        assert ref.email == "mgr@example.com"

    def test_manager_optional(self):
        profile = EmployeeProfile(user_id=1)
        assert profile.manager is None
        assert profile.groups == []
        assert profile.programs == []


# ── UserInfoService.get_profile ──────────────────────────────────────────────


class TestUserInfoService:
    @pytest.mark.asyncio
    async def test_get_profile_returns_profile(self):
        service, _conn = _make_service([_vw_users_row(), _manager_row()])

        profile = await service.get_profile(42)

        assert isinstance(profile, EmployeeProfile)
        assert profile.user_id == 42
        assert profile.username == "jlara"
        assert profile.display_name == "Jesus Lara"
        assert profile.department_code == "TECH"
        assert profile.groups == ["engineering", "platform"]
        assert profile.programs == ["ai-parrot"]
        assert isinstance(profile.manager, ManagerRef)
        assert profile.manager.user_id == 10
        assert profile.manager.display_name == "Manager Name"

    @pytest.mark.asyncio
    async def test_get_profile_no_manager(self):
        service, conn = _make_service([_vw_users_row(manager_id=None)])

        profile = await service.get_profile(42)

        assert profile.manager is None
        # Only the main query ran — no manager sub-lookup attempted.
        assert len(conn.fetch_one_calls) == 1

    @pytest.mark.asyncio
    async def test_profile_cache_ttl(self):
        service, conn = _make_service([_vw_users_row(), _manager_row()])

        first = await service.get_profile(42)
        second = await service.get_profile(42)

        assert first is second
        # Only ONE DB round-trip (main + manager query) — second call hit cache.
        assert len(conn.fetch_one_calls) == 2

    @pytest.mark.asyncio
    async def test_profile_missing_row(self):
        service, _conn = _make_service([None])

        profile = await service.get_profile(999)

        assert profile is None
