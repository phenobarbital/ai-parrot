"""Cross-worker fire coordination for the agent scheduler (FEAT-631)."""

from __future__ import annotations

import logging
import os
import socket
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Awaitable, Callable, Optional, Protocol, Set, runtime_checkable

import redis.asyncio as aioredis
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.base import run_coroutine_job
from apscheduler.util import iscoroutinefunction_partial

from parrot.conf import CACHE_HOST, CACHE_PORT

from .sanitize import SchedulerConfigError, sanitize_redis_settings

logger = logging.getLogger("Parrot.Scheduler.coordination")

DEFAULT_PREFIX = "parrot:scheduler:"
DEFAULT_FIRE_TTL = 86400
DEFAULT_RUN_NOW_TTL = 3600

CURRENT_RUN_TIME: ContextVar[Optional[datetime]] = ContextVar("scheduler_current_run_time", default=None)
# Scheduled run time of the fire being executed; set by CoordinatedAsyncIOExecutor (FEAT-644, aa813ccc1927).


def manager_prefix(registered_name: str) -> str:
    """Return the Redis key prefix owned by one scheduler manager (``parrot:scheduler:<name>:``)."""
    return f"{DEFAULT_PREFIX}{registered_name}:"


def redis_db() -> int:
    """Logical Redis db for jobstore, run state and coordination (``SCHEDULER_REDIS_DB``, default 6)."""
    from navconfig import config as nav_config

    raw = nav_config.get("SCHEDULER_REDIS_DB")
    return int(sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=raw)["db"])


class FireCoordinationError(Exception):
    """The coordination backend could not answer."""


@runtime_checkable
class FireCoordinator(Protocol):
    """Backend contract for scheduled-fire and run-now coordination."""

    worker_id: str

    async def claim(self, job_id: str, run_time: datetime) -> bool: ...

    async def try_acquire_running(self, schedule_id: str) -> bool: ...

    async def release_running(self, schedule_id: str) -> None: ...

    async def close(self) -> None: ...


