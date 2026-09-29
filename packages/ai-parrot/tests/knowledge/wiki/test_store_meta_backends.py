"""FEAT-609 Q2: get_meta/set_meta on the server-hosted backends (mocked I/O)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.knowledge.wiki.arango_store import META_COLLECTION, ArangoDBWikiStore
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore


def _pg_store(wiki_name: str) -> tuple[PostgresWikiStore, MagicMock]:
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value="stored")
    conn.execute = AsyncMock()
    acquire = MagicMock()
    acquire.__aenter__ = AsyncMock(return_value=conn)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire)
    store = PostgresWikiStore("postgresql://unused", wiki_name=wiki_name, schema="s")
    store._pool = pool  # bypass ensure_schema: no live DB in this test
    return store, conn


async def test_postgres_meta_keys_are_wiki_scoped() -> None:
    store, conn = _pg_store("a")
    assert await store.get_meta("extractor_fingerprint") == "stored"
    assert conn.fetchval.await_args.args[1] == "wiki:a:extractor_fingerprint"
    await store.set_meta("extractor_fingerprint", "v")
    assert conn.execute.await_args.args[1:] == ("wiki:a:extractor_fingerprint", "v")
    assert "s.meta" in conn.execute.await_args.args[0]


async def test_postgres_get_meta_absent_is_none() -> None:
    store, conn = _pg_store("a")
    conn.fetchval = AsyncMock(return_value=None)
    assert await store.get_meta("k") is None


async def test_postgres_two_wikis_do_not_collide() -> None:
    store_a, conn_a = _pg_store("a")
    store_b, conn_b = _pg_store("b")
    await store_a.set_meta("k", "1")
    await store_b.set_meta("k", "2")
    assert conn_a.execute.await_args.args[1] != conn_b.execute.await_args.args[1]


def _arango(read_only: bool = False) -> tuple[ArangoDBWikiStore, MagicMock]:
    db = MagicMock()
    db.query = AsyncMock(return_value=(["fp"], None))
    db.execute = AsyncMock(return_value=([], None))
    store = ArangoDBWikiStore({"host": "x"}, wiki_name="w", read_only=read_only)
    store._db = db
    store._initialized = True
    store._loop = __import__("asyncio").get_running_loop()
    return store, db


async def test_arango_meta_upsert_and_read() -> None:
    store, db = _arango()
    await store.set_meta("extractor_fingerprint", "v")
    aql, kwargs = db.execute.await_args.args[0], db.execute.await_args.kwargs
    assert "UPSERT" in aql
    assert kwargs["bind_vars"] == {"@collection": META_COLLECTION, "key": "extractor_fingerprint", "value": "v"}
    assert await store.get_meta("extractor_fingerprint") == "fp"
    db.query = AsyncMock(return_value=([], None))
    assert await store.get_meta("missing") is None


async def test_arango_meta_read_only_refuses() -> None:
    store, db = _arango(read_only=True)
    with pytest.raises(PermissionError):
        await store.set_meta("k", "v")
    db.execute.assert_not_awaited()
    assert await store.get_meta("k") == "fp"
