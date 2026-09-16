"""FEAT-099 (TASK-079): DocumentDB protected targets for parrot credentials."""
from __future__ import annotations

import base64
import copy
import os
from typing import Any

import orjson
import pytest
from navigator_session.vault import KeyRing, VaultIntegrityError, open_sealed, read_header
from navigator_session.vault.registry import ProtectedTarget

from parrot.security.credentials_utils import (
    credential_context,
    encrypt_credential,
    llm_key_context,
)
from parrot.vault_targets import (
    UserCredentialsTarget,
    UserLlmKeysTarget,
    user_credentials_factory,
    user_llm_keys_factory,
)

MASTER_KEYS = {1: b"\x11" * 32, 2: b"\x22" * 32}


class FakeDocumentDb:
    """In-memory stand-in for ``parrot.interfaces.documentdb.DocumentDb``.

    Collections are lists of dicts; ``read`` drops ``_id`` like the real driver.
    """

    store: dict[str, list[dict]] = {}

    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def _collection(self, name: str) -> list[dict]:
        return self.store.setdefault(name, [])

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        return all(doc.get(k) == v for k, v in query.items())

    async def read(self, collection_name: str, query: dict | None = None, **_kw) -> list[dict]:
        return [
            {k: v for k, v in doc.items() if k != "_id"}
            for doc in self._collection(collection_name)
            if self._matches(doc, query or {})
        ]

    async def read_one(self, collection_name: str, query: dict, **_kw):
        docs = await self.read(collection_name, query)
        return docs[0] if docs else None

    async def write(self, collection_name: str, data, **_kw):
        docs = data if isinstance(data, list) else [data]
        self._collection(collection_name).extend(copy.deepcopy(docs))

    async def update_one(self, collection_name: str, query: dict, update_data: dict,
                         upsert: bool = False, **_kw):
        matched = 0
        for doc in self._collection(collection_name):
            if self._matches(doc, query):
                doc.update(copy.deepcopy(update_data["$set"]))
                matched = 1
                break
        if not matched and upsert:
            self._collection(collection_name).append({**query, **copy.deepcopy(update_data["$set"])})
        return type("Result", (), {"matched_count": matched, "upserted_id": None})()

    async def delete(self, collection_name: str, query: dict, **_kw):
        docs = self._collection(collection_name)
        keep = [doc for doc in docs if not self._matches(doc, query)]
        removed = len(docs) - len(keep)
        self.store[collection_name] = keep
        return removed


class MemoryBackup:
    def __init__(self):
        self.records: dict[str, list[dict]] = {}

    async def write(self, target, record):
        orjson.dumps(record)  # must be JSON-serializable
        self.records.setdefault(target, []).append(record)

    async def read(self, target):
        for record in self.records.get(target, []):
            yield record


@pytest.fixture
def keyring():
    return KeyRing(MASTER_KEYS, 1)


@pytest.fixture
def docdb():
    FakeDocumentDb.store = {}
    return FakeDocumentDb


@pytest.fixture
def credentials_target(docdb):
    return UserCredentialsTarget(docdb)


@pytest.fixture
def llm_keys_target(docdb):
    return UserLlmKeysTarget(docdb)


def seed_credential(docdb, keyring, user_id, name, value):
    docdb.store.setdefault("user_credentials", []).append({
        "_id": object(),
        "user_id": user_id,
        "name": name,
        "credential": encrypt_credential(value, credential_context(user_id, name), keyring),
        "key_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
    })


def seed_llm_key(docdb, keyring, user_id, provider, api_key):
    docdb.store.setdefault("user_llm_keys", []).append({
        "user_id": user_id, "provider": provider,
        "api_key": encrypt_credential({"api_key": api_key}, llm_key_context(user_id, provider), keyring),
        "key_version": 1,
    })


class TestDeclaration:
    def test_protocol_and_names(self, credentials_target, llm_keys_target):
        assert isinstance(credentials_target, ProtectedTarget)
        assert isinstance(llm_keys_target, ProtectedTarget)
        assert credentials_target.name == "docdb:user_credentials"
        assert llm_keys_target.name == "docdb:user_llm_keys"
        assert credentials_target.encrypted_fields == ("credential",)
        assert llm_keys_target.encrypted_fields == ("api_key",)

    def test_factories_need_documentdb(self, docdb, monkeypatch):
        import parrot.vault_targets as module

        monkeypatch.setattr(module, "_default_docdb_factory", lambda: None)
        assert user_credentials_factory({}) is None and user_llm_keys_factory({}) is None
        assert isinstance(user_credentials_factory({"docdb_factory": docdb}), UserCredentialsTarget)
        assert isinstance(user_llm_keys_factory({"docdb_factory": docdb}), UserLlmKeysTarget)

    def test_entry_points_declared(self):
        tomllib = pytest.importorskip("tomllib")
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        data = tomllib.loads((root / "pyproject.toml").read_text())
        group = data["project"]["entry-points"]["navigator_session.vault_targets"]
        assert group["parrot_user_credentials"] == "parrot.vault_targets:user_credentials_factory"
        assert group["parrot_user_llm_keys"] == "parrot.vault_targets:user_llm_keys_factory"


