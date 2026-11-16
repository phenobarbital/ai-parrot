"""Behavioral acceptance tests for episodic backend scope propagation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from parrot.memory.dynamics.review_log import ReviewBackend
from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.backends.pgvector import PgVectorBackend
from parrot.memory.episodic.backends.redis_vector import (
    RedisVectorBackend,
    _episode_to_hash,
    _hash_to_episode,
)
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.recall import HybridBM25Strategy, _BM25IndexEntry


def _episode(**overrides: Any) -> EpisodicMemory:
    """Build a deterministic two-dimensional episode."""
    values: dict[str, Any] = {
        "episode_id": "00000000-0000-0000-0000-000000000001",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "tenant_id": "tenant-a",
        "agent_id": "agent-a",
        "model_id": "provider:model-a",
        "user_id": "user-a",
        "session_id": "session-a",
        "room_id": "room-a",
        "crew_id": "crew-a",
        "situation": "first content",
        "action_taken": "first action",
        "outcome": "success",
        "embedding": [0.8, 0.6],
    }
    values.update(overrides)
    return EpisodicMemory(**values)


class _Acquire:
    """Async context manager returned by the fake PostgreSQL pool."""

    def __init__(self, connection: _PgConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _PgConnection:
        return self._connection

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _PgConnection:
    """Record PostgreSQL operations while modeling primary-key write-once behavior."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.last_fetch: tuple[str, tuple[Any, ...]] | None = None
        self.inserted: dict[str, tuple[Any, ...]] = {}

    async def execute(self, query: str, *args: Any) -> str:
        self.statements.append(query)
        if "INSERT INTO" in query and args:
            self.inserted.setdefault(str(args[0]), args)
            return "INSERT 0 1"
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.last_fetch = (query, args)
        return []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.last_fetch = (query, args)
        return None


class _PgPool:
    """Minimal asyncpg pool double for isolated backend contract tests."""

    def __init__(self) -> None:
        self.connection = _PgConnection()

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)

    async def close(self) -> None:
        return None


class _SearchRedis:
    """Capture RediSearch commands without requiring a shared Redis service."""

    def __init__(self, response: list[Any] | None = None, hash_data: dict[str, Any] | None = None) -> None:
        self.commands: list[tuple[Any, ...]] = []
        self._response = response or [0]
        self._hash_data = hash_data or {}

    async def execute_command(self, *args: Any) -> list[Any]:
        self.commands.append(args)
        return self._response

    async def hgetall(self, key: str) -> dict[str, Any]:
        return self._hash_data


