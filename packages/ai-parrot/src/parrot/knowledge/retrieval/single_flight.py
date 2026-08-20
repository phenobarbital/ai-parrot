"""Single-flight regeneration lock, keyed on `(page_id, section_kind)`.

Spec §6.2/§6.3. Guards `WikiSection` regeneration to prevent thundering
herd on a hot module after a large merge. Keyed on `(page_id,
section_kind)` — **not** `page_id` — so two requests needing different
sections of the same hot page do not serialize (spec §6.2).

No Redis single-flight lock exists anywhere in `knowledge/` or the
eventbus integration to reuse. The pattern this module follows is
redis-py's `.lock()`, as used in `parrot/auth/oauth2_base.py:519` and
`parrot/auth/jira_oauth.py:523` — copied, not imported, since those
modules solve an unrelated problem (OAuth token refresh). This is new
code for T9, per spec §6.3.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from parrot.knowledge.retrieval.sections import SectionKind

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: Default Redis lock timeout (seconds) — long enough for a section
#: regeneration LLM call, short enough not to wedge a stuck worker's lock
#: forever.
_DEFAULT_LOCK_TIMEOUT = 30.0


class SingleFlight:
    """De-duplicates concurrent regeneration calls for the same section.

    Two layers of protection, both keyed on `(page_id, section_kind)`:

    1. **In-process de-duplication** (always active): concurrent callers
       for the same key join the SAME in-flight coroutine rather than
       each invoking their own — true "single flight" semantics, not just
       mutual exclusion. This works with or without Redis.
    2. **Cross-process Redis lock** (only when a redis client is
       configured): an additional distributed lock so two separate
       worker processes also coalesce. With no Redis configured, this
       layer is skipped and the degradation is logged once.

    Attributes:
        redis: An async redis-py client (`redis.asyncio.Redis`-shaped —
            needs only `.lock()`), or ``None`` to run in-process only.
    """

    def __init__(self, redis: Any | None = None, *, lock_timeout: float = _DEFAULT_LOCK_TIMEOUT) -> None:
        """Construct a `SingleFlight`.

        Args:
            redis: An async redis client, or ``None``.
            lock_timeout: Redis lock timeout in seconds (unused when
                `redis` is ``None``).
        """
        self.redis = redis
        self._lock_timeout = lock_timeout
        self._in_flight: dict[tuple[str, str], asyncio.Future] = {}
        self._registry_lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
        if redis is None:
            self.logger.warning(
                "SingleFlight: no Redis client configured — falling back to an "
                "in-process asyncio-based single-flight only (no cross-process "
                "coordination)"
            )

    @staticmethod
    def _redis_key(page_id: str, section_kind: SectionKind) -> str:
        """Build the Redis lock key for `(page_id, section_kind)`."""
        return f"wiki-single-flight:{page_id}:{section_kind.value}"

    async def run_once(
        self,
        page_id: str,
        section_kind: SectionKind,
        factory: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Run `factory()` at most once per `(page_id, section_kind)` in flight.

        If a call for the same key is already running, this joins it
        instead of invoking `factory` again — the caller gets the SAME
        result the first caller gets (or the same exception).

        Args:
            page_id: The `WikiPage.page_id` being regenerated.
            section_kind: Which `SectionKind` is being regenerated.
            factory: A zero-arg async callable that performs the actual
                regeneration (out of scope here — T10/T11 supply it).

        Returns:
            `factory()`'s result — shared across all callers that joined
            the same in-flight call.
        """
        key = (page_id, section_kind.value)

        async with self._registry_lock:
            future = self._in_flight.get(key)
            is_new = future is None
            if is_new:
                future = asyncio.ensure_future(self._run_and_cleanup(key, section_kind, factory))
                self._in_flight[key] = future

        assert future is not None
        return await future

    async def _run_and_cleanup(
        self,
        key: tuple[str, str],
        section_kind: SectionKind,
        factory: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Run `factory`, optionally under a Redis lock, then clear the in-flight entry."""
        try:
            if self.redis is not None:
                page_id, _ = key
                lock = self.redis.lock(self._redis_key(page_id, section_kind), timeout=self._lock_timeout)
                await lock.acquire()
                try:
                    return await factory()
                finally:
                    await lock.release()
            else:
                return await factory()
        finally:
            async with self._registry_lock:
                self._in_flight.pop(key, None)
