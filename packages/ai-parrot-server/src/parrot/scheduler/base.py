"""Target-agnostic scheduler base (FEAT-644): resolver contract and registry."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from enum import Enum
from typing import Any, Callable, Dict, Optional, Protocol, Sequence, Set, runtime_checkable

import redis.asyncio as aioredis
from aiohttp import web
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from asyncdb import AsyncDB
from navigator.connections import PostgresPool
from navconfig import config as nav_config
from parrot.conf import CACHE_HOST, CACHE_PORT, default_dsn

from . import jobs
from .coordination import (
    CoordinatedAsyncIOExecutor,
    FireCoordinator,
    NullFireCoordinator,
    build_fire_coordinator,
    manager_prefix,
    redis_db,
)
from .models import CodeJobRecord
from .models import FireContext, JobDefinition, utcnow
from .runstate import MemoryRunState, PostgresRunState, RedisRunState, RunStateStore
from .sanitize import (
    SchedulerConfigError,
    clean_int,
    normalize_schedule_type,
    sanitize_redis_settings,
    sanitize_schedule_config,
)

__all__ = (
    "ScheduleType",
    "TargetMissingError",
    "SchedulerUnavailableError",
    "NotEditableError",
    "SchedulerRunNowConflictError",
    "TargetResolver",
    "TargetRegistry",
    "RegistryResolver",
    "apply_prompt_signature",
    "inject_fire_context",
    "utcnow",
    "SchedulerManager",
)

logger = logging.getLogger("Parrot.Scheduler")

_RUN_NOW_JOB_PREFIX = "run_now:"
_FIRE_CONTEXT_PARAMS = ("fire_id", "scheduled_at")


class ScheduleType(Enum):
    """Schedule execution types."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    INTERVAL = "interval"
    CRON = "cron"
    CRONTAB = "crontab"


class TargetMissingError(LookupError):
    """The target is unavailable in this process."""


class SchedulerUnavailableError(RuntimeError):
    """Coordination backend or jobstore is unavailable."""


class NotEditableError(ValueError):
    """A code-declared or external job cannot be mutated."""


class SchedulerRunNowConflictError(Exception):
    """A run-now execution is already active for the schedule."""


@runtime_checkable
class TargetResolver(Protocol):
    """Strategy resolving a ``target_kind`` to a live object."""

    kind: str

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None: ...

    def derive_target_id(self, target: Any) -> str | None: ...

    def build_call(
        self, target: Any, definition: JobDefinition, fire: FireContext
    ) -> tuple[list[Any], dict[str, Any]]: ...


class TargetRegistry:
    """Manager-scoped explicit registrations, keyed by ``(kind, name)``."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], Any] = {}
        self._methods: dict[tuple[str, str], frozenset[str]] = {}

    def register(self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None) -> None:
        """Register ``obj`` with an optional public-method allowlist."""
        key = (kind, name)
        if methods is None:
            self._methods.pop(key, None)
        else:
            allowed_methods = frozenset(methods)
            if any(not method.isidentifier() or method.startswith("_") for method in allowed_methods):
                raise ValueError("methods must be public Python identifiers")
            self._methods[key] = allowed_methods
        self._objects[key] = obj

    def unregister(self, name: str, *, kind: str = "service") -> None:
        """Remove a target and its allowlist if registered."""
        key = (kind, name)
        self._objects.pop(key, None)
        self._methods.pop(key, None)

    def get(self, name: str, *, kind: str = "service") -> Any | None:
        """Return a registered target, or ``None`` when absent."""
        return self._objects.get((kind, name))

    def allowed_methods(self, name: str, *, kind: str = "service") -> frozenset[str] | None:
        """Return the target method allowlist, if one was registered."""
        return self._methods.get((kind, name))


def apply_prompt_signature(
    method: Any, call_args: list[Any], call_kwargs: dict[str, Any], prompt: Any
) -> tuple[list[Any], dict[str, Any]]:
    """Inject ``prompt`` into a call according to its signature."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return call_args, call_kwargs

    positional_params = [
        param
        for param in signature.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if positional_params:
        call_kwargs.setdefault(positional_params[0].name, prompt)
        return call_args, call_kwargs

    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()):
        call_args.append(prompt)
        return call_args, call_kwargs

    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
        call_kwargs.setdefault("prompt", prompt)
    return call_args, call_kwargs


