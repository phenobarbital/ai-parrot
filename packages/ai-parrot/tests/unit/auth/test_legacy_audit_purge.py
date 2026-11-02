"""FEAT-776 M10 purge tests."""

import fnmatch
import sys
import types
from datetime import datetime, timezone

import pytest

import parrot.auth.oauth2.legacy_audit as legacy_audit
import parrot.auth.oauth2_base as oauth2_base
from parrot.auth.oauth2.legacy_audit import main, purge_legacy_keys

AFTER = datetime(2030, 1, 2, tzinfo=timezone.utc)
BEFORE = datetime(2029, 12, 31, tzinfo=timezone.utc)


class MemRedis:
    """In-memory Redis double with scan_iter(match=) and unlink(*keys)."""

    def __init__(self, keys):
        self.store = dict.fromkeys(keys, "secret")
        self.reads = 0

    async def scan_iter(self, match="*"):
        for key in list(self.store):
            if fnmatch.fnmatchcase(key, match):
                yield key

    async def unlink(self, *keys):
        for key in keys:
            self.store.pop(key, None)
        return len(keys)

    async def get(self, key):  # pragma: no cover - must never be called
        self.reads += 1
        return self.store.get(key)


KEYS = [
    "jira:oauth:telegram:1",
    "oauth2:jira:telegram:1",
    "oauth2:o365:telegram:2",
    "oauth2:o365:web:2",
    "oauth2:jira:msteams:3",
    "jira:oauth:web:4",
]


def _cutoff(monkeypatch, value):
    monkeypatch.setattr(legacy_audit, "OAUTH2_LEGACY_KEYS_UNTIL", value)
    monkeypatch.setattr(oauth2_base, "OAUTH2_LEGACY_KEYS_UNTIL", value)


@pytest.mark.asyncio
async def test_purge_dry_run_and_date_gate(monkeypatch) -> None:
    _cutoff(monkeypatch, "2030-01-01T00:00:00Z")
    redis = MemRedis(KEYS)
    counts = await purge_legacy_keys(redis, channel="telegram", providers=["jira", "o365"], now=BEFORE)
    assert counts == {
        "jira:oauth:telegram:*": 1,
        "oauth2:jira:telegram:*": 1,
        "oauth2:o365:telegram:*": 1,
    }
    assert len(redis.store) == len(KEYS)
    with pytest.raises(PermissionError):
        await purge_legacy_keys(redis, channel="telegram", providers=["jira"], dry_run=False, now=BEFORE)
    # exactly at the cutoff the window is still open
    with pytest.raises(PermissionError):
        await purge_legacy_keys(
            redis,
            channel="telegram",
            providers=["jira"],
            dry_run=False,
            now=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
    assert len(redis.store) == len(KEYS)
    for bad in ("", "   ", "not-a-date"):
        _cutoff(monkeypatch, bad)
        with pytest.raises(PermissionError):
            await purge_legacy_keys(redis, channel="telegram", providers=["jira"], dry_run=False, now=AFTER)
    assert len(redis.store) == len(KEYS)
    await purge_legacy_keys(redis, channel="telegram", providers=["jira"], dry_run=False, force=True, now=BEFORE)
    assert "oauth2:jira:telegram:1" not in redis.store
    assert redis.reads == 0


@pytest.mark.asyncio
async def test_purge_deletes_only_channel_keys(monkeypatch) -> None:
    _cutoff(monkeypatch, "2030-01-01T00:00:00Z")
    monkeypatch.setattr(legacy_audit, "_UNLINK_BATCH", 1)
    redis = MemRedis(KEYS)
    counts = await purge_legacy_keys(redis, channel="telegram", providers=["jira", "o365"], dry_run=False, now=AFTER)
    assert sum(counts.values()) == 3
    assert sorted(redis.store) == sorted(["oauth2:o365:web:2", "oauth2:jira:msteams:3", "jira:oauth:web:4"])
    with pytest.raises(ValueError):
        await purge_legacy_keys(redis, channel="*", providers=["jira"], dry_run=False, force=True)
    assert len(redis.store) == 3


def test_purge_cli_exit_code_2_when_gate_refuses(monkeypatch, capsys) -> None:
    _cutoff(monkeypatch, "2999-01-01T00:00:00Z")
    redis = MemRedis(KEYS)
    fake_asyncio = types.ModuleType("redis.asyncio")
    fake_asyncio.from_url = lambda url: redis
    fake_redis = types.ModuleType("redis")
    fake_redis.asyncio = fake_asyncio
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_asyncio)
    assert main(["--purge", "--channel", "telegram", "--confirm"]) == 2
    assert len(redis.store) == len(KEYS)
    assert main(["--purge", "--channel", "telegram"]) == 0
    out = capsys.readouterr().out
    assert "oauth2:o365:telegram:*\t1" in out
    assert "secret" not in out
