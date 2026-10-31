"""FEAT-776 M4 unit tests: channel link/unlink (fake pool)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, List, Optional

import pytest

from parrot.services import identity_mapping as im
from parrot.services.identity_mapping import IdentityMappingService


class FakeConn:
    """In-memory connection applying the channel SQL semantics and recording the call order."""

    def __init__(self, rows: set, fail_upsert: bool = False) -> None:
        self.rows = rows  # {(user_id, provider, provider_user_id)}
        self.calls: List[tuple] = []
        self.in_tx = False
        self.fail_upsert = fail_upsert

    @asynccontextmanager
    async def transaction(self):
        snapshot = set(self.rows)
        self.in_tx = True
        try:
            yield
        except BaseException:
            self.rows.clear()
            self.rows.update(snapshot)
            raise
        finally:
            self.in_tx = False

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args, self.in_tx))
        if sql == im._DELETE_CHANNEL_OTHERS_SQL:
            provider, puid, uid = args
            gone = {r for r in self.rows if r[1] == provider and r[2] == puid and r[0] != uid}
            self.rows -= gone
            return f"DELETE {len(gone)}"
        if sql == im._DELETE_CHANNEL_SQL:
            provider, puid = args
            gone = {r for r in self.rows if r[1] == provider and r[2] == puid}
            self.rows -= gone
            return f"DELETE {len(gone)}"
        return "SELECT 1"

    async def fetchrow(self, sql: str, *args: Any) -> Optional[dict]:
        self.calls.append(("fetchrow", sql, args, self.in_tx))
        if self.fail_upsert:
            return None
        uid, provider, puid = args[0], args[1], args[2]
        self.rows.add((uid, provider, puid))
        return {"identity_id": 1}


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def _service(rows: set, fail_upsert: bool = False):
    conn = FakeConn(rows, fail_upsert)
    return IdentityMappingService(FakePool(conn)), conn


@pytest.mark.asyncio
async def test_link_channel_identity_moves_ownership() -> None:
    svc, conn = _service({("1", "telegram", "tg1"), ("1", "telegram", "other")})
    await svc.link_channel_identity(nav_user_id="2", auth_provider="telegram", provider_user_id="tg1", auth_data={})
    assert ("2", "telegram", "tg1") in conn.rows
    assert ("1", "telegram", "tg1") not in conn.rows
    assert ("1", "telegram", "other") in conn.rows


@pytest.mark.asyncio
async def test_link_rolls_back_when_upsert_fails() -> None:
    svc, conn = _service({("1", "telegram", "tg1")}, fail_upsert=True)
    with pytest.raises(RuntimeError):
        await svc.link_channel_identity(nav_user_id="2", auth_provider="telegram", provider_user_id="tg1", auth_data={})
    assert conn.rows == {("1", "telegram", "tg1")}


@pytest.mark.asyncio
async def test_channel_identity_lock_shared_by_mutations() -> None:
    svc, conn = _service(set())
    await svc.link_channel_identity(nav_user_id="2", auth_provider="telegram", provider_user_id="tg1", auth_data={})
    await svc.unlink_channel_identity("telegram", "tg1")
    locks = [c for c in conn.calls if c[1] == im._CHANNEL_LOCK_SQL]
    assert len(locks) == 2
    assert locks[0][2] == locks[1][2] == (im._channel_lock_key("telegram", "tg1"),)
    assert all(c[3] for c in conn.calls)  # every statement inside transaction()
    assert conn.calls[0][1] == im._CHANNEL_LOCK_SQL
    first_unlink = next(i for i, c in enumerate(conn.calls) if c[1] == im._DELETE_CHANNEL_SQL)
    assert conn.calls[first_unlink - 1][1] == im._CHANNEL_LOCK_SQL
    key = im._channel_lock_key("telegram", "tg1")
    assert -(2**63) <= key < 2**63
    assert key != im._channel_lock_key("telegram", "tg2")
    assert im._channel_lock_key("a", "bc") != im._channel_lock_key("ab", "c")


@pytest.mark.asyncio
async def test_link_channel_identity_rejects_bad_input() -> None:
    svc, conn = _service(set())
    base = {"auth_provider": "telegram", "auth_data": {}}
    with pytest.raises(ValueError):
        await svc.link_channel_identity(nav_user_id="abc", provider_user_id="tg1", **base)
    with pytest.raises(ValueError):
        await svc.link_channel_identity(nav_user_id="1", provider_user_id="", **base)
    with pytest.raises(ValueError):
        await svc.link_channel_identity(
            nav_user_id="1", provider_user_id="tg1", auth_provider="telegram", auth_data={"access_token": "x"}
        )
    assert conn.calls == []  # validation happens before any statement


@pytest.mark.asyncio
async def test_unlink_channel_identity_counts() -> None:
    svc, conn = _service({("1", "telegram", "tg1")})
    assert await svc.unlink_channel_identity("telegram", "tg1") == 1
    assert await svc.unlink_channel_identity("telegram", "tg1") == 0