def inject_fire_context(method: Any, call_kwargs: dict[str, Any], fire: FireContext) -> dict[str, Any]:
    """Add fire context when the target signature accepts it."""
    try:
        signature = inspect.signature(inspect.unwrap(method))
    except (TypeError, ValueError):
        return call_kwargs

    accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
    for name in _FIRE_CONTEXT_PARAMS:
        if name not in call_kwargs and (name in signature.parameters or accepts_kwargs):
            call_kwargs[name] = getattr(fire, name)
    return call_kwargs


class RegistryResolver:
    """``service`` kind: objects registered via ``register_target``."""

    kind: str = "service"

    def __init__(self, registry: TargetRegistry) -> None:
        self._registry = registry

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
        """Return the registered object or ``None`` without raising."""
        return self._registry.get(name, kind=self.kind)

    def derive_target_id(self, target: Any) -> str | None:
        """Return no ID because services carry none."""
        return None

    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
        """Validate the service method and build its arguments."""
        method_name = definition.method_name
        if method_name is None:
            raise ValueError("method_name is required for service schedules")
        if method_name.startswith("_"):
            raise ValueError("method_name must be a public identifier")

        allowed_methods = self._registry.allowed_methods(definition.target_name, kind=self.kind)
        if allowed_methods is not None and method_name not in allowed_methods:
            raise ValueError(f"method {method_name!r} not allowed for service {definition.target_name!r}")

        method = getattr(target, method_name)
        if not callable(method):
            raise ValueError(f"method {method_name!r} is not callable")

        call_args: list[Any] = []
        call_kwargs = dict(definition.metadata)
        if definition.prompt is not None:
            call_args, call_kwargs = apply_prompt_signature(method, call_args, call_kwargs, definition.prompt)
        return call_args, inject_fire_context(method, call_kwargs, fire)


