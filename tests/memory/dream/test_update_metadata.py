"""Unit tests for AbstractEpisodeBackend.update_metadata() (TASK-1985).

Covers all three backend implementations (FAISS real; PgVector/Redis
mocked) plus the ``EpisodicMemoryStore.mark_consolidated()`` passthrough.
"""
import json
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Worktree environment gotcha (unrelated to TASK-1985): the repo-root
# conftest.py stubs the uncompiled `parrot.utils.types` Cython extension,
# but that stub is injected partway through conftest.py's own execution.
# If some earlier conftest import transitively imports
# `parrot.memory.episodic.backends.faiss` BEFORE the stub is in place, its
# module-level `import faiss` fails, gets caught, and
# `_FAISS_AVAILABLE = False` is cached in sys.modules for the rest of the
# session. By the time this test module loads, conftest.py has finished
# and the stub is present, so a forced fresh re-import here recovers the
# correct state without touching conftest.py.
sys.modules.pop("parrot.memory.episodic.backends.faiss", None)

from parrot.memory.episodic.backends.abstract import AbstractEpisodeBackend
from parrot.memory.episodic.backends.faiss import FAISSBackend
from parrot.memory.episodic.backends.pgvector import PgVectorBackend
from parrot.memory.episodic.backends.redis_vector import RedisVectorBackend
from parrot.memory.episodic.models import EpisodeOutcome, EpisodicMemory
from parrot.memory.episodic.store import EpisodicMemoryStore


def _make_episode(**overrides) -> EpisodicMemory:
    defaults = {
        "agent_id": "agent-1",
        "situation": "did a thing",
        "action_taken": "did it",
        "outcome": EpisodeOutcome.SUCCESS,
    }
    defaults.update(overrides)
    return EpisodicMemory(**defaults)


# ── FAISS (real) ──────────────────────────────────────────────────────


@pytest.fixture
def faiss_backend_with_episodes():
    backend = FAISSBackend(dimension=4, persistence_path=None)
    episodes = [_make_episode() for _ in range(3)]
    backend._episodes = {ep.episode_id: ep for ep in episodes}
    return backend, [ep.episode_id for ep in episodes]


class TestFAISSUpdateMetadata:
    async def test_patch_merged(self, faiss_backend_with_episodes):
        backend, ids = faiss_backend_with_episodes
        n = await backend.update_metadata(ids[:2], {"consolidated_into": "mem-x"})
        assert n == 2
        assert backend._episodes[ids[0]].metadata["consolidated_into"] == "mem-x"
        assert backend._episodes[ids[1]].metadata["consolidated_into"] == "mem-x"
        assert "consolidated_into" not in backend._episodes[ids[2]].metadata

    async def test_unknown_ids_ignored(self, faiss_backend_with_episodes):
        backend, _ = faiss_backend_with_episodes
        assert await backend.update_metadata(["nope"], {"k": "v"}) == 0

    async def test_empty_ids_returns_zero(self, faiss_backend_with_episodes):
        backend, _ = faiss_backend_with_episodes
        assert await backend.update_metadata([], {"k": "v"}) == 0

    async def test_survives_persistence(self, tmp_path):
        """Patch, save, reload — metadata still patched."""
        backend = FAISSBackend(dimension=4, persistence_path=str(tmp_path))
        ep = _make_episode()
        await backend.store(ep)

        n = await backend.update_metadata([ep.episode_id], {"consolidated_into": "mem-y"})
        assert n == 1

        reloaded = FAISSBackend(dimension=4, persistence_path=str(tmp_path))
        await reloaded.load()
        assert reloaded._episodes[ep.episode_id].metadata["consolidated_into"] == "mem-y"


# ── PgVector (mocked asyncpg) ─────────────────────────────────────────


