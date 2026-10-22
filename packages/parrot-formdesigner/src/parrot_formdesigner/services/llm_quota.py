"""Server-side quota for LLM-backed form calls (FEAT-728).

Public forms expose ``/validate`` and ``/data`` without authentication
(services/public_forms.py:13), and both can reach the LLM plausibility
checker. This module bounds those calls per identity and form. It is never
configured from form schema — a tenant must not be able to raise its own
limit (spec AC14).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Callable, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from aiohttp import web

__all__ = ["LLMQuota", "LLMQuotaBackend", "InProcessSlidingWindow", "QuotaDecision"]

logger = logging.getLogger(__name__)


class QuotaDecision(BaseModel):
    """One limiter answer."""

    allowed: bool
    retry_after_s: int = Field(default=0, ge=0)


class LLMQuotaBackend(Protocol):
    """Swap-in point for a shared limiter (e.g. Redis) — see spec §8 Q2."""

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        """Charge one call to ``key``; return whether it is allowed."""
        ...


class InProcessSlidingWindow:
    """Per-key sliding window on a monotonic clock, bounded by LRU eviction.

    Per-worker state: with N gunicorn workers the effective limit is N times
    the configured one (spec §7). ``max_keys`` caps adversarial key growth
    from anonymous IPs; the least-recently-used key is evicted at the cap.
    """

    def __init__(self, *, max_keys: int = 4096, clock: Callable[[], float] | None = None) -> None:
        self._max_keys = max_keys
        self._clock = clock or time.monotonic
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        """Charge one call to ``key``.

        Returns ``allowed=False`` with the seconds until the oldest hit in the
        window expires (always >= 1 when denied, so ``Retry-After`` is useful).
        """
        now = self._clock()
        async with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            self._hits.move_to_end(key)

            # Prune hits older than `now - window_s`
            while hits and hits[0] < now - window_s:
                hits.popleft()

            if len(hits) < limit:
                # Allow: append current time
                hits.append(now)
            else:
                # Deny: compute retry_after_s from hits[0]
                retry_after_s = max(1, math.ceil(hits[0] + window_s - now))  # Always >= 1
                return QuotaDecision(allowed=False, retry_after_s=retry_after_s)

            # Evict LRU key while len(self._hits) > self._max_keys
            while len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)

            return QuotaDecision(allowed=True)


class LLMQuota:
    """Quota for LLM-backed form calls, keyed by ``{tenant}:{form_uid}:{identity}``."""

    def __init__(
        self,
        backend: LLMQuotaBackend | None = None,
        *,
        enabled: bool = True,
        limit: int = 10,
        window_s: float = 60.0,
        trust_forwarded_for: bool = False,
    ) -> None:
        self.backend: LLMQuotaBackend = backend or InProcessSlidingWindow()
        self.enabled = enabled
        self.limit = limit
        self.window_s = window_s
        self.trust_forwarded_for = trust_forwarded_for
        self.logger = logging.getLogger(__name__)

    def identity(self, request: "web.Request") -> str:
        """The caller's quota identity.

        The authenticated user id when navigator populated a session
        (verified: api/handlers.py:576-580), else the client IP —
        ``X-Forwarded-For``'s first hop only when ``trust_forwarded_for`` is on,
        because that header is client-settable.
        """
        # Session id first, then forwarded-for (guarded), then request.remote,
        # then the literal "anonymous" when everything is None
        session_id: str | None = None
        session = request.get("session")  # navigator-auth sets this to None for anonymous callers
        if session is not None:
            _sid = session.get("id")
            session_id = str(_sid) if _sid else None

        if session_id is not None:
            return session_id

        # Guarded forwarded-for: only use when explicitly trusted
        if self.trust_forwarded_for:
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                # First hop only (spec §7 "Proxies collapse identities")
                first_hop = forwarded_for.split(",")[0].strip()
                if first_hop:
                    return first_hop

        # Fall back to request.remote
        remote = request.remote
        if remote is not None:
            return remote

        # Everything is None: anonymous
        return "anonymous"

    async def acquire(self, request: "web.Request", *, tenant: str | None, form_uid: str) -> QuotaDecision:
        """Charge one LLM call. Always allows when ``enabled`` is False.

        Never raises: a backend failure is logged and allowed, because a limiter
        outage must not take the submit path down with it.
        """
        if not self.enabled:
            return QuotaDecision(allowed=True)
        key = f"{tenant or '-'}:{form_uid}:{self.identity(request)}"
        try:
            return await self.backend.acquire(key, limit=self.limit, window_s=self.window_s)
        except Exception as exc:  # noqa: BLE001 — a limiter outage must not break submissions
            self.logger.warning("LLM quota backend failed (%s); allowing the call", type(exc).__name__)
            return QuotaDecision(allowed=True)
