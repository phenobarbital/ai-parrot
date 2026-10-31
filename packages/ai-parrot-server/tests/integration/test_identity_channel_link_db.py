"""FEAT-776 M4 real-DB tests (opt-in: IDENTITY_PG_DSN, IDENTITY_TEST_USER_ID, IDENTITY_TEST_USER_ID_2)."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator

import pytest

from parrot.services.identity_mapping import IdentityMappingService
from parrot.services.identity_principal import IdentityPrincipalResolver

asyncpg = pytest.importorskip("asyncpg")


@pytest.fixture
async def link_db() -> AsyncIterator[tuple[Any, Any, str, str, str]]:
    """Yield two services on two pools, two user ids and a unique provider_user_id."""
    dsn = os.getenv("IDENTITY_PG_DSN")
    user_a = os.getenv("IDENTITY_TEST_USER_ID")
    user_b = os.getenv("IDENTITY_TEST_USER_ID_2")
    if not (dsn and user_a and user_b):
        pytest.skip("IDENTITY_PG_DSN, IDENTITY_TEST_USER_ID and IDENTITY_TEST_USER_ID_2 are required")
    try:
        pool1 = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        pool2 = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        async with pool1.acquire() as connection:
            if not await connection.fetchval("SELECT to_regclass('auth.user_identities')"):
                pytest.skip("auth.user_identities is unavailable")
    except Exception as exc:  # pragma: no cover - depends on external Postgres
        pytest.skip(f"auth database is unreachable: {exc}")
    puid = f"task-5019-{uuid.uuid4()}"
    svc1, svc2 = IdentityMappingService(pool1), IdentityMappingService(pool2)
    try:
        yield svc1, svc2, user_a, user_b, puid
    finally:
        await svc1.unlink_channel_identity("telegram", puid)
        await pool1.close()
        await pool2.close()


class _FailingUpsertPool:
    """Pool proxy whose connections fail the upsert after the delete ran."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    def acquire(self) -> Any:
        pool = self._pool

        class _Ctx:
            async def __aenter__(self_inner) -> Any:
                self_inner.conn = await pool.acquire()
                conn = self_inner.conn

                class _Proxy:
                    def __getattr__(self_p, name: str) -> Any:
                        return getattr(conn, name)

                    async def fetchrow(self_p, *args: Any, **kwargs: Any) -> Any:
                        raise RuntimeError("forced upsert failure")

                return _Proxy()

            async def __aexit__(self_inner, *exc: Any) -> None:
                await pool.release(self_inner.conn)

        return _Ctx()


async def _owners(svc: IdentityMappingService, puid: str) -> list:
    async with svc._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id FROM auth.user_identities WHERE auth_provider = 'telegram' AND provider_user_id = $1", puid
        )
    return [str(r["user_id"]) for r in rows]


@pytest.mark.asyncio
async def test_db_concurrent_channel_identity_links(link_db) -> None:
    svc1, svc2, user_a, user_b, puid = link_db
    for _ in range(5):
        await asyncio.gather(
            svc1.link_channel_identity(
                nav_user_id=user_a, auth_provider="telegram", provider_user_id=puid, auth_data={}
            ),
            svc2.link_channel_identity(
                nav_user_id=user_b, auth_provider="telegram", provider_user_id=puid, auth_data={}
            ),
        )
        owners = await _owners(svc1, puid)
        assert len(owners) == 1 and owners[0] in (user_a, user_b)
    await asyncio.gather(
        svc1.link_channel_identity(nav_user_id=user_a, auth_provider="telegram", provider_user_id=puid, auth_data={}),
        svc2.unlink_channel_identity("telegram", puid),
    )
    assert len(await _owners(svc1, puid)) <= 1

    # A failed replacement rolls back: user_a keeps ownership.
    await svc1.link_channel_identity(nav_user_id=user_a, auth_provider="telegram", provider_user_id=puid, auth_data={})
    failing = IdentityMappingService(_FailingUpsertPool(svc2._pool))
    with pytest.raises(RuntimeError):
        await failing.link_channel_identity(
            nav_user_id=user_b, auth_provider="telegram", provider_user_id=puid, auth_data={}
        )
    assert await _owners(svc1, puid) == [user_a]


@pytest.mark.asyncio
async def test_e2e_telegram_login_link_resolves(link_db) -> None:
    svc1, _svc2, user_a, _user_b, puid = link_db
    from asyncdb import AsyncPool

    resolver_pool = AsyncPool("pg", dsn=os.environ["IDENTITY_PG_DSN"])
    await resolver_pool.connect()
    try:
        await svc1.link_channel_identity(
            nav_user_id=user_a, auth_provider="telegram", provider_user_id=puid, auth_data={}
        )
        resolver = IdentityPrincipalResolver(resolver_pool)
        principal = await resolver.resolve("telegram", puid)
        assert principal is not None and str(principal.user_id) == user_a
        assert await svc1.unlink_channel_identity("telegram", puid) == 1
        assert await resolver.resolve("telegram", puid) is None
    finally:
        await resolver_pool.close()
