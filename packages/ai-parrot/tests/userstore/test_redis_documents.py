"""Integration coverage for the FEAT-878 Redis keyed document primitive."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from parrot.userstore import CollectionSpec, RedisDocumentStore
from parrot.userstore.testing import redis_test_settings

SPEC = CollectionSpec("t_docs", ("user_id", "name"), ("user_id", "kind"))


@pytest_asyncio.fixture
async def store(monkeypatch: pytest.MonkeyPatch):
    """Provide an isolated real-Redis document store."""
    async with redis_test_settings(monkeypatch):
        yield RedisDocumentStore(SPEC)


@pytest.mark.asyncio
async def test_put_get_delete_roundtrip(store: RedisDocumentStore) -> None:
    """Full-key addressing encodes special characters and normalizes key types."""
    await store.put({"user_id": 35, "name": "a:b/c", "kind": "x", "v": 1})
    assert (await store.get({"user_id": "35", "name": "a:b/c"})) == {
        "user_id": 35,
        "name": "a:b/c",
        "kind": "x",
        "v": 1,
    }
    assert await store.delete({"user_id": 35, "name": "a:b/c"}) is True
    assert await store.get({"user_id": 35, "name": "a:b/c"}) is None


@pytest.mark.asyncio
async def test_upsert_on_insert_only_once(store: RedisDocumentStore) -> None:
    """$setOnInsert fields apply only to the initial upsert."""
    key = {"user_id": 1, "name": "first"}
    assert await store.upsert(key, {"kind": "one"}, on_insert={"created": "initial"}) == {
        **key,
        "created": "initial",
        "kind": "one",
    }
    result = await store.upsert(key, {"kind": "two"}, on_insert={"created": "replacement"})
    assert result["created"] == "initial"
    assert result["kind"] == "two"


@pytest.mark.asyncio
async def test_update_absent_returns_false(store: RedisDocumentStore) -> None:
    """Update never creates an absent document."""
    key = {"user_id": 1, "name": "missing"}
    assert await store.update(key, {"kind": "x"}) is False
    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_create_only_when_absent(store: RedisDocumentStore) -> None:
    """A duplicate create preserves the initial document."""
    original = {"user_id": 1, "name": "only", "kind": "first"}
    assert await store.create(original) is True
    assert await store.create({**original, "kind": "second"}) is False
    assert await store.get(original) == original


@pytest.mark.asyncio
async def test_index_follows_field_change(store: RedisDocumentStore) -> None:
    """Changing an indexed field removes its old index membership."""
    key = {"user_id": 1, "name": "updated"}
    await store.put({**key, "kind": "old"})
    assert await store.update(key, {"kind": "new"}) is True
    assert await store.find({"kind": "old"}) == []
    assert await store.find({"kind": "new"}) == [{**key, "kind": "new"}]


@pytest.mark.asyncio
async def test_find_intersects_indexes(store: RedisDocumentStore) -> None:
    """Find intersects indexed filters then applies non-indexed equality filters."""
    await store.put({"user_id": 35, "name": "one", "kind": "x", "version": 1})
    await store.put({"user_id": "35", "name": "two", "kind": "x", "version": 2})
    await store.put({"user_id": 35, "name": "three", "kind": "y", "version": 1})
    assert await store.find({"user_id": "35", "kind": "x", "version": 2}) == [
        {"user_id": "35", "name": "two", "kind": "x", "version": 2}
    ]
    assert len(await store.find()) == 3


@pytest.mark.asyncio
async def test_delete_where_returns_docs(store: RedisDocumentStore) -> None:
    """Delete-where returns precisely the documents it removed."""
    await store.put({"user_id": 1, "name": "one", "kind": "remove"})
    await store.put({"user_id": 1, "name": "two", "kind": "keep"})
    assert await store.delete_where({"kind": "remove"}) == [{"user_id": 1, "name": "one", "kind": "remove"}]
    assert await store.find() == [{"user_id": 1, "name": "two", "kind": "keep"}]


@pytest.mark.asyncio
async def test_concurrent_upserts_keep_indexes(store: RedisDocumentStore) -> None:
    """Concurrent writes retain one document membership across secondary indexes."""
    key = {"user_id": 1, "name": "n"}
    await asyncio.gather(*(store.upsert(key, {"kind": f"k{index % 3}"}) for index in range(20)))
    doc_id = store._doc_id(key)
    memberships = [await store.client.smembers(store._index_key("kind", f"k{index}")) for index in range(3)]
    assert sum(doc_id in members for members in memberships) == 1
    assert await store.client.smembers(store._all_key()) == {doc_id}


@pytest.mark.asyncio
async def test_missing_key_field_raises(store: RedisDocumentStore) -> None:
    """All configured key fields are mandatory."""
    with pytest.raises(ValueError, match="name"):
        await store.get({"user_id": 1})


@pytest.mark.asyncio
async def test_empty_key_part_rejected(store: RedisDocumentStore) -> None:
    """Empty or null key values must not create a blank-identity document."""
    with pytest.raises(ValueError):
        await store.put({"user_id": "", "name": "n", "kind": "x"})
    with pytest.raises(ValueError):
        await store.get({"user_id": "u", "name": ""})


@pytest.mark.asyncio
async def test_find_none_matches_missing_or_null_field(store: RedisDocumentStore) -> None:
    """A ``None`` filter matches documents whose field is absent or null, never a set value."""
    await store.put({"user_id": "u", "name": "a", "kind": "x"})
    await store.put({"user_id": "u", "name": "b", "kind": "x", "tag": None})
    await store.put({"user_id": "u", "name": "c", "kind": "x", "tag": "t"})
    found = await store.find({"user_id": "u", "tag": None})
    assert sorted(doc["name"] for doc in found) == ["a", "b"]
