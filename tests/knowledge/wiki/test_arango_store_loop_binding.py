"""An ArangoDB connection may not outlive the event loop that opened it.

`asyncdb`'s ArangoDB driver is aiohttp-backed, and aiohttp binds its
connector to the loop that created it. A process that makes several
`asyncio.run(...)` calls — the CLI's `status`, which resolves each
federated plane in its own run — used to hand the second call the
connection cached during the first, whose loop had since closed. That
surfaced from deep inside the driver as `Event loop is closed`, with the
traceback pointing at `sources.py:_run_async` rather than at the real
cause.
"""

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore


class LoopBoundDB:
    """A driver double that behaves like aiohttp: usable only on its loop."""

    instances: ClassVar[list["LoopBoundDB"]] = []

    def __init__(self, *args, **kwargs):
        self.loop = None
        self.closed = False
        self.close_calls = 0
        LoopBoundDB.instances.append(self)

    async def connection(self):
        self.loop = asyncio.get_running_loop()
        return self

    def _check_loop(self):
        if self.loop is None:
            return
        if self.loop.is_closed() or asyncio.get_running_loop() is not self.loop:
            raise RuntimeError("Event loop is closed")

    async def query(self, *args, **kwargs):
        self._check_loop()
        return ([], None)

    async def execute(self, *args, **kwargs):
        self._check_loop()
        return ([], None)

    async def collection_exists(self, name):
        self._check_loop()
        return True

    async def create_collection(self, name, edge=False):
        self._check_loop()

    async def close(self):
        self.close_calls += 1
        self._check_loop()
        self.closed = True

    @property
    def _connection(self):
        conn = MagicMock()
        conn.views = AsyncMock(return_value=[{"name": "w_pages_view", "type": "arangosearch"}])
        conn.create_view = AsyncMock()
        return conn


@pytest.fixture
def store(monkeypatch):
    LoopBoundDB.instances.clear()
    monkeypatch.setattr("parrot.knowledge.wiki.arango_store.AsyncDB", LoopBoundDB)
    with patch.object(ArangoDBWikiStore, "_create_pages_view", new=AsyncMock()):
        yield ArangoDBWikiStore({"host": "h"}, database="wiki_t", wiki_name="t")


class TestConnectionOutlivesItsLoop:
    def test_second_asyncio_run_reconnects_instead_of_raising(self, store):
        """The reported crash: `Event loop is closed` on the second run."""

        async def one_op():
            await store._ensure_init()
            return await store._query("RETURN 1", {})

        assert asyncio.run(one_op()) == []
        # A brand-new loop, exactly as a second CLI `_run(...)` would be.
        assert asyncio.run(one_op()) == []

        assert len(LoopBoundDB.instances) == 2, "the dead connection must be replaced, not reused"

    def test_same_loop_reuses_one_connection(self, store):
        """Reconnecting is for dead loops only — not per call."""

        async def three_ops():
            await store._ensure_init()
            await store._query("RETURN 1", {})
            await store._query("RETURN 2", {})

        asyncio.run(three_ops())

        assert len(LoopBoundDB.instances) == 1

    def test_stale_connection_close_failure_is_swallowed(self, store):
        """Closing it drives the dead loop — that must not surface."""

        async def op():
            await store._ensure_init()
            return await store._query("RETURN 1", {})

        asyncio.run(op())
        dead = LoopBoundDB.instances[0]

        asyncio.run(op())  # would raise if _discard_connection propagated

        assert dead.close_calls == 1 and dead.closed is False

    def test_initialize_directly_also_reconnects(self, store):
        """The sources manager and the federation await initialize() by
        hand — they must get the same protection as _ensure_init callers."""

        asyncio.run(store.initialize())
        asyncio.run(store.initialize())

        assert len(LoopBoundDB.instances) == 2
        assert LoopBoundDB.instances[1].loop is store._loop, "the second connection owns the binding"

    def test_close_forgets_the_loop(self, store):
        async def op():
            await store._ensure_init()
            await store.close()

        asyncio.run(op())

        assert store._loop is None
        assert store._initialized is False
