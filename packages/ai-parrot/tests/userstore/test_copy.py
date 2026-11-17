"""Tests for the DocumentDB to Redis user-store copy command."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from navigator_session.vault import KeyRing

from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential
from parrot.userstore import RedisDocumentStore
from parrot.userstore import copy as copy_mod
from parrot.userstore.collections import USER_CREDENTIALS
from parrot.userstore.testing import redis_test_settings


class _FakeDocumentDb:
    """Minimal async DocumentDB source with isolated in-memory collections."""

    collections: dict[str, list[dict[str, Any]]] = {}

    async def __aenter__(self) -> _FakeDocumentDb:
        """Return this fake connection."""
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        """Close the fake connection without suppressing errors."""
        return False

    async def read(self, name: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Return copies of every document in the requested collection."""
        assert query == {}
        return [dict(document) for document in self.collections.get(name, [])]


@pytest_asyncio.fixture
async def env(monkeypatch: pytest.MonkeyPatch):
    """Patch DocumentDB and point Redis at an isolated db-15 prefix."""
    _FakeDocumentDb.collections = {}
    monkeypatch.setattr(copy_mod, "DocumentDb", _FakeDocumentDb)
    async with redis_test_settings(monkeypatch):
        yield


@pytest.mark.asyncio
async def test_copy_insert_only_and_overwrite(env: None) -> None:
    """A second run skips, while overwrite accepts only a strictly newer source."""
    key = {"user_id": "u1", "name": "prod"}
    _FakeDocumentDb.collections[USER_CREDENTIALS.name] = [
        {**key, "credential": "first", "updated_at": "2026-01-02T00:00:00Z"}
    ]

    first = await copy_mod.copy_to_redis([USER_CREDENTIALS.name])
    second = await copy_mod.copy_to_redis([USER_CREDENTIALS.name])
    assert first.copied == {USER_CREDENTIALS.name: 1}
    assert second.skipped == {USER_CREDENTIALS.name: 1}

    _FakeDocumentDb.collections[USER_CREDENTIALS.name][0].update(
        credential="older", updated_at="2026-01-01T00:00:00+00:00"
    )
    older = await copy_mod.copy_to_redis([USER_CREDENTIALS.name], overwrite=True)
    assert older.skipped == {USER_CREDENTIALS.name: 1}

    _FakeDocumentDb.collections[USER_CREDENTIALS.name][0].update(
        credential="newer", updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc)
    )
    newer = await copy_mod.copy_to_redis([USER_CREDENTIALS.name], overwrite=True)
    assert newer.copied == {USER_CREDENTIALS.name: 1}
    assert (await RedisDocumentStore(USER_CREDENTIALS).get(key))["credential"] == "newer"


@pytest.mark.asyncio
async def test_copy_dry_run_writes_nothing(env: None) -> None:
    """Dry-run reports a copy but leaves Redis unchanged."""
    document = {"user_id": "u1", "name": "dry", "credential": "sealed"}
    _FakeDocumentDb.collections[USER_CREDENTIALS.name] = [document]
    report = await copy_mod.copy_to_redis([USER_CREDENTIALS.name], dry_run=True)
    assert report.copied == {USER_CREDENTIALS.name: 1}
    assert await RedisDocumentStore(USER_CREDENTIALS).get(document) is None


@pytest.mark.asyncio
async def test_copy_collapses_duplicates(env: None) -> None:
    """Only the newest source document for a key is copied."""
    key = {"user_id": "u1", "name": "duplicate"}
    _FakeDocumentDb.collections[USER_CREDENTIALS.name] = [
        {**key, "credential": "newest", "updated_at": "2026-02-01T00:00:00Z", "_id": "new"},
        {**key, "credential": "oldest", "updated_at": "2025-02-01T00:00:00Z", "_id": "old"},
    ]
    report = await copy_mod.copy_to_redis([USER_CREDENTIALS.name])
    stored = await RedisDocumentStore(USER_CREDENTIALS).get(key)
    assert report.duplicates == {USER_CREDENTIALS.name: 1}
    assert stored["credential"] == "newest"
    assert "_id" not in stored


@pytest.mark.asyncio
async def test_sealed_credential_remains_decryptable(env: None) -> None:
    """The copy preserves sealed credential bytes encoded in the source string."""
    keyring = KeyRing({1: b"k" * 32}, 1)
    key = {"user_id": "u1", "name": "sealed"}
    context = credential_context(**key)
    sealed = encrypt_credential({"password": "secret"}, context, keyring)
    _FakeDocumentDb.collections[USER_CREDENTIALS.name] = [{**key, "credential": sealed}]
    await copy_mod.copy_to_redis([USER_CREDENTIALS.name])
    stored = await RedisDocumentStore(USER_CREDENTIALS).get(key)
    assert decrypt_credential(stored["credential"], context, keyring) == {"password": "secret"}


@pytest.mark.asyncio
async def test_copy_no_secret_in_logs(env: None, caplog: pytest.LogCaptureFixture) -> None:
    """Failures log identity and exception class without document values."""
    secret = "never-log-this-ciphertext"
    _FakeDocumentDb.collections[USER_CREDENTIALS.name] = [{"user_id": "u1", "credential": secret}]
    with caplog.at_level(logging.WARNING, logger="parrot.userstore.copy"):
        report = await copy_mod.copy_to_redis([USER_CREDENTIALS.name])
    assert report.failed == {USER_CREDENTIALS.name: 1}
    assert secret not in caplog.text
    assert "ValueError" in caplog.text


def test_main_rejects_unknown_collection(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown collection names produce argparse's usage exit code and valid-name guidance."""
    with pytest.raises(SystemExit) as raised:
        copy_mod.main(["--collections", "not_a_store"])
    assert raised.value.code == 2
    assert "valid names" in capsys.readouterr().err
