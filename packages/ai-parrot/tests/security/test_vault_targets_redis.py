"""Redis protected-target coverage for vault rotation (FEAT-878)."""

from __future__ import annotations

import base64

import pytest
import pytest_asyncio
from navigator_session.vault import KeyRing

from parrot import vault_targets
from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_CREDENTIALS
from parrot.userstore.testing import redis_test_settings

MASTER_KEYS = {1: b"\x11" * 32, 2: b"\x22" * 32}


class MemoryBackup:
    """In-memory BackupSink and BackupSource for raw target records."""

    def __init__(self) -> None:
        self.records: dict[str, list[dict]] = {}

    async def write(self, target: str, record: dict) -> None:
        """Store one raw backup record."""
        self.records.setdefault(target, []).append(record)

    async def read(self, target: str):
        """Yield stored records for one target."""
        for record in self.records.get(target, []):
            yield record


@pytest_asyncio.fixture
async def redis_env(monkeypatch: pytest.MonkeyPatch):
    """Configure one isolated Redis namespace for each test."""
    monkeypatch.delenv("VAULT_STORE", raising=False)
    monkeypatch.delenv("BYOK_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    async with redis_test_settings(monkeypatch):
        yield


async def test_redis_target_rotation_cycle(redis_env) -> None:
    """Redis target rotation, quarantine, and restore preserve decryptability."""
    target = vault_targets.redis_user_credentials_factory({})
    assert isinstance(target, vault_targets.RedisUserCredentialsTarget)
    documents = RedisDocumentStore(USER_CREDENTIALS)
    identity = {"user_id": 1, "name": "production"}
    keyring = KeyRing(MASTER_KEYS, 1)
    context = credential_context(**identity)
    await documents.put(
        {
            **identity,
            "credential": encrypt_credential({"driver": "postgres"}, context, keyring),
            "key_version": 1,
        }
    )

    [[row]] = [batch async for batch in target.iter_batches(10)]
    rotated = base64.b64decode(encrypt_credential({"driver": "postgres-rotated"}, context, keyring, key_id=2))
    await target.write(row, {"credential": rotated}, key_version=2)
    stored = await documents.get(identity)
    assert stored is not None
    assert stored["key_version"] == 2
    assert decrypt_credential(stored["credential"], context, keyring) == {"driver": "postgres-rotated"}

    backup = MemoryBackup()
    assert await target.export_raw(backup) == 1
    await target.quarantine(row, "rotation-check", run_id="run-1")
    assert await documents.get(identity) is None
    assert await target.restore_raw(backup) == 1
    restored = await documents.get(identity)
    assert restored is not None
    assert decrypt_credential(restored["credential"], context, keyring) == {"driver": "postgres-rotated"}


def test_redis_target_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factories select Redis only and suppress invalid switch settings."""
    monkeypatch.setenv("VAULT_STORE", "documentdb")
    assert vault_targets.redis_user_credentials_factory({}) is None

    monkeypatch.delenv("VAULT_STORE")
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    assert isinstance(vault_targets.redis_user_credentials_factory({}), vault_targets.RedisUserCredentialsTarget)
    assert isinstance(vault_targets.redis_user_llm_keys_factory({}), vault_targets.RedisUserLlmKeysTarget)

    monkeypatch.setenv("BYOK_STORE", "not-a-backend")
    assert vault_targets.redis_user_llm_keys_factory({}) is None
