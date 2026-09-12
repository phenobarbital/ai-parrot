"""Shared fixtures for the dev-loop integration tests (FEAT-555).

``fakeredis`` is not a declared dependency anywhere in this workspace; this
module provides an in-process stand-in mirroring the core dev-loop tests'
``_FakeStreamsRedis`` (packages/ai-parrot/tests/flows/dev_loop/test_streaming.py:26),
extended with the hash/set/expire subset ``RunRegistry`` (TASK-3203) needs.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest


class FakeRedis:
    """In-process stand-in for ``redis.asyncio.Redis`` (decode_responses=True).

    Supports the subset used by TASK-3203/3204: streams (``xadd``/``xread``/
    ``xrange``/``keys``), hashes (``hset``/``hgetall``/``delete``), sets
    (``sadd``/``srem``/``smembers``) and ``expire``.
    """

    def __init__(self) -> None:
        self._streams: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._sets: Dict[str, set] = {}
        self.expirations: Dict[str, int] = {}
        self._counter = 0

    # -- streams ----------------------------------------------------------

    async def xadd(self, key: str, fields: Dict[str, str], **_kw: Any) -> str:
        self._counter += 1
        entry_id = f"{int(time.time() * 1000)}-{self._counter}"
        self._streams.setdefault(key, []).append((entry_id, fields))
        return entry_id

    async def xrange(
        self, name: str, *, min: str = "-", max: str = "+"
    ) -> List[Tuple[str, Dict[str, str]]]:  # noqa: A002
        return list(self._streams.get(name, []))

    async def xread(
        self,
        streams: Dict[str, str],
        *,
        block: Optional[int] = None,
        count: Optional[int] = None,
    ) -> List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]:
        result: List[Tuple[str, List[Tuple[str, Dict[str, str]]]]] = []
        for key, cursor in streams.items():
            entries = self._streams.get(key, [])
            if cursor == "$":
                continue
            collected = [(entry_id, fields) for entry_id, fields in entries if entry_id > cursor]
            if count:
                collected = collected[:count]
            if collected:
                result.append((key, collected))
        if not result and block:
            await asyncio.sleep(block / 1000.0)
        return result

    async def keys(self, pattern: str) -> List[str]:
        # Very rough wildcard handling: only support a trailing '*'.
        names = set(self._streams) | set(self._hashes) | set(self._sets)
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return sorted(k for k in names if k.startswith(prefix))
        return sorted(k for k in names if k == pattern)

    # -- hashes -------------------------------------------------------------

    async def hset(self, key: str, mapping: Optional[Dict[str, str]] = None, **kwargs: Any) -> int:
        data = dict(mapping or {})
        data.update(kwargs)
        self._hashes.setdefault(key, {}).update(data)
        return len(data)

    async def hget(self, key: str, field: str) -> Optional[str]:
        return self._hashes.get(key, {}).get(field)

    async def hgetall(self, key: str) -> Dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            for store in (self._streams, self._hashes, self._sets):
                if key in store:
                    del store[key]
                    removed += 1
            self.expirations.pop(key, None)
        return removed

    # -- sets -----------------------------------------------------------------

    async def sadd(self, key: str, *members: str) -> int:
        s = self._sets.setdefault(key, set())
        before = len(s)
        s.update(members)
        return len(s) - before

    async def srem(self, key: str, *members: str) -> int:
        s = self._sets.get(key, set())
        before = len(s)
        s.difference_update(members)
        return before - len(s)

    async def smembers(self, key: str) -> set:
        return set(self._sets.get(key, set()))

    # -- misc ----------------------------------------------------------------

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations[key] = seconds
        return True

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis() -> FakeRedis:
    """Fresh fake Redis per test."""
    return FakeRedis()
