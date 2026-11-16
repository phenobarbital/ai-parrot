"""Behavioral acceptance tests for scoped episodic recall and cache invalidation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.dynamics.models import ReviewSignal
from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.cache import EpisodeRedisCache
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, EpisodicMemory, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore


class _Pipeline:
    """Small async Redis pipeline used by the isolated cache acceptance test."""

    def __init__(self, redis: "_Redis") -> None:
        self._redis = redis
        self._commands: list[tuple[str, tuple[Any, ...]]] = []

    def set(self, key: str, value: str) -> "_Pipeline":
        """Queue a string write."""
        self._commands.append(("set", (key, value)))
        return self

    def expire(self, key: str, ttl: int) -> "_Pipeline":
        """Queue a no-op expiry."""
        self._commands.append(("expire", (key, ttl)))
        return self

    def zadd(self, key: str, values: dict[str, float]) -> "_Pipeline":
        """Queue a sorted-set update."""
        self._commands.append(("zadd", (key, values)))
        return self

    def zremrangebyrank(self, key: str, start: int, stop: int) -> "_Pipeline":
        """Queue a sorted-set trim."""
        self._commands.append(("zremrangebyrank", (key, start, stop)))
        return self

    def lpush(self, key: str, value: str) -> "_Pipeline":
        """Queue a list prepend."""
        self._commands.append(("lpush", (key, value)))
        return self

    def ltrim(self, key: str, start: int, stop: int) -> "_Pipeline":
        """Queue a list trim."""
        self._commands.append(("ltrim", (key, start, stop)))
        return self

    def get(self, key: str) -> "_Pipeline":
        """Queue a string lookup."""
        self._commands.append(("get", (key,)))
        return self

    async def execute(self) -> list[Any]:
        """Apply queued commands in order."""
        results: list[Any] = []
        for name, arguments in self._commands:
            results.append(await getattr(self._redis, name)(*arguments))
        return results


class _Redis:
    """Minimal in-memory async Redis implementation for cache behavior."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._zsets: dict[str, dict[str, float]] = {}
        self._lists: dict[str, list[str]] = {}

    def pipeline(self) -> _Pipeline:
        """Create a command pipeline."""
        return _Pipeline(self)

    async def set(self, key: str, value: str) -> None:
        """Store one string value."""
        self._data[key] = value

    async def expire(self, key: str, ttl: int) -> None:
        """Accept expiry calls without clock behavior."""

    async def get(self, key: str) -> str | None:
        """Return one stored string value."""
        return self._data.get(key)

    async def zadd(self, key: str, values: dict[str, float]) -> None:
        """Add sorted-set members."""
        self._zsets.setdefault(key, {}).update(values)

    async def zremrangebyrank(self, key: str, start: int, stop: int) -> None:
        """Trim sorted-set members by ascending rank."""
        values = sorted(self._zsets.get(key, {}).items(), key=lambda item: item[1])
        if stop < 0:
            stop = len(values) + stop
        for member, _ in values[start : stop + 1]:
            self._zsets[key].pop(member, None)

    async def zrevrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return sorted-set members by descending score."""
        values = sorted(self._zsets.get(key, {}).items(), key=lambda item: item[1], reverse=True)
        end = len(values) if stop < 0 else stop + 1
        return [member for member, _ in values[start:end]]

    async def zrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return sorted-set members by ascending score."""
        values = sorted(self._zsets.get(key, {}).items(), key=lambda item: item[1])
        end = len(values) if stop < 0 else stop + 1
        return [member for member, _ in values[start:end]]

    async def lpush(self, key: str, value: str) -> None:
        """Prepend one list member."""
        self._lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        """Trim a list by range."""
        self._lists[key] = self._lists.get(key, [])[start : stop + 1]

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        """Return list members by range."""
        values = self._lists.get(key, [])
        end = len(values) if stop < 0 else stop + 1
        return values[start:end]

    async def delete(self, *keys: str) -> None:
        """Delete each Redis data structure for the supplied keys."""
        for key in keys:
            self._data.pop(key, None)
            self._zsets.pop(key, None)
            self._lists.pop(key, None)


def _namespace(*, session_id: str = "session-a", user_id: str = "user-a") -> MemoryNamespace:
    """Build a fully scoped episodic namespace."""
    return MemoryNamespace(
        tenant_id="tenant-a",
        agent_id="agent-a",
        user_id=user_id,
        session_id=session_id,
        room_id="room-a",
        crew_id="crew-a",
        model_id="provider:model-a",
    )


def _episode(
    episode_id: str,
    namespace: MemoryNamespace,
    *,
    category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION,
    importance: int = 5,
    outcome: EpisodeOutcome = EpisodeOutcome.SUCCESS,
    created_at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc),
) -> EpisodicMemory:
    """Create a deterministic scoped episode."""
    return EpisodicMemory(
        episode_id=episode_id,
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=namespace.user_id,
        session_id=namespace.session_id,
        room_id=namespace.room_id,
        crew_id=namespace.crew_id,
        model_id=namespace.model_id,
        situation=f"Deployment lesson for {episode_id}",
        action_taken="Validated deployment",
        outcome=outcome,
        category=category,
        importance=importance,
        is_failure=outcome == EpisodeOutcome.FAILURE,
        lesson_learned=f"Use lesson {episode_id}",
        created_at=created_at,
    )


