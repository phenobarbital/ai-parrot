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
from parrot.memory.episodic.models import EpisodicMemory, MemoryNamespace


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
            backend.apply_review


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