@pytest.mark.asyncio
class TestIterationAndContexts:
    async def test_rows_expose_decoded_blob_and_context(self, docdb, credentials_target, keyring):
        seed_credential(docdb, keyring, 1, "prod", {"driver": "pg"})
        [[row]] = [batch async for batch in credentials_target.iter_batches(10)]
        assert row.ref == "docdb:user_credentials:user_id=1,name=prod"
        assert read_header(row.values["credential"]).key_id == 1
        context = credentials_target.context_for(row, "credential")
        assert orjson.loads(open_sealed(row.values["credential"], context, keyring)) == {"driver": "pg"}
        with pytest.raises(ValueError):
            credentials_target.context_for(row, "api_key")

    async def test_batches_are_deterministic(self, docdb, credentials_target, keyring):
        for i in range(5):
            seed_credential(docdb, keyring, i % 2 + 1, f"name-{i}", {"i": i})
        batches = [b async for b in credentials_target.iter_batches(2)]
        assert [len(b) for b in batches] == [2, 2, 1]
        refs = [r.ref for b in batches for r in b]
        assert refs == sorted(refs) and len(set(refs)) == 5
        with pytest.raises(ValueError):
            [b async for b in credentials_target.iter_batches(0)]

    async def test_llm_key_context_bound_to_provider(self, docdb, llm_keys_target, keyring):
        seed_llm_key(docdb, keyring, "7", "openai", "sk-test")
        seed_llm_key(docdb, keyring, "7", "anthropic", "sk-ant")
        rows = [r for b in [b async for b in llm_keys_target.iter_batches(10)] for r in b]
        openai_row = next(r for r in rows if r.identity["provider"] == "openai")
        other_row = next(r for r in rows if r.identity["provider"] == "anthropic")
        with pytest.raises(VaultIntegrityError):
            open_sealed(
                openai_row.values["api_key"],
                llm_keys_target.context_for(other_row, "api_key"),
                keyring,
            )


@pytest.mark.asyncio
class TestWriteQuarantineRestore:
    async def test_write_updates_document(self, docdb, credentials_target, keyring):
        seed_credential(docdb, keyring, 1, "prod", {"driver": "pg"})
        [[row]] = [b async for b in credentials_target.iter_batches(10)]
        new_blob = base64.b64decode(
            encrypt_credential({"driver": "pg2"}, credential_context(1, "prod"), keyring, key_id=2)
        )
        await credentials_target.write(row, {"credential": new_blob}, 2)
        doc = docdb.store["user_credentials"][0]
        assert doc["key_version"] == 2 and "updated_at" in doc
        assert base64.b64decode(doc["credential"]) == new_blob

    async def test_write_validation_and_missing_document(self, docdb, credentials_target, keyring):
        seed_credential(docdb, keyring, 1, "prod", {"a": 1})
        [[row]] = [b async for b in credentials_target.iter_batches(10)]
        with pytest.raises(ValueError):
            await credentials_target.write(row, {}, 1)
        with pytest.raises(ValueError):
            await credentials_target.write(row, {"api_key": b"x"}, 1)
        with pytest.raises(ValueError):
            await credentials_target.write(row, {"credential": None}, 1)
        docdb.store["user_credentials"] = []
        with pytest.raises(LookupError):
            await credentials_target.write(row, {"credential": b"\xa2x"}, 1)

    async def test_quarantine_moves_document(self, docdb, credentials_target, keyring):
        seed_credential(docdb, keyring, 1, "prod", {"a": 1})
        original = copy.deepcopy(docdb.store["user_credentials"][0])
        [[row]] = [b async for b in credentials_target.iter_batches(10)]
        await credentials_target.quarantine(row, "VaultIntegrityError", run_id="run-1")
        assert docdb.store["user_credentials"] == []
        [quarantined] = docdb.store["user_credentials_quarantine"]
        assert quarantined["credential"] == original["credential"]
        assert quarantined["reason"] == "VaultIntegrityError" and quarantined["run_id"] == "run-1"
        assert quarantined["quarantined_at"]

    async def test_export_restore_roundtrip(self, docdb, credentials_target, llm_keys_target, keyring):
        seed_credential(docdb, keyring, 1, "prod", {"driver": "pg", "password": "p"})
        seed_credential(docdb, keyring, 2, "dev", {"driver": "pg"})
        seed_llm_key(docdb, keyring, "7", "openai", "sk-test")
        before = copy.deepcopy(docdb.store)
        sink = MemoryBackup()

        assert await credentials_target.export_raw(sink) == 2
        assert await llm_keys_target.export_raw(sink) == 1
        dumped = orjson.dumps(sink.records).decode()
        assert "password" not in dumped and "sk-test" not in dumped

        # migrate + quarantine, then roll back
        rows = [r for b in [b async for b in credentials_target.iter_batches(10)] for r in b]
        await credentials_target.write(rows[0], {"credential": b"\xa2migrated"}, 2)
        await credentials_target.quarantine(rows[1], "LegacyV1Error", run_id="run-2")

        assert await credentials_target.restore_raw(sink) == 2
        assert await llm_keys_target.restore_raw(sink) == 1
        restored = {
            name: [{k: v for k, v in doc.items() if k != "_id"} for doc in docs]
            for name, docs in docdb.store.items() if docs
        }
        expected = {
            name: [{k: v for k, v in doc.items() if k != "_id"} for doc in docs]
            for name, docs in before.items()
        }
        assert restored == expected  # quarantine copy removed, documents byte-identical
