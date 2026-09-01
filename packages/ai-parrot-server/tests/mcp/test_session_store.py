"""Unit tests for the Redis-backed shared session + event store
(FEAT-477, TASK-2609).
"""
import pytest
from aiohttp.test_utils import make_mocked_request
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.session_store import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionStoreUnavailable,
)
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer


class _FakeRedis:
    """Minimal in-memory Redis double supporting this store's operations."""

    def __init__(self):
        self._strings: dict[str, str] = {}
        self._lists: dict[str, list[str]] = {}
        self._expire_at: dict[str, float] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._strings[key] = value
        self._expire_at[key] = ttl

    async def get(self, key: str) -> "str | None":
        return self._strings.get(key)

    async def delete(self, key: str) -> None:
        self._strings.pop(key, None)
        self._lists.pop(key, None)
        self._expire_at.pop(key, None)

    async def incr(self, key: str) -> int:
        current = int(self._strings.get(key, "0"))
        current += 1
        self._strings[key] = str(current)
        return current

    async def rpush(self, key: str, value: str) -> int:
        self._lists.setdefault(key, []).append(value)
        return len(self._lists[key])

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        values = self._lists.get(key, [])
        if end == -1:
            return values[start:]
        return values[start : end + 1]

    async def ltrim(self, key: str, start: int, end: int) -> None:
        values = self._lists.get(key, [])
        if not values:
            return
        if end == -1:
            self._lists[key] = values[start:]
        else:
            self._lists[key] = values[start : end + 1]

    async def expire(self, key: str, ttl: int) -> None:
        self._expire_at[key] = ttl


class _BrokenRedis:
    """A Redis double whose every operation raises."""

    async def _boom(self, *_args, **_kwargs):
        raise ConnectionError("redis unavailable")

    def __getattr__(self, item):
        return self._boom


@pytest.fixture
def shared_backend():
    """One fake Redis instance shared by two independent store 'clients' —
    simulating two gunicorn workers talking to the same Redis.
    """
    return _FakeRedis()


@pytest.fixture
def redis_store_a(shared_backend):
    return RedisSessionStore(shared_backend, ttl=3600, max_events=1000)


@pytest.fixture
def redis_store_b(shared_backend):
    return RedisSessionStore(shared_backend, ttl=3600, max_events=1000)


@pytest.fixture
def broken_redis_store():
    return RedisSessionStore(_BrokenRedis(), ttl=3600, max_events=1000)


@pytest.fixture
def cfg():
    return MCPServerConfig(session_ttl=1800, event_buffer_size=500)


class TestSessionStore:
    async def test_session_resolves_across_workers(self, redis_store_a, redis_store_b):
        sid = await redis_store_a.create_session(user={"user_id": "u1"})
        record = await redis_store_b.get_session(sid)
        assert record is not None
        assert record.principal == {"user_id": "u1"}

    async def test_event_replay_across_workers(self, redis_store_a, redis_store_b):
        sid = await redis_store_a.create_session(user={})
        await redis_store_a.append_event(sid, "server", {"n": 1})
        await redis_store_a.append_event(sid, "server", {"n": 2})
        events = await redis_store_b.events_after(sid, "server", 0)
        assert len(events) == 2
        assert [e.message["n"] for e in events] == [1, 2]

    async def test_events_after_filters_by_sequence(self, redis_store_a):
        sid = await redis_store_a.create_session(user={})
        await redis_store_a.append_event(sid, "server", {"n": 1})
        await redis_store_a.append_event(sid, "server", {"n": 2})
        events = await redis_store_a.events_after(sid, "server", 1)
        assert len(events) == 1 and events[0].message["n"] == 2

    async def test_store_unavailable_fails_cleanly(self, broken_redis_store):
        with pytest.raises(SessionStoreUnavailable):
            await broken_redis_store.get_session("s1")

    async def test_no_silent_local_fallback(self, broken_redis_store):
        with pytest.raises(SessionStoreUnavailable):
            await broken_redis_store.create_session(user={})
        assert not getattr(broken_redis_store, "_local_sessions", None)

    async def test_survives_worker_recycle(self, redis_store_a, shared_backend):
        sid = await redis_store_a.create_session(user={})
        # Simulate a worker recycle: drop the old client, build a fresh one
        # against the same backing Redis.
        fresh_store_client = RedisSessionStore(shared_backend, ttl=3600, max_events=1000)
        assert await fresh_store_client.get_session(sid) is not None

    async def test_ttl_and_buffer_size_honoured(self, shared_backend, cfg):
        store = RedisSessionStore(
            shared_backend, ttl=cfg.session_ttl, max_events=cfg.event_buffer_size
        )
        assert store.ttl == cfg.session_ttl
        assert store.max_events == cfg.event_buffer_size

    async def test_event_ring_bounded_by_max_events(self, shared_backend):
        store = RedisSessionStore(shared_backend, ttl=3600, max_events=3)
        sid = await store.create_session(user={})
        for i in range(10):
            await store.append_event(sid, "server", {"n": i})
        events = await store.events_after(sid, "server", -1)
        assert len(events) == 3
        assert [e.message["n"] for e in events] == [7, 8, 9]

    async def test_delete_session_removes_events(self, redis_store_a):
        sid = await redis_store_a.create_session(user={})
        await redis_store_a.append_event(sid, "server", {"n": 1})
        await redis_store_a.delete_session(sid)
        assert await redis_store_a.get_session(sid) is None