def _default_worker_id() -> str:
    """Build a process-local identifier suitable for Redis claim values."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class NullFireCoordinator:
    """Single-process coordinator: every fire claim wins."""

    def __init__(self, worker_id: Optional[str] = None) -> None:
        self.worker_id = worker_id or _default_worker_id()
        self._running: Set[str] = set()

    async def claim(self, job_id: str, run_time: datetime) -> bool:
        """Allow every scheduled fire when no shared backend is configured."""
        return True

    async def try_acquire_running(self, schedule_id: str) -> bool:
        """Acquire the in-process run-now guard for a schedule."""
        schedule_key = str(schedule_id)
        if schedule_key in self._running:
            return False
        self._running.add(schedule_key)
        return True

    async def release_running(self, schedule_id: str) -> None:
        """Release the in-process run-now guard for a schedule."""
        self._running.discard(str(schedule_id))

    async def close(self) -> None:
        """Close the coordinator; there are no local resources to release."""
        return None


class RedisFireCoordinator:
    """Coordinate fires and run-now executions using Redis SET NX EX."""

    def __init__(
        self,
        client: "aioredis.Redis",
        *,
        worker_id: Optional[str] = None,
        fire_ttl: int = DEFAULT_FIRE_TTL,
        run_now_ttl: int = DEFAULT_RUN_NOW_TTL,
        prefix: str = DEFAULT_PREFIX,
    ) -> None:
        self._client = client
        self.worker_id = worker_id or _default_worker_id()
        self._fire_ttl = int(fire_ttl)
        self._run_now_ttl = int(run_now_ttl)
        self._prefix = prefix

    async def claim(self, job_id: str, run_time: datetime) -> bool:
        """Atomically claim one scheduled fire."""
        key = f"{self._prefix}fire:{job_id}:{run_time.isoformat()}"
        try:
            result = await self._client.set(key, self.worker_id, nx=True, ex=self._fire_ttl)
        except Exception as exc:
            raise FireCoordinationError(f"Could not claim scheduled fire {job_id!r}") from exc
        return bool(result)

    async def try_acquire_running(self, schedule_id: str) -> bool:
        """Atomically acquire the run-now guard for a schedule."""
        key = f"{self._prefix}running:{schedule_id}"
        try:
            result = await self._client.set(key, self.worker_id, nx=True, ex=self._run_now_ttl)
        except Exception as exc:
            raise FireCoordinationError(f"Could not acquire run-now guard {schedule_id!r}") from exc
        return bool(result)

    async def release_running(self, schedule_id: str) -> None:
        """Release a run-now guard, swallowing backend shutdown failures."""
        key = f"{self._prefix}running:{schedule_id}"
        try:
            await self._client.delete(key)
        except Exception:
            logger.warning("Could not release run-now guard %s", schedule_id, exc_info=True)

    async def close(self) -> None:
        """Close the Redis client without allowing shutdown errors to escape."""
        try:
            close = getattr(self._client, "aclose", None)
            if close is None:
                close = getattr(self._client, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        except Exception:
            logger.warning("Could not close scheduler coordination Redis client", exc_info=True)


def build_fire_coordinator(
    mode: Optional[str] = None, *, use_redis: bool = False, prefix: str = DEFAULT_PREFIX
) -> FireCoordinator:
    """Resolve and build the fire coordinator.

    A Redis jobstore (``use_redis=True``) always yields ``RedisFireCoordinator``: ``none`` from the argument or
    ``SCHEDULER_COORDINATION`` is overridden with a WARNING (FEAT-644 AC14). ``prefix`` namespaces the claim keys.

    Raises:
        SchedulerConfigError: If the resolved mode is unknown.
    """
    from navconfig import config as nav_config

    raw = mode or nav_config.get("SCHEDULER_COORDINATION") or ("redis" if use_redis else "none")
    normalized = str(raw).strip().lower()
    if normalized == "none" and use_redis:
        logger.warning(
            "SCHEDULER_COORDINATION=none ignored: a Redis jobstore is attached, fires must be claimed (FEAT-644)"
        )
        normalized = "redis"
    if normalized == "none":
        return NullFireCoordinator()
    if normalized == "redis":
        fire_ttl = nav_config.get("SCHEDULER_FIRE_LOCK_TTL") or DEFAULT_FIRE_TTL
        run_now_ttl = nav_config.get("SCHEDULER_RUN_NOW_LOCK_TTL") or DEFAULT_RUN_NOW_TTL
        client = aioredis.Redis(**sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=redis_db()))
        return RedisFireCoordinator(client, fire_ttl=int(fire_ttl), run_now_ttl=int(run_now_ttl), prefix=prefix)
    raise SchedulerConfigError(f"Unknown SCHEDULER_COORDINATION {raw!r}; expected 'redis' or 'none'")


UnavailableHook = Callable[[str, BaseException], Awaitable[None]]


class CoordinatedAsyncIOExecutor(AsyncIOExecutor):
    """AsyncIOExecutor whose coroutine jobs first claim their scheduled fire."""

    def __init__(
        self,
        coordinator: Optional[FireCoordinator] = None,
        on_unavailable: Optional[UnavailableHook] = None,
    ) -> None:
        super().__init__()
        self._coordinator: FireCoordinator = coordinator or NullFireCoordinator()
        self._on_unavailable = on_unavailable

    def set_coordinator(self, coordinator: FireCoordinator) -> None:
        """Replace the coordinator after executor construction."""
        self._coordinator = coordinator

    async def _claimed_run(self, job, run_times):
        try:
            won = await self._coordinator.claim(job.id, run_times[-1])
        except FireCoordinationError as exc:
            logger.error("Scheduler coordination unavailable for job %s: %s — skipping fire", job.id, exc)
            if self._on_unavailable:
                try:
                    await self._on_unavailable(job.id, exc)
                except Exception:
                    logger.warning("Scheduler unavailable callback failed for job %s", job.id, exc_info=True)
            return []
        if not won:
            logger.debug("Job %s @ %s claimed by another worker; skipping", job.id, run_times[-1])
            return []
        token = CURRENT_RUN_TIME.set(run_times[-1])
        try:
            return await run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)
        finally:
            CURRENT_RUN_TIME.reset(token)

    def _do_submit_job(self, job, run_times):
        if not iscoroutinefunction_partial(job.func):
            return super()._do_submit_job(job, run_times)

        def callback(f):
            self._pending_futures.discard(f)
            try:
                events = f.result()
            except BaseException:
                self._run_job_error(job.id, *sys.exc_info()[1:])
            else:
                self._run_job_success(job.id, events)

        f = self._eventloop.create_task(self._claimed_run(job, run_times))
        f.add_done_callback(callback)
        self._pending_futures.add(f)
