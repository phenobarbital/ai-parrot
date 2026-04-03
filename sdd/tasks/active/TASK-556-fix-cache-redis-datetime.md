# TASK-556: Fix cache layer — Redis library, race condition, datetime deprecation

**Feature**: FEAT-080 formdesigner-package-fixes
**Status**: pending
**Priority**: critical
**Estimated effort**: small

## Context

Code review found that `services/cache.py` imports `aioredis` which is not installed — the project standard is `redis.asyncio`. Additionally, `_get_redis()` has a race condition on startup, and all `datetime.utcnow()` calls are deprecated in Python 3.12+.

## File

`packages/parrot-formdesigner/src/parrot/formdesigner/services/cache.py`

## Tasks

### 1. Replace `aioredis` with `redis.asyncio` (C1)

**Line ~86-87** — Change:
```python
import aioredis
self._redis = await aioredis.from_url(self._redis_url)
```
To:
```python
from redis.asyncio import Redis
self._redis = await Redis.from_url(self._redis_url)
```

### 2. Add lock to `_get_redis()` initialization (I1)

Wrap the `self._redis is None` check inside `async with self._lock:` to prevent duplicate connections from concurrent coroutines:

```python
async def _get_redis(self) -> Any | None:
    async with self._lock:
        if self._redis is None and self._redis_url:
            try:
                from redis.asyncio import Redis
                self._redis = await Redis.from_url(self._redis_url)
            except ImportError:
                self.logger.warning("redis not installed — Redis caching unavailable")
            except Exception as exc:
                self.logger.warning("Failed to connect to Redis: %s", exc)
    return self._redis
```

### 3. Replace all `datetime.utcnow()` (I3)

Replace every occurrence (lines ~33, 111, 116, 150, 199) with:
```python
from datetime import datetime, timezone
datetime.now(tz=timezone.utc)
```

Also fix `_CacheEntry.last_accessed` default factory:
```python
last_accessed: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
```

### 4. Log Redis close errors instead of bare `pass`

**Line ~282-289** — Change:
```python
except Exception:
    pass
```
To:
```python
except Exception as exc:
    self.logger.debug("Error closing Redis connection: %s", exc)
```

### 5. Document `invalidate_all()` callback behavior

Either fire `_on_invalidate` callbacks for each evicted key in `invalidate_all()`, or add a clear docstring noting that per-key callbacks are NOT fired on bulk invalidation.

## Acceptance Criteria

- [ ] `from redis.asyncio import Redis` used, not `aioredis`
- [ ] `_get_redis()` is thread-safe under concurrent access
- [ ] Zero `datetime.utcnow()` calls remain in cache.py
- [ ] Redis close errors are logged at DEBUG level
- [ ] Unit tests pass
