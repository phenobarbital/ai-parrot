"""Omission store for per-turn conversation compaction (FEAT-525).

Everything pruned or offloaded from a turn (oversized tool outputs, at
write time or at render time) lands here, content-addressed and indexed
by ``turn_id`` so it can be recovered byte for byte by
``read_omitted_content`` (TASK-2829). Owned by the ``ConversationMemory``
backend (wired in TASK-2826); this module only defines the store.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import aiofiles

from parrot.memory.compaction.models import Omission

logger = logging.getLogger(__name__)

#: Fixed message returned for an unknown or foreign content id. Callers
#: format it with the id they looked up.
EXPIRED_MESSAGE: str = (
    "Omitted content {content_id} is unknown or may have expired — "
    "re-run the tool to regenerate it."
)


def content_id(content: str) -> str:
    """Compute the content-addressed id for a piece of omitted content.

    Args:
        content: The full text being offloaded.

    Returns:
        ``"om_"`` followed by the 16-hex-character blake2b-8 digest of
        ``content``. Identical content always yields the same id.
    """
    digest = hashlib.blake2b(content.encode("utf-8"), digest_size=8).hexdigest()
    return f"om_{digest}"


class OmissionStore(ABC):
    """Content-addressed store for content pruned or offloaded from turns."""

    def __init__(self, *, ttl: Optional[int] = None) -> None:
        """Initialize the store.

        Args:
            ttl: Expiry in seconds for stored content. ``None`` (default)
                means no expiry, matching the history's own lack of a TTL.
        """
        self.ttl = ttl

    @abstractmethod
    async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
        """Store ``content`` under ``session_key``, indexed by ``turn_id``.

        Idempotent: storing the same content twice returns the same id
        and does not create a duplicate index entry.

        Args:
            session_key: Opaque scoping key (composed by the memory).
            content: The full text to store.
            turn_id: When given, indexes the resulting id under this turn.

        Returns:
            The content id.
        """

    async def put_many(self, session_key: str, omissions: Sequence[Omission]) -> None:
        """Store every :class:`Omission` under its own ``turn_id`` (default: loop over :meth:`put`).

        Args:
            session_key: Opaque scoping key (composed by the memory).
            omissions: The omissions to flush.
        """
        for omission in omissions:
            await self.put(session_key, omission.content, turn_id=omission.turn_id)

    @abstractmethod
    async def get(self, session_key: str, content_id: str) -> Optional[str]:
        """Return the stored content for ``content_id``, or ``None`` if unknown.

        Args:
            session_key: Opaque scoping key (composed by the memory).
            content_id: The id returned by a previous :meth:`put`.

        Returns:
            The stored content, or ``None`` when the id is unknown or
            belongs to a different session.
        """

    @abstractmethod
    async def list_by_turn(self, session_key: str, turn_id: str) -> List[str]:
        """Return the content ids stored for ``turn_id``, in insertion order.

        Args:
            session_key: Opaque scoping key (composed by the memory).
            turn_id: The turn to look up.

        Returns:
            A list of content ids (empty when the turn has none).
        """

    @abstractmethod
    async def clear(self, session_key: str) -> None:
        """Delete every stored content and index entry for ``session_key``.

        Args:
            session_key: Opaque scoping key (composed by the memory).
        """


class InMemoryOmissionStore(OmissionStore):
    """Process-local, dict-backed :class:`OmissionStore`."""

    def __init__(self, *, ttl: Optional[int] = None) -> None:
        """Initialize the store (see :class:`OmissionStore`)."""
        super().__init__(ttl=ttl)
        self._content: Dict[str, Dict[str, str]] = {}
        self._turns: Dict[str, Dict[str, List[str]]] = {}

    async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
        cid = content_id(content)
        self._content.setdefault(session_key, {})[cid] = content
        if turn_id is not None:
            ids = self._turns.setdefault(session_key, {}).setdefault(turn_id, [])
            if cid not in ids:
                ids.append(cid)
        return cid

    async def get(self, session_key: str, content_id: str) -> Optional[str]:
        return self._content.get(session_key, {}).get(content_id)

    async def list_by_turn(self, session_key: str, turn_id: str) -> List[str]:
        return list(self._turns.get(session_key, {}).get(turn_id, []))

    async def clear(self, session_key: str) -> None:
        self._content.pop(session_key, None)
        self._turns.pop(session_key, None)


class RedisOmissionStore(OmissionStore):
    """Redis-backed :class:`OmissionStore`, sharing an existing async client."""

    def __init__(self, redis_client, *, key_prefix: str = "conversation", ttl: Optional[int] = None) -> None:
        """Initialize the store.

        Args:
            redis_client: An already-constructed async Redis client (the
                same one ``RedisConversation`` owns — never opens a
                second connection).
            key_prefix: Prefix for the two hashes this store owns.
            ttl: Expiry in seconds. ``None`` (default) means no expiry.
        """
        super().__init__(ttl=ttl)
        self._redis = redis_client
        self._prefix = key_prefix

    def _content_key(self, session_key: str) -> str:
        return f"{self._prefix}_omitted:{session_key}"

    def _turns_key(self, session_key: str) -> str:
        return f"{self._prefix}_omitted_turns:{session_key}"

    async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
        cid = content_id(content)
        await self._redis.hset(self._content_key(session_key), cid, content)
        if turn_id is not None:
            turns_key = self._turns_key(session_key)
            raw = await self._redis.hget(turns_key, turn_id)
            ids: List[str] = json.loads(raw) if raw else []
            if cid not in ids:
                ids.append(cid)
                await self._redis.hset(turns_key, turn_id, json.dumps(ids))
        if self.ttl is not None:
            await self._redis.expire(self._content_key(session_key), self.ttl)
            await self._redis.expire(self._turns_key(session_key), self.ttl)
        return cid

    async def get(self, session_key: str, content_id: str) -> Optional[str]:
        return await self._redis.hget(self._content_key(session_key), content_id)

    async def list_by_turn(self, session_key: str, turn_id: str) -> List[str]:
        raw = await self._redis.hget(self._turns_key(session_key), turn_id)
        return json.loads(raw) if raw else []

    async def clear(self, session_key: str) -> None:
        await self._redis.delete(self._content_key(session_key))
        await self._redis.delete(self._turns_key(session_key))


class FileOmissionStore(OmissionStore):
    """File-backed :class:`OmissionStore`.

    Layout: ``{base_path}/_omitted/{safe(session_key)}/{content_id}.txt``
    plus an ``index.json`` mapping ``turn_id -> [content_id, ...]``.
    """

    def __init__(self, base_path, *, ttl: Optional[int] = None) -> None:
        """Initialize the store.

        Args:
            base_path: Root directory (shared with ``FileConversationMemory``).
            ttl: Ignored — the file backend has no expiry mechanism.
        """
        super().__init__(ttl=ttl)
        if ttl is not None:
            logger.debug("FileOmissionStore has no expiry mechanism; ignoring ttl=%s", ttl)
        self._root = Path(base_path) / "_omitted"
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(session_key: str) -> str:
        """Replace path-hostile characters in a session key."""
        return session_key.replace(":", "__").replace("/", "__")

    def _session_dir(self, session_key: str) -> Path:
        return self._root / self._safe(session_key)

    def _index_path(self, session_key: str) -> Path:
        return self._session_dir(session_key) / "index.json"

    async def _read_index(self, session_key: str) -> Dict[str, List[str]]:
        path = self._index_path(session_key)
        if not path.exists():
            return {}
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw) if raw else {}

    async def _write_index(self, session_key: str, index: Dict[str, List[str]]) -> None:
        path = self._index_path(session_key)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(index))

    async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
        cid = content_id(content)
        session_dir = self._session_dir(session_key)
        session_dir.mkdir(parents=True, exist_ok=True)
        content_path = session_dir / f"{cid}.txt"
        if not content_path.exists():
            async with aiofiles.open(content_path, "w", encoding="utf-8") as f:
                await f.write(content)
        if turn_id is not None:
            index = await self._read_index(session_key)
            ids = index.setdefault(turn_id, [])
            if cid not in ids:
                ids.append(cid)
                await self._write_index(session_key, index)
        return cid

    async def get(self, session_key: str, content_id: str) -> Optional[str]:
        path = self._session_dir(session_key) / f"{content_id}.txt"
        if not path.exists():
            return None
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return await f.read()

    async def list_by_turn(self, session_key: str, turn_id: str) -> List[str]:
        index = await self._read_index(session_key)
        return list(index.get(turn_id, []))

    async def clear(self, session_key: str) -> None:
        session_dir = self._session_dir(session_key)
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