def _scope(namespace: MemoryNamespace) -> MemoryRequestScope:
    """Build matching trusted review scope."""
    return MemoryRequestScope(
        tenant_id=namespace.tenant_id,
        agent_id=namespace.agent_id,
        user_id=namespace.user_id,
        session_id=namespace.session_id,
        room_id=namespace.room_id,
        crew_id=namespace.crew_id,
        model_id=namespace.model_id,
        turn_id="turn-a",
        identity_provenance="runtime_derived",
    )


@pytest.mark.asyncio
async def test_cache_full_scope_and_invalidation(tmp_path: Path) -> None:
    """Keep cache identities scoped and invalidate after a committed review."""
    redis = _Redis()
    cache = EpisodeRedisCache(redis)
    namespace = _namespace()
    other_session = _namespace(session_id="session-b")
    episode = _episode("episode-a", namespace)

    await cache.cache_episode(namespace, episode)
    assert cache._key(namespace) != cache._key(other_session)
    assert await cache.get_recent(other_session) is None

    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    store = EpisodicMemoryStore(backend, redis_cache=cache, default_ttl_days=0)
    try:
        recorded = await store.record_episode(
            namespace,
            "Deploy the release",
            "Ran deployment",
            EpisodeOutcome.SUCCESS,
            generate_reflection=False,
        )
        assert await cache.get_recent(namespace) is not None
        await store.cite([recorded.episode_id], namespace=namespace, exposure_id="exposure-a")
        receipts = await store.review(
            [recorded.episode_id],
            ReviewSignal(
                outcome_id="outcome-a",
                outcome_revision=0,
                observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                scope=_scope(namespace),
                evidence_ref="coder-review/v1/execution-a/task-a/attempt-a",
                source="coder_engine",
                outcome="success",
                first_attempt=True,
                correction_count=0,
                passed_check_ids=("check-a",),
            ),
            namespace=namespace,
            exposure_id="exposure-a",
        )
        assert [receipt.status for receipt in receipts] == ["applied"]
        assert await cache.get_recent(namespace) is None
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_ranking_consistent_across_routes(tmp_path: Path) -> None:
    """Apply the shared importance-aware policy before route-specific formatting."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    namespace = _namespace()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("failure-low", namespace, importance=3, outcome=EpisodeOutcome.FAILURE))
        await backend.store(_episode("failure-high", namespace, importance=9, outcome=EpisodeOutcome.FAILURE))
        await backend.store(
            _episode("preference-low", namespace, category=EpisodeCategory.USER_PREFERENCE, importance=2)
        )
        await backend.store(
            _episode("preference-high", namespace, category=EpisodeCategory.USER_PREFERENCE, importance=8)
        )

        room = await store.get_room_context(namespace, limit=4)
        preferences = await store.get_user_preferences(namespace, limit=2)
        warnings = await store.get_failure_warnings(namespace, current_query="deployment", max_warnings=2)

        assert [episode.episode_id for episode in room] == [
            "failure-high",
            "preference-high",
            "failure-low",
            "preference-low",
        ]
        assert [episode.episode_id for episode in preferences] == ["preference-high", "preference-low"]
        assert warnings.index("failure-high") < warnings.index("failure-low")
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_offline_fallback_no_embedding_provider(tmp_path: Path) -> None:
    """Use scoped local lexical recall without configuring an embedding provider."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    namespace = _namespace()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    try:
        await backend.store(_episode("deployment-match", namespace, importance=7))
        await backend.store(_episode("other-session", _namespace(session_id="session-b"), importance=10))

        results = await store.recall_similar("deployment", namespace, top_k=3)

        assert [result.episode_id for result in results] == ["deployment-match"]
        assert results[0].score == 1.0
        assert results[0].ranking_score == pytest.approx(1.7)
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_equal_importance_routes_keep_the_newest(tmp_path: Path) -> None:
    """Truncated non-search routes return the newest equal-importance episodes, not an ID-ordered subset."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    namespace = _namespace()
    store = EpisodicMemoryStore(backend, default_ttl_days=0)
    first_day = datetime(2026, 1, 1, tzinfo=timezone.utc)
    try:
        for offset, episode_id in enumerate(("a-pref-old", "b-pref-mid", "c-pref-new")):
            await backend.store(
                _episode(
                    episode_id,
                    namespace,
                    category=EpisodeCategory.USER_PREFERENCE,
                    created_at=first_day + timedelta(days=offset),
                )
            )
        for offset, episode_id in enumerate(("a-fail-old", "b-fail-mid", "c-fail-new"), start=3):
            await backend.store(
                _episode(
                    episode_id,
                    namespace,
                    outcome=EpisodeOutcome.FAILURE,
                    created_at=first_day + timedelta(days=offset),
                )
            )

        preferences = await store.get_user_preferences(namespace, limit=2)
        room = await store.get_room_context(namespace, limit=3)
        warnings = await store.get_failure_warnings(namespace, current_query="deployment", max_warnings=2)

        assert [episode.episode_id for episode in preferences] == ["c-pref-new", "b-pref-mid"]
        assert [episode.episode_id for episode in room] == ["c-fail-new", "b-fail-mid", "a-fail-old"]
        assert "c-fail-new" in warnings and "b-fail-mid" in warnings
        assert "a-fail-old" not in warnings
        assert warnings.index("c-fail-new") < warnings.index("b-fail-mid")
    finally:
        await backend.close()
