"""Tests for LocalJiraTokenStore and FileTokenCredentialResolver (FEAT-696 M3)."""

from __future__ import annotations

import json
import stat
import time
from unittest.mock import AsyncMock, patch

import pytest

from parrot_tools.jira_local_auth import FileTokenCredentialResolver, LocalJiraTokenStore
from parrot.auth.jira_oauth import JiraTokenSet


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Never touch the real home directory."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in (
        "JIRA_LOCAL_SETTINGS",
        "JIRA_CLIENT_ID",
        "JIRA_CLIENT_SECRET",
        "JIRA_LOCAL_SITE",
        "JIRA_LOCAL_ALLOWED_CHANNELS",
    ):
        monkeypatch.delenv(name, raising=False)


def _token(expires_in: float = 3600, refresh: str = "r1", site: str = "https://x.atlassian.net") -> JiraTokenSet:
    return JiraTokenSet(
        access_token="a1",
        refresh_token=refresh,
        expires_at=time.time() + expires_in,
        cloud_id="cid",
        site_url=site,
        account_id="acc",
        display_name="Me",
    )


def _store(tmp_path) -> LocalJiraTokenStore:
    return LocalJiraTokenStore(tmp_path / "jira" / "settings.local.json")


class TestLocalJiraTokenStore:
    def test_save_creates_file_0600(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token())
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700

    def test_save_atomic_replace(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token(refresh="r1"))
        store.save(_token(refresh="r2"))
        assert store.get().refresh_token == "r2"
        assert [p.name for p in store.path.parent.iterdir() if p.name.endswith(".tmp")] == []
        json.loads(store.path.read_text())

    def test_get_default_site(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token(), make_default=True)
        assert store.get().cloud_id == "cid"
        assert store.get("https://x.atlassian.net") is not None
        assert store.get("nope") is None

    def test_delete_removes_entry(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token())
        assert store.delete() is True
        assert store.get() is None
        assert not store.path.exists()
        assert store.delete() is False


class TestFileTokenCredentialResolver:
    @pytest.mark.asyncio
    async def test_resolve_returns_valid_token(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token())
        r = FileTokenCredentialResolver(store, "id", "secret")
        tok = await r.resolve("cli", "u")
        assert tok.access_token == "a1"

    @pytest.mark.asyncio
    async def test_resolve_refreshes_expired(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token(expires_in=-100))
        r = FileTokenCredentialResolver(store, "id", "secret")
        with patch(
            "parrot_tools.jira_local_auth.refresh_access_token",
            new=AsyncMock(return_value={"access_token": "a2", "refresh_token": "r2", "expires_in": 3600}),
        ):
            tok = await r.resolve("cli", "u")
        assert tok.access_token == "a2"
        assert store.get().refresh_token == "r2"
        assert not store.get().is_expired

    @pytest.mark.asyncio
    async def test_resolve_keeps_old_refresh_token(self, tmp_path):
        store = _store(tmp_path)
        store.save(_token(expires_in=-100, refresh="keepme"))
        r = FileTokenCredentialResolver(store, "id", "secret")
        with patch(
            "parrot_tools.jira_local_auth.refresh_access_token",
            new=AsyncMock(return_value={"access_token": "a2", "expires_in": 3600}),
        ):
            tok = await r.resolve("cli", "u")
        assert tok.refresh_token == "keepme"
        assert store.get().refresh_token == "keepme"

    @pytest.mark.asyncio
    async def test_resolve_none_when_missing(self, tmp_path):
        r = FileTokenCredentialResolver(_store(tmp_path), "id", "secret")
        assert await r.resolve("cli", "u") is None

    @pytest.mark.asyncio
    async def test_get_auth_url_raises(self, tmp_path):
        r = FileTokenCredentialResolver(_store(tmp_path), "id", "secret")
        with pytest.raises(NotImplementedError):
            await r.get_auth_url("cli", "u")

    def test_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_LOCAL_SETTINGS", str(tmp_path / "s.json"))
        monkeypatch.setenv("JIRA_CLIENT_ID", "cid")
        monkeypatch.setenv("JIRA_CLIENT_SECRET", "sec")
        monkeypatch.setenv("JIRA_LOCAL_SITE", "https://x.atlassian.net")
        r = FileTokenCredentialResolver.from_env()
        assert (r.client_id, r.client_secret, r.site) == ("cid", "sec", "https://x.atlassian.net")
        assert r.store.path == tmp_path / "s.json"
        assert r.single_user is True


@pytest.mark.asyncio
async def test_cancelled_lock_acquisition_releases_lock(tmp_path) -> None:
    """A resolve() cancelled while waiting for the flock must not leave the lock held."""
    import asyncio
    import fcntl
    import os

    store = _store(tmp_path)
    store.save(_token(expires_in=-100))
    resolver = FileTokenCredentialResolver(store, "id", "secret")

    with store.locked():
        task = asyncio.ensure_future(resolver.resolve("cli", "local"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.sleep(0.2)  # let the worker thread finish and the release callback run

    fd = os.open(store.lock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises BlockingIOError if still held
    finally:
        os.close(fd)


class TestCorruptStore:
    def test_corrupt_file_raises_clean_error_on_read(self, tmp_path):
        store = _store(tmp_path)
        store.path.parent.mkdir(parents=True)
        store.path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="corrupt"):
            store.get()

    def test_save_repairs_corrupt_file(self, tmp_path):
        store = _store(tmp_path)
        store.path.parent.mkdir(parents=True)
        store.path.write_text("{not json", encoding="utf-8")
        store.save(_token())
        assert store.get().access_token == "a1"

    def test_delete_on_corrupt_file_is_noop(self, tmp_path):
        store = _store(tmp_path)
        store.path.parent.mkdir(parents=True)
        store.path.write_text("{not json", encoding="utf-8")
        assert store.delete() is False
