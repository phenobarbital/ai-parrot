"""FEAT-099 (TASK-082): VaultTokenSync round-trips ``{provider}:{field}`` keys.

Regression for F4: ``SessionVault._validate_key`` used to reject ``:`` in key
names, so every ``store_tokens()`` write raised, was swallowed by the broad
``except`` and silently stored nothing. Keys are hashed in Redis now, so ``:``
is allowed and Telegram/CLI token persistence works.

Uses the real ``SessionVault`` against in-memory database/Redis doubles.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import pytest
from navigator_session.vault import KeyRing
from navigator_session.vault import session_vault as sv

from parrot.services.vault_token_sync import VaultTokenSync, _synth_session_uuid

MASTER_KEYS = {1: b"\x66" * 32}
USER_ID = "7"
PROVIDER = "o365"


def _norm(sql: str) -> str:
    return " ".join(sql.split())


class VaultDb:
    """Minimal auth.user_vault_secrets / auth.user_vault_audit double."""

    def __init__(self) -> None:
        self.secrets: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []

    def active(self, user_id, key):
        return next(
            (r for r in self.secrets
             if r["user_id"] == user_id and r["key"] == key and r["deleted_at"] is None),
            None,
        )

    @asynccontextmanager
    async def _conn(self):
        yield VaultDbConnection(self)

    def acquire(self):
        return self._conn()


class VaultDbConnection:
    def __init__(self, db: VaultDb) -> None:
        self.db = db

    async def execute(self, sql: str, *args: Any) -> str:
        stmt = _norm(sql)
        if stmt == _norm(sv._UPSERT_SECRET):
            user_id, key, blob, key_version = args
            row = self.db.active(user_id, key)
            if row is None:
                self.db.secrets.append({
                    "id": uuid.uuid4(), "user_id": user_id, "key": key,
                    "ciphertext_db": blob, "key_version": key_version,
                    "updated_at": datetime.now(timezone.utc), "deleted_at": None,
                })
            else:
                row.update(ciphertext_db=blob, key_version=key_version,
                           updated_at=datetime.now(timezone.utc))
            return "INSERT 0 1"
        if stmt == _norm(sv._SOFT_DELETE_SECRET):
            row = self.db.active(*args)
            if row:
                row["deleted_at"] = datetime.now(timezone.utc)
            return "UPDATE 1"
        if stmt == _norm(sv._INSERT_AUDIT):
            self.db.audit.append({"user_id": args[0], "key": args[1], "operation": args[2]})
            return "INSERT 0 1"
        raise AssertionError(f"unexpected SQL: {stmt}")

    async def fetch(self, sql: str, *args: Any):
        assert _norm(sql) == _norm(sv._SELECT_ALL_ACTIVE)
        return [
            {k: r[k] for k in ("key", "ciphertext_db", "key_version", "updated_at")}
            for r in self.db.secrets if r["user_id"] == args[0] and r["deleted_at"] is None
        ]


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def setex(self, name, ttl, value):
        self.data[name] = value

    async def get(self, name):
        return self.data.get(name)

    async def delete(self, name):
        self.data.pop(name, None)


@pytest.fixture
def keyring():
    return KeyRing(MASTER_KEYS, 1)


@pytest.fixture
def db():
    return VaultDb()


@pytest.fixture
def sync(db, keyring, monkeypatch):
    """VaultTokenSync wired to the doubles, with a deterministic key ring."""
    original = sv.SessionVault.load_for_session.__func__

    async def load_with_keyring(cls, **kwargs):
        kwargs.setdefault("keyring", keyring)
        return await original(cls, **kwargs)

    monkeypatch.setattr(sv.SessionVault, "load_for_session", classmethod(load_with_keyring))
    return VaultTokenSync(db_pool=db, redis=FakeRedis(), session_scheme="cli-persistent")


TOKENS = {
    "access_token": "eyJ-access",
    "refresh_token": "eyJ-refresh",
    "expires_at": "2026-09-16T10:00:00+00:00",
}


@pytest.mark.asyncio
class TestF4Regression:
    async def test_colon_keys_round_trip(self, sync, db):
        """store_tokens actually persists {provider}:{field} keys (F4)."""
        await sync.store_tokens(USER_ID, PROVIDER, TOKENS)

        stored_keys = sorted(row["key"] for row in db.secrets)
        assert stored_keys == [f"{PROVIDER}:{field}" for field in sorted(TOKENS)]
        assert all(row["ciphertext_db"][0] == 0xA2 for row in db.secrets)
        assert not any("eyJ-access" in str(row["ciphertext_db"]) for row in db.secrets)

        result = await sync.read_tokens_result(USER_ID, PROVIDER)
        assert result.status == "ok" and result.tokens == TOKENS
        assert await sync.read_tokens(USER_ID, PROVIDER) == TOKENS

    async def test_deterministic_session_across_instances(self, db, keyring, monkeypatch):
        """A fresh instance (new process) reads what a previous one stored."""
        original = sv.SessionVault.load_for_session.__func__

        async def load_with_keyring(cls, **kwargs):
            kwargs.setdefault("keyring", keyring)
            return await original(cls, **kwargs)

        monkeypatch.setattr(sv.SessionVault, "load_for_session", classmethod(load_with_keyring))
        writer = VaultTokenSync(db_pool=db, redis=FakeRedis(), session_scheme="telegram-persistent")
        await writer.store_tokens(USER_ID, "jira", {"access_token": "tok"})

        reader = VaultTokenSync(db_pool=db, redis=FakeRedis(), session_scheme="telegram-persistent")
        assert await reader.read_tokens(USER_ID, "jira") == {"access_token": "tok"}
        assert _synth_session_uuid(USER_ID, "telegram-persistent") == f"telegram-persistent:{USER_ID}"

    async def test_delete_tokens(self, sync, db):
        await sync.store_tokens(USER_ID, PROVIDER, TOKENS)
        await sync.delete_tokens(USER_ID, PROVIDER)
        assert await sync.read_tokens(USER_ID, PROVIDER) is None
        assert all(row["deleted_at"] is not None for row in db.secrets)

    async def test_missing_vs_unreadable(self, sync, db):
        assert (await sync.read_tokens_result(USER_ID, PROVIDER)).status == "missing"

        await sync.store_tokens(USER_ID, PROVIDER, TOKENS)
        # Tamper with a stored blob the way a database-level attacker would.
        row = db.secrets[0]
        row["ciphertext_db"] = row["ciphertext_db"][:-1] + bytes([row["ciphertext_db"][-1] ^ 1])

        fresh = VaultTokenSync(db_pool=db, redis=FakeRedis(), session_scheme="cli-persistent")
        fresh._vaults.clear()
        result = await fresh.read_tokens_result(USER_ID, PROVIDER)
        # the tampered secret is skipped at load time, so the set is incomplete
        assert result.status in ("ok", "unreadable")
        if result.status == "ok":
            assert f"{PROVIDER}:access_token" not in (result.tokens or {})
            assert len(result.tokens or {}) < len(TOKENS)

    async def test_partial_write_warning_still_works(self, sync, db, caplog, monkeypatch):
        """FEAT-267 behaviour preserved: partial writes are reported."""
        import logging

        calls = {"n": 0}
        original_set = sv.SessionVault.set

        async def flaky_set(self, key, value):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("redis down")
            return await original_set(self, key, value)

        monkeypatch.setattr(sv.SessionVault, "set", flaky_set)
        with caplog.at_level(logging.WARNING):
            await sync.store_tokens(USER_ID, PROVIDER, TOKENS)
        assert "PARTIAL WRITE detected" in caplog.text
        assert "eyJ-access" not in caplog.text