class TestPgVectorUpdateMetadata:
    async def test_jsonb_merge_query_and_count(self):
        backend = PgVectorBackend(dsn="postgresql://fake")

        fake_conn = AsyncMock()
        fake_conn.execute.return_value = "UPDATE 2"

        fake_acquire_cm = MagicMock()
        fake_acquire_cm.__aenter__ = AsyncMock(return_value=fake_conn)
        fake_acquire_cm.__aexit__ = AsyncMock(return_value=False)

        fake_pool = MagicMock()
        fake_pool.acquire.return_value = fake_acquire_cm
        backend._pool = fake_pool

        count = await backend.update_metadata(
            ["11111111-1111-1111-1111-111111111111"], {"consolidated_into": "mem-z"}
        )

        assert count == 2
        args, _ = fake_conn.execute.call_args
        sql = args[0]
        assert "||" in sql and "jsonb" in sql.lower()
        assert json.loads(args[1]) == {"consolidated_into": "mem-z"}

    async def test_empty_ids_returns_zero(self):
        backend = PgVectorBackend(dsn="postgresql://fake")
        assert await backend.update_metadata([], {"k": "v"}) == 0


# ── Redis (mocked client) ─────────────────────────────────────────────


class TestRedisUpdateMetadata:
    async def test_metadata_rewritten_other_fields_untouched(self):
        backend = RedisVectorBackend()
        fake_redis = AsyncMock()
        fake_redis.hget.return_value = json.dumps({"existing": "value"}).encode()
        backend._redis = fake_redis

        n = await backend.update_metadata(["ep-1"], {"consolidated_into": "mem-w"})

        assert n == 1
        fake_redis.hset.assert_awaited_once()
        key, field, value = fake_redis.hset.call_args[0]
        assert key == "ep:ep-1"
        assert field == "metadata"
        merged = json.loads(value)
        assert merged == {"existing": "value", "consolidated_into": "mem-w"}

    async def test_unconfigured_backend_returns_zero(self):
        backend = RedisVectorBackend()
        assert await backend.update_metadata(["ep-1"], {"k": "v"}) == 0

    async def test_missing_episode_skipped(self):
        backend = RedisVectorBackend()
        fake_redis = AsyncMock()
        fake_redis.hget.return_value = None
        fake_redis.exists.return_value = False
        backend._redis = fake_redis

        n = await backend.update_metadata(["nope"], {"k": "v"})
        assert n == 0


# ── Protocol conformance ───────────────────────────────────────────────


def test_backends_still_satisfy_protocol():
    faiss_backend = FAISSBackend(dimension=4)
    pg_backend = PgVectorBackend(dsn="postgresql://fake")
    redis_backend = RedisVectorBackend()

    assert isinstance(faiss_backend, AbstractEpisodeBackend)
    assert isinstance(pg_backend, AbstractEpisodeBackend)
    assert isinstance(redis_backend, AbstractEpisodeBackend)


# ── EpisodicMemoryStore.mark_consolidated ──────────────────────────────


class TestStoreMarkConsolidated:
    async def test_passthrough(self):
        backend = FAISSBackend(dimension=4)
        ep = _make_episode()
        await backend.store(ep)
        store = EpisodicMemoryStore(backend=backend)

        n = await store.mark_consolidated([ep.episode_id], "mem-abc")

        assert n == 1
        assert backend._episodes[ep.episode_id].metadata["consolidated_into"] == "mem-abc"

    async def test_backend_without_method(self):
        """Backend lacking update_metadata -> returns 0, logs WARNING."""

        class BareBackend:
            async def store(self, episode):
                return episode.episode_id

            async def search_similar(self, *a, **kw):
                return []

            async def get_recent(self, *a, **kw):
                return []

            async def get_failures(self, *a, **kw):
                return []

            async def delete_expired(self):
                return 0

            async def count(self, *a, **kw):
                return 0

        store = EpisodicMemoryStore(backend=BareBackend())
        n = await store.mark_consolidated(["ep-1"], "mem-abc")
        assert n == 0
