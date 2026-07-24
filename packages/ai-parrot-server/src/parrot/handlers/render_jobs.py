"""Redis-backed job store for async infographic renders (FEAT-327, Module 4).

``async=true`` on ``POST /api/v1/agents/infographic/render`` turns a render
into a background job: ``202 {job_id}`` immediately, with the actual render
running as an ``asyncio`` task and its outcome polled via
``GET /api/v1/agents/infographic/render/jobs/{job_id}``.

All job state lives in **Redis** (never process memory) so polling works
regardless of which worker created or rendered the job (resolved decision:
multi-worker safety). Terminal jobs (``done``/``failed``) carry a **1-day
TTL**; non-terminal jobs (``pending``/``running``) carry no TTL — an orphaned
``running`` job (worker died mid-render) is instead caught by the
**max-runtime watchdog**: each job stores a ``deadline`` timestamp, and
:meth:`RenderJobStore.get` flips a past-deadline ``running`` job to
``failed`` at poll time.

This is NEW code — there is no generic KV/job store in ``parrot.memory``
(only ``ConversationMemory`` subclasses); :class:`RenderJobStore` follows
the SAME Redis client-construction pattern as
:class:`~parrot.memory.redis.RedisConversation` but is not a subclass of it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from redis.asyncio import Redis

from parrot.conf import REDIS_HISTORY_URL

from .infographic_render import RenderJob

logger = logging.getLogger(__name__)

#: Redis key prefix for job records.
_KEY_PREFIX = "infographic:job:"

#: TTL (seconds) applied to a job record once it reaches a terminal state
#: (resolved decision: 1 day).
TERMINAL_JOB_TTL_SECONDS = 86400

#: Default max-runtime (seconds) a job may stay ``running`` before the
#: watchdog flips it to ``failed`` (resolved decision: start with 10 minutes).
DEFAULT_MAX_RUNTIME_SECONDS = 600


def resolve_max_runtime_seconds() -> int:
    """Return the max-runtime (seconds) before the watchdog flips a job.

    v1: a constant. Kept behind this single resolver function so a future
    resource-aware computation can replace it without changing
    :class:`RenderJobStore`'s API (resolved decision).

    Returns:
        The max-runtime, in seconds.
    """
    return DEFAULT_MAX_RUNTIME_SECONDS


class RenderJobStore:
    """Redis-backed store for :class:`RenderJob` records.

    Multi-worker safe: ALL state lives in Redis (or an injected Redis-shaped
    client, e.g. a test double) — no process-memory job state.

    Attributes:
        redis_client: The underlying async Redis client (or a test double
            exposing ``set``/``get``/``expire``).
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        *,
        redis_url: Optional[str] = None,
    ) -> None:
        """Construct the store.

        Args:
            redis_client: An existing async Redis-shaped client to use
                (injected for tests). When omitted, a real client is built
                exactly like :class:`~parrot.memory.redis.RedisConversation`.
            redis_url: Overrides ``REDIS_HISTORY_URL`` when building a new
                client (ignored when ``redis_client`` is given).
        """
        self._redis = redis_client or Redis.from_url(
            redis_url or REDIS_HISTORY_URL,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

    @staticmethod
    def _key(job_id: str) -> str:
        """Build the Redis key for a job id."""
        return f"{_KEY_PREFIX}{job_id}"

    async def create(self, job: RenderJob) -> None:
        """Create a new job record (``pending``/``running``) — no TTL.

        Args:
            job: The job record to store.
        """
        await self._redis.set(self._key(job.job_id), job.model_dump_json())

    async def get(self, job_id: str) -> Optional[RenderJob]:
        """Return the job record, applying the watchdog check first.

        A ``running`` job whose ``deadline`` has passed is flipped to
        ``failed`` (with a structured watchdog error) and persisted with the
        terminal TTL before being returned — this is how an orphaned job
        (its worker died mid-render) is recovered, without a background
        daemon (resolved decision: poll-time check only).

        Args:
            job_id: The job identifier.

        Returns:
            The job record, or ``None`` when unknown/expired (the route
            maps this to ``404``).
        """
        raw = await self._redis.get(self._key(job_id))
        if raw is None:
            return None
        job = RenderJob.model_validate_json(raw)
        return await self._apply_watchdog(job)

    async def _apply_watchdog(self, job: RenderJob) -> RenderJob:
        """Flip a past-deadline ``running`` job to ``failed``; else pass through."""
        if job.status != "running":
            return job
        try:
            deadline = datetime.fromisoformat(job.deadline)
        except ValueError:
            return job
        if datetime.now(timezone.utc) <= deadline:
            return job
        failed = job.model_copy(
            update={
                "status": "failed",
                "error": {
                    "code": "watchdog_timeout",
                    "detail": f"max-runtime exceeded (deadline={job.deadline})",
                },
            }
        )
        await self.set_terminal(failed)
        logger.warning("Render job %s flipped to failed by watchdog", job.job_id)
        return failed

    async def set_running(
        self, job_id: str, *, max_runtime_seconds: Optional[int] = None
    ) -> RenderJob:
        """Transition a job to ``running``, stamping a fresh watchdog deadline.

        Args:
            job_id: The job identifier.
            max_runtime_seconds: Overrides :func:`resolve_max_runtime_seconds`.

        Returns:
            The updated job record.

        Raises:
            KeyError: The job does not exist.
        """
        runtime = (
            max_runtime_seconds
            if max_runtime_seconds is not None
            else resolve_max_runtime_seconds()
        )
        job = await self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        deadline = datetime.now(timezone.utc) + timedelta(seconds=runtime)
        updated = job.model_copy(update={"status": "running", "deadline": deadline.isoformat()})
        await self._redis.set(self._key(job_id), updated.model_dump_json())
        return updated

    async def set_terminal(self, job: RenderJob) -> None:
        """Persist a job in a terminal state (``done``/``failed``) with the TTL.

        Args:
            job: The job record, with ``status`` already set to ``done`` or
                ``failed``.
        """
        if job.status not in ("done", "failed"):
            raise ValueError(f"set_terminal() requires a terminal status, got {job.status!r}")
        key = self._key(job.job_id)
        await self._redis.set(key, job.model_dump_json())
        await self._redis.expire(key, TERMINAL_JOB_TTL_SECONDS)


__all__ = (
    "TERMINAL_JOB_TTL_SECONDS",
    "DEFAULT_MAX_RUNTIME_SECONDS",
    "resolve_max_runtime_seconds",
    "RenderJobStore",
)
