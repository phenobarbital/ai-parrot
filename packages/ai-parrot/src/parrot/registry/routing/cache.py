"""Asyncio-safe LRU cache for store routing decisions (FEAT-111 Module 6).

``functools.lru_cache`` silently misbehaves on async methods — it caches the
coroutine object instead of the awaited result.  This module provides a small
``asyncio.Lock``-guarded LRU implemented over ``collections.OrderedDict``.

Usage::

    from parrot.registry.routing import DecisionCache, build_cache_key

    cache = DecisionCache(maxsize=256)
    key = build_cache_key(query, ("pgvector", "arango"))
    decision = await cache.get(key)
    if decision is None:
        decision = ... # compute it
        await cache.put(key, decision)
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from typing import Optional

from parrot.registry.routing.models import StoreRoutingDecision

# Normalise a query: lowercase, collapse whitespace.
_WHITESPACE_RE = re.compile(r"\s+")


def build_cache_key(query: str, store_fingerprint: tuple[str, ...]) -> str:
    """Build a stable, compact cache key.

    Normalisation: lowercase + collapse whitespace + strip leading/trailing
    whitespace.  The sorted *store_fingerprint* tuple is included so that a
    change in available stores invalidates stale decisions.

    Args:
        query: Raw user query string.
        store_fingerprint: Sorted tuple of store-type strings (or other stable
            identifiers) that uniquely identifies the current store
            configuration.

    Returns:
        A 40-character hex string (SHA-1).
    """
    normalised = _WHITESPACE_RE.sub(" ", query.lower()).strip()
    # Sort the fingerprint to make key order-independent.
    fp = "|".join(sorted(store_fingerprint))
    raw = f"{normalised}\x00{fp}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


class DecisionCache:
    """Asyncio-safe LRU cache for :class:`~parrot.registry.routing.StoreRoutingDecision`.

    Uses :class:`collections.OrderedDict` + :class:`asyncio.Lock` to provide
    a thread/coroutine-safe LRU without requiring ``functools.lru_cache`` (which
    does not work correctly with async methods).

    .. note::
        Returned ``StoreRoutingDecision`` objects are **not** deep-copied.
        Callers must not mutate them.

    Args:
        maxsize: Maximum number of entries.  ``0`` disables the cache (all
            ``get`` calls return ``None``; ``put`` calls are no-ops).
    """

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[str, StoreRoutingDecision] = OrderedDict()
        import asyncio
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[StoreRoutingDecision]:
        """Retrieve *key* from the cache, promoting it to MRU position.

        Args:
            key: Cache key produced by :func:`build_cache_key`.

        Returns:
            The cached :class:`StoreRoutingDecision`, or ``None`` on miss /
            when the cache is disabled.
        """
        if self._maxsize == 0:
            return None

        async with self._lock:
            if key not in self._data:
                return None
            # Promote to MRU
            self._data.move_to_end(key)
            return self._data[key]

    async def put(self, key: str, decision: StoreRoutingDecision) -> None:
        """Store *decision* under *key*, evicting the LRU entry if needed.

        Args:
            key: Cache key produced by :func:`build_cache_key`.
            decision: Routing decision to cache.  Must not be mutated after
                calling this method.
        """
        if self._maxsize == 0:
            return

        async with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = decision
                return

            self._data[key] = decision
            # Evict LRU entries while over capacity
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)  # last=False → removes LRU (front)
