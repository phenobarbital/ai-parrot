import asyncio
import hashlib
import json
from typing import Any, Dict, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field

@dataclass
class CacheEntry:
    """Cache entry with TTL support."""
    value: Any
    expires_at: datetime
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at

    def accessed(self):
        """Track cache hits for analytics."""
        self.hit_count += 1

class TTLCache:
    """Thread-safe TTL cache with memory management."""

    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 300,  # 5 minutes default
        cleanup_interval: int = 60  # Run cleanup every minute
    ):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = asyncio.Lock()
        self._cleanup_task = None
        self._stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0
        }
        self.cleanup_interval = cleanup_interval

    async def start(self):
        """Start the cleanup background task."""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(
                self._periodic_cleanup(self.cleanup_interval)
            )

    async def stop(self):
        """Stop the cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    def _generate_key(self, *args, **kwargs) -> str:
        """Generate cache key from arguments."""
        key_data = {
            'args': args,
            'kwargs': sorted(kwargs.items())
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.md5(key_str.encode()).hexdigest()

    async def get(
        self,
        key: str,
        default: Any = None
    ) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats['misses'] += 1
                return default

            if entry.is_expired:
                del self._cache[key]
                self._stats['misses'] += 1
                return default

            entry.accessed()
            self._stats['hits'] += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None
    ):
        """Set value in cache with TTL."""
        ttl = ttl or self._default_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)

        async with self._lock:
            # Check size limit
            if len(self._cache) >= self._max_size:
                await self._evict_lru()

            self._cache[key] = CacheEntry(
                value=value,
                expires_at=expires_at
            )

    async def invalidate(self, pattern: str = None):
        """Invalidate cache entries matching pattern."""
        async with self._lock:
            if pattern:
                keys_to_remove = [
                    k for k in self._cache.keys()
                    if pattern in k
                ]
                for key in keys_to_remove:
                    del self._cache[key]
            else:
                self._cache.clear()

    async def _evict_lru(self):
        """Evict least recently used entries."""
        if not self._cache:
            return

        # Find oldest entry
        oldest_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].expires_at
        )
        del self._cache[oldest_key]
        self._stats['evictions'] += 1

    async def _periodic_cleanup(self, interval: int):
        """Periodically clean up expired entries."""
        while True:
            try:
                await asyncio.sleep(interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break

    async def _cleanup_expired(self):
        """Remove expired entries."""
        async with self._lock:
            expired_keys = [
                k for k, v in self._cache.items()
                if v.is_expired
            ]
            for key in expired_keys:
                del self._cache[key]

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._stats['hits'] + self._stats['misses']
        hit_rate = (self._stats['hits'] / total * 100) if total > 0 else 0

        return {
            **self._stats,
            'size': len(self._cache),
            'hit_rate': f"{hit_rate:.2f}%"
        }
