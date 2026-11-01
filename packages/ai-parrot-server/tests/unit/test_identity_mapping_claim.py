"""Tests for IdentityMappingService.claim_channel_identity (FEAT-777 M2).

Real-Postgres tests skip without IDENTITY_PG_DSN / parrot.conf.default_dsn or when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, List, Optional

import pytest

from parrot.services.identity_mapping import ClaimResult, IdentityMappingService


class _FailPool:
    def acquire(self) -> Any:
        raise AssertionError("DB must not be reached")


class _FakeTx:
    async def __aenter__(self) -> "_FakeTx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeRaw:
    def __init__(self, rows: List[dict]) -> None:
        self.rows = rows
        self.calls: List[str] = []

    def transaction(self) -> _FakeTx:
        return _FakeTx()

    async def execute(self, sql: str, *args: Any) -> None:
        self.calls.append("lock")

    async def fetch(self, sql: str, *args: Any) -> List[dict]:
        self.calls.append("fetch")
        return self.rows

    async def fetchrow(self, sql: str, *args: Any) -> dict:
        self.calls.append("write")
        return {"identity_id": "x"}


class _FakePool:
    def __init__(self, raw: _FakeRaw) -> None:
        self.raw = raw

    def acquire(self) -> "_FakePool":
        return self

    async def __aenter__(self) -> _FakeRaw:
        return self.raw

    async def __aexit__(self, *exc: Any) -> bool:
        return False


def _claim_kwargs(user: str = "7") -> dict:
    return {"nav_user_id": user, "auth_provider": "slack", "provider_user_id": "T1:U1", "auth_data": {"a": 1}}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", ["", "T01:U02", "abc"])
async def test_claim_rejects_non_numeric_nav_user_id(bad_id: str) -> None:
    svc = IdentityMappingService(_FailPool())
    with pytest.raises(ValueError):
        await svc.claim_channel_identity(**_claim_kwargs(bad_id))


@pytest.mark.asyncio
async def test_claim_rejects_secrets_and_empty_provider_id() -> None:
    svc = IdentityMappingService(_FailPool())
    with pytest.raises(ValueError):
        await svc.claim_channel_identity(**{**_claim_kwargs(), "auth_data": {"token": "x"}})
    with pytest.raises(ValueError):
        await svc.claim_channel_identity(**{**_claim_kwargs(), "provider_user_id": ""})


@pytest.mark.asyncio
async def test_claim_result_mapping_with_fake_connection() -> None:
    """No rows -> claimed; one enabled same owner -> already_owned; other/disabled/several -> conflict."""
    cases = [
        ([], "claimed", True),
        ([{"identity_id": 1, "user_id": 7, "enabled": True}], "already_owned", True),
        ([{"identity_id": 1, "user_id": 8, "enabled": True}], "conflict", False),
        ([{"identity_id": 1, "user_id": 7, "enabled": False}], "conflict", False),
        (
            [
                {"identity_id": 1, "user_id": 7, "enabled": True},
                {"identity_id": 2, "user_id": 8, "enabled": True},
            ],
            "conflict",
            False,
        ),
    ]
    for rows, expected, writes in cases:
        raw = _FakeRaw(rows)
        res = await IdentityMappingService(_FakePool(raw)).claim_channel_identity(**_claim_kwargs())
        assert res.status == expected
        assert raw.calls[:2] == ["lock", "fetch"]
        assert ("write" in raw.calls) is writes


@pytest.mark.asyncio
async def test_upsert_identity_slack_conflict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = IdentityMappingService(_FailPool())

    async def _conflict(**kwargs: Any) -> ClaimResult:
        return ClaimResult(status="conflict")

    monkeypatch.setattr(svc, "claim_channel_identity", _conflict)
    with pytest.raises(PermissionError):
        await svc.upsert_identity(nav_user_id="7", auth_provider="slack", provider_user_id="T1:U1", auth_data={})


@pytest.mark.asyncio
async def test_upsert_identity_slack_claimed_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = IdentityMappingService(_FailPool())

    async def _ok(**kwargs: Any) -> ClaimResult:
        return ClaimResult(status="claimed")

    monkeypatch.setattr(svc, "claim_channel_identity", _ok)
    await svc.upsert_identity(nav_user_id="7", auth_provider="slack", provider_user_id="T1:U1", auth_data={})


# --------------------------------------------------------------------------
# Real Postgres
# --------------------------------------------------------------------------


def _dsn() -> Optional[str]:
    dsn = os.environ.get("IDENTITY_PG_DSN")
    if dsn:
        return dsn
    try:
        from parrot.conf import default_dsn

        return default_dsn or None
    except Exception:  # noqa: BLE001
        return None


class _ConnPool:
    """Pool facade yielding a fixed asyncpg connection."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> "_ConnPool":
        return self

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


async def _connect() -> Any:
    dsn = _dsn()
    if not dsn:
        pytest.skip("no Postgres DSN (set IDENTITY_PG_DSN)")
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn, timeout=10)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unreachable: {exc}")
    ok = await conn.fetchval("SELECT to_regclass('auth.user_identities') IS NOT NULL")
    if not ok:
        await conn.close()
        pytest.skip("auth.user_identities missing")
    return conn


@pytest.mark.asyncio
async def test_channel_link_exclusive_claim_real_db() -> None:
    """Two connections, two existing user ids, one provider_user_id: one claimed and one conflict."""
    c1, c2 = await _connect(), await _connect()
    puid = f"TTEST{uuid.uuid4().hex}:U"
    try:
        users = await c1.fetch("SELECT user_id FROM auth.users ORDER BY user_id LIMIT 2")
        if len(users) < 2:
            pytest.skip("need two auth.users rows")
        u1, u2 = str(users[0]["user_id"]), str(users[1]["user_id"])
        s1, s2 = IdentityMappingService(_ConnPool(c1)), IdentityMappingService(_ConnPool(c2))
        res = await asyncio.gather(
            s1.claim_channel_identity(nav_user_id=u1, auth_provider="slack", provider_user_id=puid, auth_data={}),
            s2.claim_channel_identity(nav_user_id=u2, auth_provider="slack", provider_user_id=puid, auth_data={}),
        )
        assert sorted(r.status for r in res) == ["claimed", "conflict"]
        winner, wuser = (s1, u1) if res[0].status == "claimed" else (s2, u2)
        again = await winner.claim_channel_identity(
            nav_user_id=wuser, auth_provider="slack", provider_user_id=puid, auth_data={}
        )
        assert again.status == "already_owned"
    finally:
        await c1.execute("DELETE FROM auth.user_identities WHERE provider_user_id = $1", puid)
        await c1.close()
        await c2.close()


@pytest.mark.asyncio
async def test_disabled_owner_is_conflict_real_db() -> None:
    conn = await _connect()
    puid = f"TTEST{uuid.uuid4().hex}:U"
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO auth.user_identities (user_id, auth_provider, provider_user_id, auth_data, enabled, created_at)"
            " VALUES (1, 'slack', $1, '{}'::jsonb, false, NOW())",
            puid,
        )
        res = await IdentityMappingService(_ConnPool(conn)).claim_channel_identity(
            nav_user_id="1", auth_provider="slack", provider_user_id=puid, auth_data={}
        )
        assert res.status == "conflict"
    finally:
        await tx.rollback()
        await conn.close()
