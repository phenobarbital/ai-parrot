"""LRU of pre-governance CompiledQuery objects only (AC8)."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict

from .models import CompiledQuery


def _model_digest_of(cache_key: str) -> str:
    """Extract the model digest from a canonical JSON cache key.

    The key is a JSON array whose first element is the model digest (or an
    object carrying ``model_digest``).

    Raises:
        ValueError: If the key is not a canonical versioned key.
    """
    try:
        decoded = json.loads(cache_key)
    except (TypeError, ValueError) as exc:
        raise ValueError("cache_key is not canonical JSON") from exc
    if isinstance(decoded, dict) and isinstance(decoded.get("model_digest"), str):
        return decoded["model_digest"]
    if isinstance(decoded, list) and decoded and isinstance(decoded[0], str):
        return decoded[0]
    raise ValueError("cache_key lacks a model digest component")


class CompileCache:
    """Bounded LRU keyed by ``CompiledQuery.cache_key`` with a model-digest index."""

    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self._data: OrderedDict[str, CompiledQuery] = OrderedDict()
        self._by_model: dict[str, set[str]] = {}
        self._key_model: dict[str, str] = {}
        self._lock = threading.Lock()  # compile runs under asyncio.to_thread

    def _drop(self, key: str) -> None:
        self._data.pop(key, None)
        digest = self._key_model.pop(key, None)
        if digest is not None:
            keys = self._by_model.get(digest)
            if keys is not None:
                keys.discard(key)
                if not keys:
                    del self._by_model[digest]

    def get(self, key: str) -> CompiledQuery | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is not None:
                self._data.move_to_end(key)
            return hit

    def put(self, compiled: CompiledQuery) -> None:
        """Insert by ``compiled.cache_key``; evict least-recently-used beyond the bound."""
        key = compiled.cache_key
        digest = _model_digest_of(key)  # validate before any mutation
        with self._lock:
            if key in self._data:
                self._drop(key)
            self._data[key] = compiled
            self._key_model[key] = digest
            self._by_model.setdefault(digest, set()).add(key)
            while len(self._data) > max(self.max_entries, 0):
                oldest = next(iter(self._data))
                self._drop(oldest)

    def invalidate_model(self, model_digest: str) -> int:
        """Drop entries compiled for `model_digest`; returns the count."""
        with self._lock:
            keys = list(self._by_model.get(model_digest, ()))
            for key in keys:
                self._drop(key)
            return len(keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
