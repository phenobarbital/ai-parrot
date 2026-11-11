"""AC11: all user-store collections survive DocumentDB-to-Redis copy."""

from typing import Any

import pytest

from parrot.userstore import RedisDocumentStore
from parrot.userstore import copy as copy_mod
from parrot.userstore.collections import USER_STORE_COLLECTIONS
from parrot.userstore.testing import redis_test_settings


class FakeDocumentDb:
    """Return deterministic source documents without opening MongoDB."""

    collections: dict[str, list[dict[str, Any]]] = {}

    async def __aenter__(self) -> "FakeDocumentDb":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def read(self, name: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        assert query == {}
        return [dict(document) for document in self.collections[name]]


@pytest.mark.asyncio
async def test_copy_then_read_through_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Copy one valid keyed document for each registered collection and read it back."""
    monkeypatch.setattr(copy_mod, "DocumentDb", FakeDocumentDb)
    FakeDocumentDb.collections = {
        name: [{field: f"{name}-{field}" for field in spec.key_fields}] for name, spec in USER_STORE_COLLECTIONS.items()
    }
    async with redis_test_settings(monkeypatch):
        report = await copy_mod.copy_to_redis()
        assert report.failed == dict.fromkeys(USER_STORE_COLLECTIONS, 0)
        assert report.copied == dict.fromkeys(USER_STORE_COLLECTIONS, 1)
        for name, spec in USER_STORE_COLLECTIONS.items():
            source = FakeDocumentDb.collections[name][0]
            assert await RedisDocumentStore(spec).get(source) == source
