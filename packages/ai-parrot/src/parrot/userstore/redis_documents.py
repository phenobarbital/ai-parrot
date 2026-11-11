"""Keyed JSON documents with secondary indexes over redis.asyncio (FEAT-878)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import redis.asyncio as aioredis
from redis.exceptions import WatchError

from .collections import CollectionSpec
from .settings import get_user_store_redis, key_prefix

_MAX_RETRIES = 5
_BATCH_SIZE = 100


def _json_default(value: Any) -> str:
    """Serialize date-like values as ISO strings and other values as strings."""
    return value.isoformat() if isinstance(value, (datetime, date)) else str(value)


def _dumps(document: Mapping[str, Any]) -> str:
    """Encode a document deterministically for Redis."""
    return json.dumps(dict(document), default=_json_default, sort_keys=True)


class RedisDocumentStore:
    """Keyed JSON documents for one CollectionSpec. Equality filters only; no TTL."""

    def __init__(
        self,
        spec: CollectionSpec,
        *,
        client: aioredis.Redis | None = None,
        prefix: str | None = None,
    ) -> None:
        self.spec = spec
        self._client = client
        self._prefix = prefix
        self.logger = logging.getLogger("parrot.userstore.redis")

    @property
    def client(self) -> aioredis.Redis:
        """Return the injected client or the per-loop user-store client."""
        return self._client or get_user_store_redis()

    def _base(self) -> str:
        return f"{self._prefix or key_prefix()}:{self.spec.name}"

    def _doc_id(self, key: Mapping[str, Any]) -> str:
        """Return encoded key parts, rejecting missing or null key values."""
        values: list[str] = []
        for field in self.spec.key_fields:
            value = key.get(field)
            if value is None:
                raise ValueError(f"Missing key field: {field}")
            values.append(quote(str(value), safe=""))
        return ":".join(values)

    def _doc_key(self, doc_id: str) -> str:
        return f"{self._base()}:d:{doc_id}"

    def _index_key(self, field: str, value: Any) -> str:
        return f"{self._base()}:i:{field}:{quote(str(value), safe='')}"

    def _all_key(self) -> str:
        return f"{self._base()}:all"

    async def _write(
        self,
        doc_id: str,
        build: Callable[[dict[str, Any] | None], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        """Apply one watched document mutation and maintain its secondary indexes."""
        doc_key = self._doc_key(doc_id)
        for _attempt in range(_MAX_RETRIES):
            try:
                async with self.client.pipeline(transaction=True) as pipe:
                    await pipe.watch(doc_key)
                    raw = await pipe.get(doc_key)
                    old = json.loads(raw) if raw else None
                    new = build(old)
                    pipe.multi()
                    if new is None:
                        pipe.delete(doc_key)
                    else:
                        pipe.set(doc_key, _dumps(new))

                    for field in self.spec.index_fields:
                        old_value = old.get(field) if old is not None else None
                        new_value = new.get(field) if new is not None else None
                        if old_value is not None and (new_value is None or str(old_value) != str(new_value)):
                            pipe.srem(self._index_key(field, old_value), doc_id)
                        if new_value is not None and (old_value is None or str(old_value) != str(new_value)):
                            pipe.sadd(self._index_key(field, new_value), doc_id)

                    if new is None:
                        pipe.srem(self._all_key(), doc_id)
                    elif old is None:
                        pipe.sadd(self._all_key(), doc_id)
                    await pipe.execute()
                    return old if new is None else new
            except WatchError:
                continue
        raise RuntimeError("Redis document write conflicted too many times")

    async def get(self, key: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return the document for the full key, or None."""
        raw = await self.client.get(self._doc_key(self._doc_id(key)))
        return json.loads(raw) if raw else None

    async def exists(self, key: Mapping[str, Any]) -> bool:
        """Return whether a document with the full key exists."""
        return bool(await self.client.exists(self._doc_key(self._doc_id(key))))

    async def put(self, document: Mapping[str, Any]) -> None:
        """Replace the whole document, taking its key from the document."""
        clean = {name: value for name, value in document.items() if name != "_id"}
        await self._write(self._doc_id(clean), lambda _old: clean)

    async def create(self, document: Mapping[str, Any]) -> bool:
        """Insert only when absent and report whether a document was created."""
        clean = {name: value for name, value in document.items() if name != "_id"}
        created = False

        def build(old: dict[str, Any] | None) -> dict[str, Any]:
            nonlocal created
            created = old is None
            return clean if created else old

        await self._write(self._doc_id(clean), build)
        return created

    async def upsert(
        self,
        key: Mapping[str, Any],
        set_fields: Mapping[str, Any],
        *,
        on_insert: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply $set/$setOnInsert semantics and return the stored document."""

        def build(old: dict[str, Any] | None) -> dict[str, Any]:
            document = dict(old) if old is not None else {**key, **(on_insert or {})}
            document.update(set_fields)
            return document

        result = await self._write(self._doc_id(key), build)
        assert result is not None
        return result

    async def update(self, key: Mapping[str, Any], set_fields: Mapping[str, Any]) -> bool:
        """Merge fields into an existing document without creating one."""

        def build(old: dict[str, Any] | None) -> dict[str, Any] | None:
            if old is None:
                return None
            return {**old, **set_fields}

        return (await self._write(self._doc_id(key), build)) is not None

    async def delete(self, key: Mapping[str, Any]) -> bool:
        """Delete a document and return whether it was present."""
        return (await self._write(self._doc_id(key), lambda _old: None)) is not None

    async def find(self, where: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return documents matching every equality filter in ``where``."""
        filters = dict(where or {})
        if all(field in filters for field in self.spec.key_fields):
            document = await self.get(filters)
            return [document] if document and self._matches(document, filters) else []

        indexed_keys = [self._index_key(field, filters[field]) for field in self.spec.index_fields if field in filters]
        doc_ids = (
            await self.client.sinter(indexed_keys) if indexed_keys else await self.client.smembers(self._all_key())
        )
        return [document for document in await self._documents(doc_ids) if self._matches(document, filters)]

    async def delete_where(self, where: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Delete and return each document matching ``where``."""
        deleted: list[dict[str, Any]] = []
        for document in await self.find(where):
            if await self.delete(document):
                deleted.append(document)
        return deleted

    async def scan(self) -> AsyncIterator[dict[str, Any]]:
        """Yield every document in encoded-id order, skipping stale index entries."""
        for document in await self._documents(await self.client.smembers(self._all_key())):
            yield document

    async def _documents(self, doc_ids: set[str]) -> list[dict[str, Any]]:
        """Load non-stale documents in encoded-id order."""
        documents: list[dict[str, Any]] = []
        ordered_ids = sorted(doc_ids)
        for index in range(0, len(ordered_ids), _BATCH_SIZE):
            values = await self.client.mget(
                [self._doc_key(doc_id) for doc_id in ordered_ids[index : index + _BATCH_SIZE]]
            )
            documents.extend(json.loads(raw) for raw in values if raw is not None)
        return documents

    @staticmethod
    def _matches(document: Mapping[str, Any], where: Mapping[str, Any]) -> bool:
        """Return whether every filter has matching string representation."""
        return all(str(document.get(field)) == str(value) for field, value in where.items())
