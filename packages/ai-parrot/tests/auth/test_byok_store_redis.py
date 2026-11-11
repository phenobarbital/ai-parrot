from __future__ import annotations

from datetime import datetime

import pytest
from navigator_session.vault import KeyRing

import parrot.auth.broker as broker
from parrot.auth.broker.byok_redis import RedisUserLLMKeyStore, mask_api_key


class FakeDocuments:
    def __init__(self):
        self.documents = []

    async def get(self, key):
        return next((doc for doc in self.documents if all(doc.get(k) == v for k, v in key.items())), None)

    async def upsert(self, key, fields, *, on_insert=None):
        document = await self.get(key)
        if document is None:
            document = {**key, **(on_insert or {})}
            self.documents.append(document)
        document.update(fields)
        return document

    async def delete(self, key):
        document = await self.get(key)
        if document is None:
            return False
        self.documents.remove(document)
        return True

    async def find(self, where):
        return [doc for doc in self.documents if all(doc.get(k) == v for k, v in where.items())]


@pytest.fixture
def keyring(monkeypatch):
    ring = KeyRing({1: b"0" * 32}, 1)
    monkeypatch.setattr("parrot.auth.broker.byok_redis.get_vault_keyring", lambda: ring)
    return ring


def test_mask_api_key_never_exposes_short_keys():
    assert mask_api_key("short") == "*****"
    assert mask_api_key("12345678") == "123…5678"


@pytest.mark.asyncio
async def test_redis_store_round_trip_rotation_and_listing(keyring):
    documents = FakeDocuments()
    store = RedisUserLLMKeyStore(documents)

    await store.put("user-1", "zeta", "sk-zeta-secret")
    created_at = documents.documents[0]["created_at"]
    await store.put("user-1", "alpha", "sk-alpha-secret")
    await store.put("user-1", "zeta", "sk-zeta-rotated")

    assert await store.get("user-1", "zeta") == "sk-zeta-rotated"
    zeta = next(document for document in documents.documents if document["provider"] == "zeta")
    assert zeta["created_at"] == created_at
    assert await store.list_masked("user-1") == [
        {
            "provider": "alpha",
            "masked": "sk-…cret",
            "created_at": next(document for document in documents.documents if document["provider"] == "alpha")[
                "created_at"
            ].isoformat(),
        },
        {"provider": "zeta", "masked": "sk-…ated", "created_at": created_at.isoformat()},
    ]
    assert await store.delete("user-1", "alpha") is True
    assert await store.delete("user-1", "alpha") is False


@pytest.mark.asyncio
async def test_list_masked_falls_back_for_copied_undecryptable_document(keyring):
    documents = FakeDocuments()
    documents.documents.append(
        {"user_id": "user-1", "provider": "alpha", "api_key": "not-valid", "created_at": datetime.now()}
    )
    assert await RedisUserLLMKeyStore(documents).list_masked("user-1") == [
        {"provider": "alpha", "masked": "****", "created_at": documents.documents[0]["created_at"].isoformat()}
    ]


def test_store_accessor_selects_postgres_and_redis(monkeypatch):
    postgres = object()
    broker.set_user_llm_key_store(postgres)
    monkeypatch.setenv("BYOK_STORE", "postgres")
    assert broker.get_user_llm_key_store() is postgres
    monkeypatch.setenv("BYOK_STORE", "redis")
    monkeypatch.setattr(broker, "_REDIS_STORE", object())
    assert broker.get_user_llm_key_store() is broker._REDIS_STORE
    broker.set_user_llm_key_store(None)
