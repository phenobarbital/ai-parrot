"""Admin UI status endpoint — ``GET /api/v1/admin/status``.

Aggregates server identity/uptime, agent/crew counts, and per-dependency
health (Postgres, Redis, configured vector store) into a single
authenticated JSON payload the Admin UI dashboard renders. The response
models here are also the source for the TS codegen pipeline (TASK-2526) —
keep field names stable and JSON-friendly.

Health probes are individually timeboxed and try/excepted: a dead
dependency degrades its own entry, never the endpoint (never a 500).
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal

from aiohttp import web
from navigator.views import BaseView
from navigator_auth.decorators import is_authenticated, user_session
from pydantic import BaseModel

from ..version import __title__, __version__

#: Short per-probe timeout (seconds) — a dead/slow dependency must never
#: hold up the whole endpoint.
_PROBE_TIMEOUT = 1.5

# Monotonic process-start timestamp, recorded at import time (module load
# happens once, at server startup, before any request is served).
_START_TIME = time.monotonic()


class DependencyHealth(BaseModel):
    """Health of a single external dependency (Postgres, Redis, vector store)."""

    status: Literal["ok", "unreachable", "unconfigured"]
    detail: str | None = None
    latency_ms: float | None = None


class AgentCounts(BaseModel):
    """Agent inventory split by source."""

    database: int
    registry: int
    loaded: int


class AdminStatus(BaseModel):
    """Aggregate server status payload for the Admin UI dashboard."""

    name: str
    version: str
    uptime_seconds: float
    agents: AgentCounts
    crews: int
    dependencies: dict[str, DependencyHealth]


async def _probe_postgres(app: web.Application) -> DependencyHealth:
    """Liveness check for the shared Postgres pool at ``app['database']``.

    Args:
        app: The aiohttp application.

    Returns:
        ``unconfigured`` when no pool is published; ``ok``/``unreachable``
        after a timeboxed ``SELECT 1``.
    """
    db = app.get("database")
    if db is None:
        return DependencyHealth(status="unconfigured")

    async def _check() -> None:
        async with await db.acquire() as conn:
            await conn.execute("SELECT 1")

    start = time.monotonic()
    try:
        await asyncio.wait_for(_check(), timeout=_PROBE_TIMEOUT)
        return DependencyHealth(
            status="ok", latency_ms=(time.monotonic() - start) * 1000
        )
    except Exception as exc:  # noqa: BLE001
        return DependencyHealth(status="unreachable", detail=str(exc))


async def _probe_redis(app: web.Application) -> DependencyHealth:
    """Liveness check for the shared Redis client at ``app['redis']``.

    Args:
        app: The aiohttp application.

    Returns:
        ``unconfigured`` when no client is published; ``ok``/``unreachable``
        after a timeboxed ``PING``.
    """
    redis = app.get("redis")
    if redis is None:
        return DependencyHealth(status="unconfigured")

    start = time.monotonic()
    try:
        await asyncio.wait_for(redis.ping(), timeout=_PROBE_TIMEOUT)
        return DependencyHealth(
            status="ok", latency_ms=(time.monotonic() - start) * 1000
        )
    except Exception as exc:  # noqa: BLE001
        return DependencyHealth(status="unreachable", detail=str(exc))


async def _probe_vector_store(app: web.Application) -> DependencyHealth:
    """Liveness check for the configured vector store, if any.

    This deployment has no single global vector-store handle — each bot
    may carry its own vector store. Note ``AbstractBot._vector_store``
    (``bots/abstract.py:573``) is the raw ``vector_store_config`` dict, NOT
    a store instance — the actual configured/connected ``AbstractStore``
    instance lives at ``AbstractBot.store`` (``bots/abstract.py:577``,
    populated from ``AbstractBot.stores[0]`` during
    ``interfaces/vector.py`` store configuration). Implementation choice
    (spec §8 open question, resolved here): treat the vector store as
    "configured" when at least one currently-loaded bot exposes a non-None
    ``store``, and read its own ``is_connected()`` state — the cheapest
    possible liveness check, with no new connection opened by the probe
    itself. ``unconfigured`` when no loaded bot has a configured store.

    Args:
        app: The aiohttp application.

    Returns:
        The vector store's dependency health.
    """
    bot_manager = app.get("bot_manager")
    store = None
    if bot_manager is not None:
        for bot in bot_manager.get_bots().values():
            candidate = getattr(bot, "store", None)
            if candidate is not None:
                store = candidate
                break

    if store is None:
        return DependencyHealth(status="unconfigured")

    async def _check() -> bool:
        return bool(store.is_connected())

    start = time.monotonic()
    try:
        connected = await asyncio.wait_for(_check(), timeout=_PROBE_TIMEOUT)
        if connected:
            return DependencyHealth(
                status="ok", latency_ms=(time.monotonic() - start) * 1000
            )
        return DependencyHealth(status="unreachable", detail="store not connected")
    except Exception as exc:  # noqa: BLE001
        return DependencyHealth(status="unreachable", detail=str(exc))


async def _count_database_bots(app: web.Application) -> int:
    """Count enabled agents persisted in the database.

    Mirrors the connection-acquisition pattern used by
    ``BotManager._load_database_bots`` (``manager.py:388-402``). Kept
    local to this module rather than added as a new ``BotManager`` method
    per the task's anti-hallucination contract. Timeboxed and
    try/excepted — a DB hiccup degrades the count to 0, never the
    endpoint.

    Args:
        app: The aiohttp application.

    Returns:
        Number of enabled rows in the ``ai_bots`` table, or 0 when the
        database is unavailable/unconfigured.
    """
    db = app.get("database")
    if db is None:
        return 0

    async def _check() -> int:
        from ...handlers.models import (
            BotModel,  # pylint: disable=import-outside-toplevel
        )

        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            bots = await BotModel.filter(enabled=True)
            return len(bots) if bots else 0

    try:
        return await asyncio.wait_for(_check(), timeout=_PROBE_TIMEOUT)
    except Exception:  # noqa: BLE001
        return 0


async def _build_admin_status(app: web.Application) -> AdminStatus:
    """Assemble the :class:`AdminStatus` payload from live server state.

    Args:
        app: The aiohttp application (``app['bot_manager']`` must be set).

    Returns:
        The aggregated status payload.
    """
    bot_manager = app.get("bot_manager")
    loaded_count = len(bot_manager.get_bots()) if bot_manager is not None else 0
    registry_count = (
        len(bot_manager.registry.list_agents())
        if bot_manager is not None and bot_manager.registry is not None
        else 0
    )
    crews_count = len(bot_manager.list_crews()) if bot_manager is not None else 0

    database_count, postgres_health, redis_health, vector_store_health = (
        await asyncio.gather(
            _count_database_bots(app),
            _probe_postgres(app),
            _probe_redis(app),
            _probe_vector_store(app),
            return_exceptions=False,
        )
    )

    return AdminStatus(
        name=__title__,
        version=__version__,
        uptime_seconds=time.monotonic() - _START_TIME,
        agents=AgentCounts(
            database=database_count,
            registry=registry_count,
            loaded=loaded_count,
        ),
        crews=crews_count,
        dependencies={
            "postgres": postgres_health,
            "redis": redis_health,
            "vector_store": vector_store_health,
        },
    )


@is_authenticated()
@user_session()
class AdminStatusHandler(BaseView):
    """``GET /api/v1/admin/status`` — server status/inventory for the dashboard."""

    async def get(self) -> web.Response:
        """Return the current :class:`AdminStatus` payload as JSON.

        Returns:
            A 200 JSON response matching :class:`AdminStatus`. Requires
            an authenticated session (enforced by the class decorators).
        """
        status = await _build_admin_status(self.request.app)
        return self.json_response(status.model_dump(mode="json"))
