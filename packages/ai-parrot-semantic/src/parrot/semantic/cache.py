"""LRU of pre-governance CompiledQuery objects only (AC8)."""

from __future__ import annotations

import threading
from collections import OrderedDict

from .models import CompiledQuery


class CompileCache:
    """Thread-safe LRU keyed by ``CompiledQuery.cache_key``; never stores governed SQL."""

    def __init__(self, max_entries: int = 512) -> None:
        """Create a cache holding at most ``max_entries`` entries."""
        self.max_entries = max_entries
        self._data: OrderedDict[str, CompiledQuery] = OrderedDict()
        self._digests: dict[str, str] = {}
        self._lock = threading.Lock()  # compile runs under asyncio.to_thread

    def get(self, key: str) -> CompiledQuery | None:
        """Return the cached compiled query for ``key`` and mark it recently used."""
        with self._lock:
            hit = self._data.get(key)
            if hit is not None:
                self._data.move_to_end(key)
            return hit

    def put(self, compiled: CompiledQuery, *, model_digest: str | None = None) -> None:
        """Insert a compiled query, evicting the oldest entries beyond ``max_entries``."""
        with self._lock:
            key = compiled.cache_key
            self._data[key] = compiled
            self._data.move_to_end(key)
            if model_digest is not None:
                self._digests[key] = model_digest
            while len(self._data) > self.max_entries:
                old, _ = self._data.popitem(last=False)
                self._digests.pop(old, None)

    def invalidate_model(self, model_digest: str) -> int:
        """Drop entries compiled for `model_digest`; returns the count."""
        with self._lock:
            keys = [k for k, d in self._digests.items() if d == model_digest and k in self._data]
            for k in keys:
                self._data.pop(k, None)
                self._digests.pop(k, None)
            return len(keys)