class SchedulerManager:
    """Target-agnostic scheduler: APScheduler + Postgres/Redis/code backends (FEAT-644)."""

    registered_name: str = "scheduler_manager"

    def __init__(self, **kwargs: Any) -> None:
        """Build the scheduler and register it for persisted job entrypoints."""
        self.logger = logger
        self.app: web.Application | None = None
        self.db: AsyncDB | None = None
        self._pool: AsyncDB | None = None
        self._owns_pool = False
        self._job_context: Dict[str, Dict[str, Any]] = {}
        self._pending_success_tasks: Set[asyncio.Task[Any]] = set()
        self.registered_name = kwargs.get("registered_name", self.registered_name)
        self._fire_coordinator: FireCoordinator = NullFireCoordinator()
        self._local_callbacks: Dict[str, Callable[..., Any]] = {}
        self.targets = TargetRegistry()
        self._resolvers: dict[str, TargetResolver] = {"service": RegistryResolver(self.targets)}
        self._code_jobs: dict[str, CodeJobRecord] = {}
        self._memory_state = MemoryRunState()
        self._redis_client: aioredis.Redis | None = None
        self._max_failures = clean_int(
            nav_config.get("SCHEDULER_MAX_CONSECUTIVE_FAILURES"),
            default=3,
            minimum=1,
            field="SCHEDULER_MAX_CONSECUTIVE_FAILURES",
        )
        self._alert_recipients = [
            recipient.strip()
            for recipient in str(nav_config.get("SCHEDULER_ALERT_RECIPIENTS") or "").split(",")
            if recipient.strip()
        ]
        jobs.register_manager(self)

        executors = {"default": CoordinatedAsyncIOExecutor(on_unavailable=self._on_coordination_unavailable)}
        job_defaults = {"coalesce": True, "max_instances": 2, "misfire_grace_time": 300}
        self.scheduler = AsyncIOScheduler(
            jobstores=self._build_jobstores(use_redis=False),
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:
        """Provide the lifecycle hook implemented by the fire-path slice."""
        self.logger.warning("Scheduler coordination unavailable for %s: %s", job_id, exc)

    def register_resolver(self, resolver: TargetResolver) -> None:
        """Install or replace the resolver for ``resolver.kind``."""
        self._resolvers[resolver.kind] = resolver

    def register_target(
        self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None
    ) -> None:
        """Explicitly register a target consulted first by every resolver."""
        self.targets.register(name, obj, kind=kind, methods=methods)

    @property
    def redis_available(self) -> bool:
        """Return whether the Redis jobstore is attached."""
        return "redis" in self._registered_jobstores()

    def _build_jobstores(self, use_redis: bool = False) -> Dict[str, Any]:
        """Build the APScheduler stores, always including in-memory jobs."""
        jobstores: Dict[str, Any] = {"default": MemoryJobStore()}
        if use_redis:
            jobstores["redis"] = self._make_redis_jobstore()
        return jobstores

    def _make_redis_jobstore(self) -> RedisJobStore:
        """Build a Redis jobstore whose keys belong exclusively to this manager."""
        prefix = manager_prefix(self.registered_name)
        return RedisJobStore(
            jobs_key=f"{prefix}jobs",
            run_times_key=f"{prefix}run_times",
            **sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=redis_db()),
        )

    def _ensure_redis_jobstore(self) -> None:
        """Attach the Redis jobstore once, allowing repeat headless starts."""
        try:
            self.scheduler.add_jobstore(self._make_redis_jobstore(), alias="redis")
        except ValueError:
            pass

    def _registered_jobstores(self) -> Set[str]:
        """Return the aliases currently registered with APScheduler."""
        aliases = {"default"}
        aliases.update(getattr(self.scheduler, "_jobstores", {}) or {})
        return aliases

    def _create_trigger(self, schedule_type: str, config: Dict[str, Any]) -> Any:
        """Create an APScheduler trigger from a normalized schedule configuration."""
        schedule_type = normalize_schedule_type(schedule_type)
        config = sanitize_schedule_config(schedule_type, config)

        if schedule_type == ScheduleType.ONCE.value:
            return DateTrigger(run_date=config.get("run_date", utcnow()))
        if schedule_type == ScheduleType.DAILY.value:
            return CronTrigger(hour=config["hour"], minute=config["minute"])
        if schedule_type == ScheduleType.WEEKLY.value:
            return CronTrigger(day_of_week=config["day_of_week"], hour=config["hour"], minute=config["minute"])
        if schedule_type == ScheduleType.MONTHLY.value:
            return CronTrigger(day=config["day"], hour=config["hour"], minute=config["minute"])
        if schedule_type == ScheduleType.INTERVAL.value:
            return IntervalTrigger(**config)
        if schedule_type == ScheduleType.CRON.value:
            return CronTrigger(**config)
        if schedule_type == ScheduleType.CRONTAB.value:
            return CronTrigger.from_crontab(**config, timezone="UTC")
        raise SchedulerConfigError(f"Unsupported schedule type: {schedule_type}")

    async def _get_connection_pool(self) -> AsyncDB:
        """Return the injected pool, or create the default scheduler pool."""
        if self._pool is not None:
            return self._pool
        if self.app and "agentdb" in self.app:
            self._pool = self.app["agentdb"]
            return self._pool
        self._pool = AsyncDB("pg", dsn=default_dsn)
        await self._pool.connection()
        return self._pool

    def _run_state_for(self, backend: str) -> RunStateStore:
        """Return the dedicated run-state store for the given persistence backend."""
        normalized = str(backend).strip().lower()
        if normalized == "db":
            if self._pool is None:
                raise SchedulerUnavailableError("Database run state is unavailable without a connection pool")
            return PostgresRunState(self._pool.acquire)
        if normalized == "redis":
            if self._redis_client is None:
                raise SchedulerUnavailableError("Redis run state is unavailable without a Redis client")
            return RedisRunState(self._redis_client, prefix=f"{manager_prefix(self.registered_name)}runstate:")
        if normalized == "code":
            return self._memory_state
        raise ValueError(f"Unsupported scheduler backend: {backend!r}")

    async def start_headless(
        self,
        *,
        dsn: Optional[str] = None,
        use_redis: bool = False,
        register_listeners: bool = True,
        coordination: Optional[str] = None,
    ) -> None:
        """Boot the scheduler without aiohttp in the required resource order."""
        if use_redis:
            self._ensure_redis_jobstore()
            if self._redis_client is None:
                self._redis_client = aioredis.Redis(
                    **sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=redis_db()),
                    decode_responses=True,
                )

        if dsn is not None and self._pool is None:
            self._pool = AsyncDB("pg", dsn=dsn)
            await self._pool.connection()
            self._owns_pool = True

        if register_listeners:
            self.define_listeners()

        self._fire_coordinator = build_fire_coordinator(
            coordination,
            use_redis=use_redis,
            prefix=manager_prefix(self.registered_name),
        )
        executor = self.scheduler._lookup_executor("default")
        if isinstance(executor, CoordinatedAsyncIOExecutor):
            executor.set_coordinator(self._fire_coordinator)

        if not self.scheduler.running:
            self.scheduler.start()

        if self._pool is not None:
            await self.load_schedules_from_db()

        self.logger.info("Scheduler started (headless)")

    async def stop_headless(self, *, wait: bool = True) -> None:
        """Stop owned scheduler resources and remove the jobs registry entry."""
        if self.scheduler.running:
            with contextlib.suppress(Exception):
                self.scheduler.shutdown(wait=wait)

        if self._owns_pool and self._pool is not None:
            with contextlib.suppress(Exception):
                await self._pool.close()
            self._pool = None
            self._owns_pool = False

        if self._redis_client is not None:
            with contextlib.suppress(Exception):
                await self._redis_client.aclose()
            self._redis_client = None

        with contextlib.suppress(Exception):
            await self._fire_coordinator.close()
        jobs.unregister_manager(self.registered_name)
        self.logger.info("Scheduler stopped (headless)")

    def setup(self, app: web.Application) -> web.Application:
        """Configure the scheduler pool and the five scheduler HTTP routes."""
        self.db = PostgresPool(
            dsn=default_dsn,
            name="Parrot.Scheduler",
            startup=self.on_startup,
            shutdown=self.on_shutdown,
        )
        self.db.configure(app, register="agentdb")
        self.app = app
        app[self.registered_name] = self

        from ..handlers.scheduler import SchedulerCallbacksHandler, SchedulerJobsHandler, SchedulerLastResultHandler

        app.router.add_view("/api/v1/parrot/scheduler/schedules", SchedulerJobsHandler)
        app.router.add_view("/api/v1/parrot/scheduler/schedules/{schedule_id}", SchedulerJobsHandler)
        app.router.add_view("/api/v1/parrot/scheduler/schedules/{schedule_id}/last-result", SchedulerLastResultHandler)
        app.router.add_view("/api/v1/parrot/scheduler/callbacks", SchedulerCallbacksHandler)
        app.router.add_post("/api/v1/parrot/scheduler/restart", self.restart_handler)
        return app

    async def on_startup(self, app: web.Application, conn: Callable[..., Any]) -> None:
        """Set the application pool and start the base scheduler without bot scanning."""
        self.logger.info("Starting scheduler")
        try:
            self._pool = conn
        except Exception as exc:
            self.logger.error("Failed to get database connection pool: %s", exc)
            self._pool = app["agentdb"]
        await self.start_headless(use_redis=True, register_listeners=True)
        self.logger.info("Scheduler started successfully")

    async def on_shutdown(self, app: web.Application, conn: Callable[..., Any]) -> None:
        """Stop scheduler resources while leaving application-owned pools intact."""
        self.logger.info("Shutting down scheduler")
        await self.stop_headless(wait=True)
        self.logger.info("Scheduler shut down")

    async def restart_scheduler(self) -> None:
        """Safely restart APScheduler after refreshing database schedules."""
        try:
            self.logger.info("Restarting scheduler")
            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)
            await self.load_schedules_from_db()
            self.scheduler.start()
            self.logger.info("Scheduler restarted successfully")
        except Exception as exc:
            self.logger.error("Error restarting scheduler: %s", exc)
            raise

    async def restart_handler(self, request: web.Request) -> web.Response:
        """Restart the scheduler from its HTTP endpoint."""
        try:
            await self.restart_scheduler()
            return web.json_response({"status": "success", "message": "Scheduler restarted successfully"})
        except Exception as exc:
            return web.json_response({"status": "error", "message": str(exc)}, status=500)