class TestInMemorySessionStore:
    """The explicit in-process choice must implement the same interface."""

    async def test_create_and_get(self):
        store = InMemorySessionStore(ttl=3600, max_events=1000)
        sid = await store.create_session(user={"user_id": "u1"})
        record = await store.get_session(sid)
        assert record is not None and record.principal == {"user_id": "u1"}

    async def test_append_and_replay(self):
        store = InMemorySessionStore(ttl=3600, max_events=1000)
        sid = await store.create_session(user={})
        await store.append_event(sid, "server", {"n": 1})
        await store.append_event(sid, "server", {"n": 2})
        events = await store.events_after(sid, "server", 0)
        assert len(events) == 2

    async def test_pre_generated_session_id_is_honoured(self):
        store = InMemorySessionStore(ttl=3600, max_events=1000)
        sid = await store.create_session(user={}, session_id="fixed-id")
        assert sid == "fixed-id"
        assert (await store.get_session("fixed-id")) is not None


class TestCrossWorkerServerSimulation:
    """Two independent `StreamableHttpMCPServer` instances (simulating two
    gunicorn workers) sharing one `RedisSessionStore` backend.
    """

    async def test_session_created_on_worker_a_resolves_on_worker_b(self, shared_backend):
        cfg = MCPServerConfig(name="worker")
        server_a = StreamableHttpMCPServer(
            cfg, session_store=RedisSessionStore(shared_backend, ttl=3600, max_events=1000)
        )
        server_b = StreamableHttpMCPServer(
            cfg, session_store=RedisSessionStore(shared_backend, ttl=3600, max_events=1000)
        )
        request = make_mocked_request("GET", "/mcp")

        session = await server_a._create_session(protocol_version="2025-03-26")
        assert session.session_id not in server_b._sessions

        adopted = await server_b._get_session(session.session_id, request)
        assert adopted is not None
        assert adopted.session_id == session.session_id
        assert session.session_id in server_b._sessions

    async def test_event_replay_resolves_on_worker_b(self, shared_backend):
        cfg = MCPServerConfig(name="worker")
        server_a = StreamableHttpMCPServer(
            cfg, session_store=RedisSessionStore(shared_backend, ttl=3600, max_events=1000)
        )
        server_b = StreamableHttpMCPServer(
            cfg, session_store=RedisSessionStore(shared_backend, ttl=3600, max_events=1000)
        )
        request = make_mocked_request("GET", "/mcp")

        session = await server_a._create_session(protocol_version="2025-03-26")
        buffer = session.open_stream(1000, stream_id="server", max_streams=64)
        buffer.append({"jsonrpc": "2.0", "result": {"n": 1}})
        await server_a._mirror_event(session.session_id, "server", {"jsonrpc": "2.0", "result": {"n": 1}})

        # Worker B never saw the session or the stream locally.
        events = await server_b._session_store.events_after(session.session_id, "server", 0)
        assert len(events) == 1
        adopted = await server_b._get_session(session.session_id, request)
        assert adopted is not None
        assert "server" not in adopted.streams  # not yet rehydrated

    async def test_default_store_is_in_memory_and_isolated_per_instance(self):
        """G11 — default construction is unchanged: two servers with no
        explicit store do NOT share sessions.
        """
        cfg = MCPServerConfig(name="worker")
        server_a = StreamableHttpMCPServer(cfg)
        server_b = StreamableHttpMCPServer(cfg)
        assert isinstance(server_a._session_store, InMemorySessionStore)
        request = make_mocked_request("GET", "/mcp")

        session = await server_a._create_session(protocol_version="2025-03-26")
        assert await server_b._get_session(session.session_id, request) is None