class _MemoryRedis:
    """In-memory Redis HASH subset with HSETNX reservation semantics."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, Any]] = {}

    async def hsetnx(self, key: str, field: str, value: Any) -> int:
        if key in self.hashes:
            return 0
        self.hashes[key] = {field: value}
        return 1

    async def hset(self, key: str, mapping: dict[str, Any]) -> int:
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, Any]:
        return self.hashes.get(key, {})


@pytest.mark.asyncio
async def test_backend_filters_before_limits() -> None:
    """Verify all optional dimensions are applied before backend limits."""
    namespace = MemoryNamespace(
        tenant_id="tenant-a",
        agent_id="agent-a",
        model_id="provider:model-a",
        user_id="user-a",
        session_id="session-a",
        room_id="room-a",
        crew_id="crew-a",
    )
    namespace_filter = namespace.build_filter()

    faiss_backend = FAISSBackend(dimension=2)
    dimensions = ("tenant_id", "agent_id", "model_id", "user_id", "session_id", "room_id", "crew_id")
    for index in range(14):
        field = dimensions[index % len(dimensions)]
        await faiss_backend.store(
            _episode(
                episode_id=f"00000000-0000-0000-0000-{index + 2:012d}",
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(seconds=index),
                embedding=[1.0, 0.0],
                **{field: f"other-{index}"},
            )
        )
    target = _episode()
    await faiss_backend.store(target)

    similar = await faiss_backend.search_similar(
        [1.0, 0.0],
        namespace_filter,
        top_k=1,
        score_threshold=0.0,
    )
    recent = await faiss_backend.get_recent(namespace_filter, limit=1)

    assert [episode.episode_id for episode in similar] == [target.episode_id]
    assert [episode.episode_id for episode in recent] == [target.episode_id]

    pg_pool = _PgPool()
    pg_backend = PgVectorBackend("postgresql://unused")
    pg_backend._pool = pg_pool
    await pg_backend.search_similar([1.0, 0.0], namespace_filter, top_k=1, score_threshold=0.0)
    assert pg_pool.connection.last_fetch is not None
    pg_query = pg_pool.connection.last_fetch[0]
    for field in namespace_filter:
        assert f"{field} =" in pg_query
        assert pg_query.index(f"{field} =") < pg_query.index("LIMIT")

    search_redis = _SearchRedis()
    redis_backend = RedisVectorBackend(embedding_dim=2)
    redis_backend._redis = search_redis
    await redis_backend.search_similar([1.0, 0.0], namespace_filter, top_k=1, score_threshold=0.0)
    redis_query = str(search_redis.commands[0][2])
    for field in namespace_filter:
        assert f"@{field}:" in redis_query
    assert r"provider\:model\-a" in redis_query


def test_build_filter_emits_unset_only_dimensions() -> None:
    """Verify a named unset dimension is matched as unset instead of being left unconstrained."""
    namespace = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a", room_id="room-a")

    assert namespace.build_filter() == {"tenant_id": "tenant-a", "agent_id": "agent-a", "room_id": "room-a"}
    assert namespace.build_filter(null_dimensions=("user_id", "session_id")) == {
        "tenant_id": "tenant-a",
        "agent_id": "agent-a",
        "room_id": "room-a",
        "user_id": None,
        "session_id": None,
    }
    with pytest.raises(ValueError, match="room_id"):
        namespace.build_filter(null_dimensions=("room_id",))
    with pytest.raises(ValueError, match="tenant_id"):
        namespace.build_filter(null_dimensions=("tenant_id",))


@pytest.mark.asyncio
async def test_unset_only_filter_is_applied_before_limits(tmp_path: Path) -> None:
    """Verify every backend matches an unset-only dimension before its limit, or returns no rows."""
    namespace_filter = MemoryNamespace(tenant_id="tenant-a", agent_id="agent-a").build_filter(
        null_dimensions=("user_id", "session_id")
    )
    shared = {"model_id": None, "room_id": None, "crew_id": None, "embedding": [1.0, 0.0]}
    agent_level = _episode(user_id=None, session_id=None, **shared)
    others = [
        _episode(
            episode_id=f"00000000-0000-0000-0000-{index + 2:012d}",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(seconds=index),
            **dimensions,
            **shared,
        )
        for index, dimensions in enumerate(
            (
                {"user_id": "user-a", "session_id": "session-a"},
                {"user_id": None, "session_id": "session-anonymous"},
                {"user_id": "user-b", "session_id": None},
            )
        )
    ]

    faiss_backend = FAISSBackend(dimension=2)
    sqlite_backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await sqlite_backend.configure()
    try:
        for backend in (faiss_backend, sqlite_backend):
            for episode in (*others, agent_level):
                await backend.store(episode)
            similar = await backend.search_similar([1.0, 0.0], namespace_filter, top_k=1, score_threshold=0.0)
            recent = await backend.get_recent(namespace_filter, limit=1)
            assert [episode.episode_id for episode in similar] == [agent_level.episode_id]
            assert [episode.episode_id for episode in recent] == [agent_level.episode_id]
            assert await backend.count(namespace_filter) == 1
    finally:
        await sqlite_backend.close()

    pg_pool = _PgPool()
    pg_backend = PgVectorBackend("postgresql://unused")
    pg_backend._pool = pg_pool
    pg_calls = (
        pg_backend.search_similar([1.0, 0.0], namespace_filter, top_k=1, score_threshold=0.0),
        pg_backend.get_recent(namespace_filter, limit=1),
        pg_backend.count(namespace_filter),
        pg_backend.search_hybrid([1.0, 0.0], "rollout", namespace_filter, top_k=1, score_threshold=0.0),
    )
    for call in pg_calls:
        await call
        assert pg_pool.connection.last_fetch is not None
        pg_query, pg_args = pg_pool.connection.last_fetch
        assert "user_id IS NULL" in pg_query
        assert "session_id IS NULL" in pg_query
        assert "user_id =" not in pg_query
        assert None not in pg_args
        if "LIMIT" in pg_query:
            assert pg_query.index("session_id IS NULL") < pg_query.index("LIMIT")

    search_redis = _SearchRedis(response=[1, b"ep:other", []], hash_data=_episode_to_hash(others[0]))
    redis_backend = RedisVectorBackend(embedding_dim=2)
    redis_backend._redis = search_redis
    assert await redis_backend.search_similar([1.0, 0.0], namespace_filter, top_k=1, score_threshold=0.0) == []
    assert await redis_backend.get_recent(namespace_filter, limit=1) == []
    assert await redis_backend.count(namespace_filter) == 0
    assert search_redis.commands == []


def test_hybrid_index_key_separates_unset_from_the_text_none() -> None:
    """Verify an unset-only filter never shares a lexical index with a value spelled ``None``."""
    strategy = HybridBM25Strategy()
    base = {"tenant_id": "tenant-a", "agent_id": "agent-a"}

    assert strategy._namespace_key({**base, "user_id": None}) != strategy._namespace_key({**base, "user_id": "None"})


def test_hybrid_invalidation_reaches_wider_indexes_of_the_same_agent() -> None:
    """Verify a write under (user, session) drops the user-wide and agent-level indexes, not other agents'."""
    strategy = HybridBM25Strategy()
    base = {"tenant_id": "tenant-a", "agent_id": "agent-a"}
    filters = {
        "user_wide": {**base, "user_id": "user-a"},
        "agent_level": {**base, "user_id": None, "session_id": None},
        "other_agent": {"tenant_id": "tenant-a", "agent_id": "agent-b"},
    }
    for namespace_filter in filters.values():
        entry = _BM25IndexEntry(index=None, texts=[], episodes=[], built_at=0.0)
        entry.namespace_filter = dict(namespace_filter)
        strategy._cache[strategy._namespace_key(namespace_filter)] = entry

    strategy.invalidate({**base, "user_id": "user-a", "session_id": "session-a"})

    assert list(strategy._cache) == [strategy._namespace_key(filters["other_agent"])]


