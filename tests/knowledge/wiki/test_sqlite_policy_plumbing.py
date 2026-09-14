"""FEAT-557 — a configured SQLite policy reaches an actual connection."""
from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.project import (
    WikiProjectConfig,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import SQLiteWikiStore, create_wiki_store


class TestPolicyFromConfig:
    def test_maps_both_fields(self) -> None:
        """The helper is the one mapping from config to policy."""
        config = WikiProjectConfig(sqlite_busy_timeout=42.0, sqlite_performance_pragmas=True)
        policy = sqlite_policy_from_config(config)
        assert policy.busy_timeout_s == 42.0
        assert policy.performance_pragmas is True


class TestFactoryForwarding:
    async def test_sqlite_branch_receives_policy(self, tmp_path: Path) -> None:
        """A configured timeout lands on a real connection (AC-5)."""
        policy = sqlite_policy_from_config(WikiProjectConfig(sqlite_busy_timeout=7.0))
        store = create_wiki_store(tmp_path, backend="sqlite", sqlite_policy=policy)
        assert isinstance(store, SQLiteWikiStore)
        async with store._open(writable=True) as conn:
            cur = await conn.execute("PRAGMA busy_timeout")
            assert (await cur.fetchone())[0] == 7_000

    def test_policy_does_not_leak_to_other_backends(self, tmp_path: Path) -> None:
        """`sqlite_policy` is popped before the memory/extra branches (spec §7)."""
        policy = sqlite_policy_from_config(WikiProjectConfig())
        # Must not raise TypeError: unexpected keyword argument 'sqlite_policy'.
        store = create_wiki_store(tmp_path, backend="memory", sqlite_policy=policy)
        assert not isinstance(store, SQLiteWikiStore)

    async def test_default_when_no_policy_passed(self, tmp_path: Path) -> None:
        """Omitting the policy still yields the 15 s default (AC-2)."""
        store = create_wiki_store(tmp_path, backend="sqlite")
        assert isinstance(store, SQLiteWikiStore)
        async with store._open(writable=True) as conn:
            cur = await conn.execute("PRAGMA busy_timeout")
            assert (await cur.fetchone())[0] == 15_000


class TestCliPlumbing:
    async def test_open_store_forwards_configured_timeout(self, tmp_path: Path) -> None:
        """`_open_store` honours .parrot/wiki.json (AC-5)."""
        from parrot.knowledge.wiki.cli import _open_store

        config = WikiProjectConfig(wiki_name="t", sqlite_busy_timeout=30.0)
        store = _open_store(tmp_path, config)
        assert isinstance(store, SQLiteWikiStore)
        async with store._open(writable=True) as conn:
            cur = await conn.execute("PRAGMA busy_timeout")
            assert (await cur.fetchone())[0] == 30_000

    def test_open_sources_forwards_configured_timeout(self, tmp_path: Path) -> None:
        """`_open_sources` honours the same setting (AC-6)."""
        from parrot.knowledge.wiki.cli import _open_sources

        config = WikiProjectConfig(wiki_name="t", sqlite_busy_timeout=30.0)
        manager = _open_sources(tmp_path, config)
        assert manager.busy_timeout == 30.0
