"""Worker / startup helpers for JobManager configuration.

Provides convenience functions to wire up a ``JobManager`` (with or without
Redis persistence) into an aiohttp ``Application``.
"""
from __future__ import annotations

from typing import Optional

from aiohttp import web

from .job import JobManager


def configure_job_manager(
    app: web.Application,
    *,
    use_redis: bool = False,
    redis_url: Optional[str] = None,
    key_prefix: str = "parrot:jobs",
    job_ttl: int = 86400,
) -> JobManager:
    """Configure and register a JobManager on the aiohttp Application.

    Args:
        app: The aiohttp Application instance.
        use_redis: When True, attach a RedisJobStore for durable persistence.
        redis_url: Override Redis connection URL.  Defaults to
            ``REDIS_SERVICES_URL`` from ``parrot.conf``.
        key_prefix: Redis key prefix for all job hashes.
        job_ttl: TTL in seconds for completed/failed jobs in Redis.

    Returns:
        The configured JobManager (also stored in ``app['job_manager']``).

    Example::

        # Simple in-memory (default)
        configure_job_manager(app)

        # Redis-backed (persistent across restarts)
        configure_job_manager(app, use_redis=True)
    """
    store = None
    if use_redis:
        from .redis_store import RedisJobStore  # pylint: disable=import-outside-toplevel

        store = RedisJobStore(
            redis_url=redis_url,
            key_prefix=key_prefix,
            job_ttl=job_ttl,
        )

    manager = JobManager(store=store, job_ttl=job_ttl)
    app["job_manager"] = manager

    async def _start(application: web.Application) -> None:
        await application["job_manager"].start()

    async def _stop(application: web.Application) -> None:
        await application["job_manager"].stop()

    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)
    return manager