@pytest.mark.asyncio
async def test_legacy_data_survives_optional_dimension(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify additive migrations and model-less snapshots remain readable."""
    legacy = _episode(model_id=None)
    serialized = legacy.to_dict()
    serialized.pop("model_id")
    (tmp_path / "episodes.jsonl").write_text(f"{json.dumps(serialized)}\n", encoding="utf-8")

    faiss_backend = FAISSBackend(dimension=2, persistence_path=str(tmp_path))
    await faiss_backend.load()
    unfiltered = await faiss_backend.get_recent({"tenant_id": "tenant-a", "agent_id": "agent-a"})
    model_filtered = await faiss_backend.get_recent(
        {"tenant_id": "tenant-a", "agent_id": "agent-a", "model_id": "provider:model-a"}
    )
    assert [episode.model_id for episode in unfiltered] == [None]
    assert model_filtered == []

    legacy_hash = _episode_to_hash(legacy)
    legacy_hash.pop("model_id")
    search_redis = _SearchRedis(response=[1, b"ep:legacy", []], hash_data=legacy_hash)
    redis_backend = RedisVectorBackend(embedding_dim=2)
    redis_backend._redis = search_redis
    redis_episodes = await redis_backend.get_recent({"tenant_id": "tenant-a", "agent_id": "agent-a"})
    assert [episode.model_id for episode in redis_episodes] == [None]

    pg_pool = _PgPool()

    async def create_pool(**kwargs: Any) -> _PgPool:
        assert kwargs["dsn"] == "postgresql://unused"
        return pg_pool

    monkeypatch.setattr("parrot.memory.episodic.backends.pgvector.asyncpg.create_pool", create_pool)
    pg_backend = PgVectorBackend("postgresql://unused")
    await pg_backend.configure()
    ddl = "\n".join(pg_pool.connection.statements)
    assert "ADD COLUMN IF NOT EXISTS model_id TEXT" in ddl
    assert "SET model_id" not in ddl


def test_unsupported_reviews_fail_visible() -> None:
    """Verify baseline backends never advertise transactional review support."""
    backends: tuple[AbstractEpisodeBackend, ...] = (
        PgVectorBackend("postgresql://unused"),
        RedisVectorBackend(),
        FAISSBackend(dimension=2),
    )

    for backend in backends:
        assert isinstance(backend, AbstractEpisodeBackend)
        assert not isinstance(backend, ReviewBackend)
        with pytest.raises(AttributeError):
            getattr(backend, "apply_review")  # noqa: B009 — the attribute access itself is the assertion


@pytest.mark.asyncio
async def test_second_store_of_same_episode_id_keeps_first_content(tmp_path: Path) -> None:
    """Verify PostgreSQL, Redis and FAISS retain first-written content."""
    first = _episode()
    replacement = _episode(
        situation="replacement content",
        action_taken="replacement action",
        embedding=[1.0, 0.0],
    )

    faiss_backend = FAISSBackend(dimension=2, persistence_path=str(tmp_path))
    await faiss_backend.store(first)
    await faiss_backend.store(replacement)
    await faiss_backend.save()
    reloaded_faiss = FAISSBackend(dimension=2, persistence_path=str(tmp_path))
    await reloaded_faiss.load()
    faiss_stored = await reloaded_faiss.get_recent({"tenant_id": "tenant-a", "agent_id": "agent-a"})
    assert faiss_stored[0].situation == "first content"

    memory_redis = _MemoryRedis()
    redis_backend = RedisVectorBackend(embedding_dim=2)
    redis_backend._redis = memory_redis
    await redis_backend.store(first)
    await redis_backend.store(replacement)
    redis_stored = _hash_to_episode(await memory_redis.hgetall(f"ep:{first.episode_id}"))
    assert redis_stored.situation == "first content"

    pg_pool = _PgPool()
    pg_backend = PgVectorBackend("postgresql://unused")
    pg_backend._pool = pg_pool
    await pg_backend.store(first)
    await pg_backend.store(replacement)
    pg_stored = pg_pool.connection.inserted[first.episode_id]
    assert pg_stored[11] == "first content"
    insert_sql = next(statement for statement in pg_pool.connection.statements if "INSERT INTO" in statement)
    assert "ON CONFLICT (episode_id) DO NOTHING" in insert_sql


@pytest.mark.skip(reason="Requires an isolated PostgreSQL+pgvector service; SQL contract is covered above")
def test_pgvector_live_migration_and_write_once_disclosed() -> None:
    """Disclose unavailable external PostgreSQL persistence coverage."""


@pytest.mark.skip(reason="Requires an isolated Redis Stack service; HASH contract is covered above")
def test_redis_live_index_migration_and_write_once_disclosed() -> None:
    """Disclose unavailable external Redis persistence coverage."""
