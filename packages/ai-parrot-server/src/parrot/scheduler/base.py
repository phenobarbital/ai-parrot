"""Target-agnostic scheduler base (FEAT-644): resolver contract and registry."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import uuid
from enum import Enum
from typing import Any, Callable, Dict, Optional, Protocol, Sequence, Set, runtime_checkable

import redis.asyncio as aioredis
from aiohttp import web
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from asyncdb import AsyncDB
from asyncdb.exceptions import NoDataFound
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
from .models import CodeJobRecord, JOB_DEFINITION_VERSION, ServiceSchedule, schedule_fingerprint
from .models import FireContext, JobDefinition, utcnow
from .runstate import MemoryRunState, PostgresRunState, RedisRunState, RunStateStore
from .sanitize import (
    SchedulerConfigError,
    clean_int,
    clean_method_name,
    clean_misfire_grace_time,
    normalize_backend,
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

    def _db_job_kwargs(self, definition: JobDefinition) -> dict[str, Any]:
        """Build the JSON-safe trampoline arguments for a database schedule."""
        return {
            "manager_name": self.registered_name,
            "schedule_id": definition.schedule_id,
            "fingerprint": schedule_fingerprint(definition),
        }

    async def add_schedule(
        self,
        target_kind: str,
        target_name: str,
        schedule_type: str,
        schedule_config: dict[str, Any],
        *,
        backend: str = "db",
        target_id: str | None = None,
        tenant: str | None = None,
        prompt: str | None = None,
        method_name: str | None = None,
        created_by: int | None = None,
        created_email: str | None = None,
        metadata: dict[str, Any] | None = None,
        send_result: dict[str, Any] | None = None,
        success_callback: Callable[..., Any] | None = None,
        callbacks: list[dict[str, Any]] | None = None,
        misfire_grace_time: int | None = None,
    ) -> JobDefinition:
        """Validate, persist or store, and schedule a target invocation.

        Raises:
            SchedulerConfigError: If scheduler configuration is invalid.
            ValueError: If the target kind or target is unknown.
        """
        schedule_type = normalize_schedule_type(schedule_type)
        schedule_config = sanitize_schedule_config(schedule_type, schedule_config)
        backend = normalize_backend(backend, redis_available=self.redis_available, strict=True)
        method_name = clean_method_name(method_name)
        misfire_grace_time = clean_misfire_grace_time(misfire_grace_time)
        resolver = self._resolvers.get(target_kind)
        if resolver is None:
            raise ValueError(f"Unknown target kind: {target_kind!r}")
        if backend == "redis" and success_callback is not None:
            raise ValueError("success_callback is not supported for redis schedules")

        target = await resolver.resolve(target_name, target_id=target_id)
        if target is None:
            raise ValueError(f"Target not found: {target_kind}/{target_name}")
        schedule_id = str(uuid.uuid4())
        definition = JobDefinition(
            schedule_id=schedule_id,
            backend=backend,
            target_kind=target_kind,
            target_name=target_name,
            target_id=target_id if target_id is not None else resolver.derive_target_id(target),
            tenant=tenant,
            prompt=prompt,
            method_name=method_name,
            schedule_type=schedule_type,
            schedule_config=schedule_config,
            metadata=dict(metadata or {}),
            send_result=dict(send_result or {}),
            callbacks=list(callbacks or []),
            misfire_grace_time=300 if backend == "db" and misfire_grace_time is None else misfire_grace_time,
            created_by=created_by,
            created_email=created_email,
        )
        resolver.build_call(target, definition, FireContext.for_fire(schedule_id, utcnow()))
        trigger = self._create_trigger(schedule_type, schedule_config)

        if backend == "redis":
            self.scheduler.add_job(
                jobs.run_redis_job,
                trigger=trigger,
                id=schedule_id,
                name=f"{target_name}_{schedule_type}",
                kwargs={
                    "manager_name": self.registered_name,
                    "schedule_id": schedule_id,
                    "definition_version": JOB_DEFINITION_VERSION,
                    "definition": definition.model_dump(mode="json"),
                },
                jobstore="redis",
                replace_existing=True,
                misfire_grace_time=definition.misfire_grace_time,
                coalesce=True,
            )
            return definition

        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member
            ServiceSchedule.Meta.connection = conn
            row = ServiceSchedule.from_definition(definition)
            await row.save()
        try:
            job = self.scheduler.add_job(
                jobs.run_db_schedule,
                trigger=trigger,
                id=schedule_id,
                name=f"{target_name}_{schedule_type}",
                kwargs=self._db_job_kwargs(definition),
                jobstore="default",
                replace_existing=True,
                misfire_grace_time=definition.misfire_grace_time,
            )
            if job.next_run_time:
                row.next_run = job.next_run_time
                row.updated_at = utcnow()
                async with await pool.acquire() as conn:  # pylint: disable=no-member
                    ServiceSchedule.Meta.connection = conn
                    await row.update()
        except Exception as exc:
            await row.delete()
            raise RuntimeError(f"Failed to add schedule to jobstore: {exc}") from exc
        if success_callback is not None:
            self._local_callbacks[schedule_id] = success_callback
        return definition

    async def _locate(self, schedule_id: str) -> tuple[str, JobDefinition | None, Any]:
        """Find a job by id across code, Redis, database, and external jobs."""
        if schedule_id in self._code_jobs:
            record = self._code_jobs[schedule_id]
            return "code", record.to_definition(), record
        redis_job = self.scheduler.get_job(schedule_id, jobstore="redis") if self.redis_available else None
        if redis_job is not None and redis_job.func_ref == "parrot.scheduler.jobs:run_redis_job":
            return "redis", JobDefinition(**redis_job.kwargs["definition"]), redis_job
        if self._pool is not None:
            try:
                identifier = uuid.UUID(schedule_id)
            except (TypeError, ValueError):
                identifier = None
            if identifier is not None:
                async with await self._pool.acquire() as conn:  # pylint: disable=no-member
                    ServiceSchedule.Meta.connection = conn
                    try:
                        row = await ServiceSchedule.get(schedule_id=identifier)
                    except NoDataFound:
                        row = None
                if row is not None:
                    return "db", row.to_definition(), row
        for jobstore in self._registered_jobstores():
            job = self.scheduler.get_job(schedule_id, jobstore=jobstore)
            if job is not None:
                return "external", None, job
        raise NoDataFound(f"Schedule {schedule_id!r} not found")

    async def get_schedule(self, schedule_id: str) -> JobDefinition:
        """Return a definition for editable or code schedules."""
        source, definition, _ = await self._locate(schedule_id)
        if source == "external" or definition is None:
            raise NoDataFound(f"Schedule {schedule_id!r} has no definition")
        return definition

    async def list_schedules(self) -> list[JobDefinition]:
        """Return database, Redis, and code schedule definitions."""
        definitions: list[JobDefinition] = []
        if self._pool is not None:
            async with await self._pool.acquire() as conn:  # pylint: disable=no-member
                ServiceSchedule.Meta.connection = conn
                definitions.extend(row.to_definition() for row in await ServiceSchedule.all())
        if self.redis_available:
            for job in self.scheduler.get_jobs(jobstore="redis"):
                if job.func_ref == "parrot.scheduler.jobs:run_redis_job":
                    definitions.append(JobDefinition(**job.kwargs["definition"]))
        definitions.extend(record.to_definition() for record in self._code_jobs.values())
        return definitions

    def _serialize_job(self, definition: JobDefinition | None, job: Any = None, *, source: str) -> dict[str, Any]:
        """Serialize an owned or foreign APScheduler job without leaking kwargs."""
        jobstore = getattr(job, "_jobstore_alias", None)
        next_run_time = getattr(job, "next_run_time", None) if job else None
        job_payload = {
            "id": str(job.id) if job else None,
            "name": job.name if job else None,
            "next_run": next_run_time.isoformat() if next_run_time else None,
            "paused": bool(job and next_run_time is None),
            "pending": job is not None,
            "jobstore": jobstore,
        }
        if definition is None:
            return {
                "source": "external",
                "schedule_id": str(job.id),
                "enabled": next_run_time is not None,
                "job": job_payload,
            }
        payload = definition.model_dump(mode="json")
        payload.update({"source": source, "backend": definition.backend, "enabled": next_run_time is not None if job else True, "job": job_payload})
        return payload

    async def list_jobs(self) -> list[dict[str, Any]]:
        """Return every scheduler job and database rows that have drifted."""
        definitions = {definition.schedule_id: definition for definition in await self.list_schedules()}
        payload: list[dict[str, Any]] = []
        for jobstore in self._registered_jobstores():
            for job in self.scheduler.get_jobs(jobstore=jobstore):
                definition = definitions.pop(job.id, None)
                if definition is not None:
                    payload.append(self._serialize_job(definition, job, source=definition.backend))
                else:
                    payload.append(self._serialize_job(None, job, source="external"))
        for definition in definitions.values():
            payload.append(self._serialize_job(definition, source=definition.backend))
        return payload

    async def update_schedule(self, schedule_id: str, updates: dict[str, Any]) -> JobDefinition:
        """Update an editable schedule and rebuild its APScheduler trigger."""
        source, current, stored = await self._locate(schedule_id)
        if source == "external" or current is None:
            raise NotEditableError("external schedules cannot be edited")
        if "backend" in updates:
            raise NotEditableError("backend cannot change; delete and re-create")
        if source == "code":
            if set(updates) != {"enabled"}:
                raise NotEditableError("code-declared schedules cannot be edited")
            enabled = bool(updates["enabled"])
            stored.enabled = enabled
            if enabled:
                self.scheduler.resume_job(schedule_id, jobstore="default")
            else:
                self.scheduler.pause_job(schedule_id, jobstore="default")
            await self._run_state_for("code").set_enabled(schedule_id, enabled)
            return stored.to_definition()

        editable = {
            "target_kind", "target_name", "target_id", "prompt", "method_name", "schedule_type", "schedule_config",
            "metadata", "send_result", "callbacks", "misfire_grace_time", "tenant", "created_by", "created_email",
        }
        values = current.model_dump()
        values.update({key: value for key, value in updates.items() if key in editable})
        values["method_name"] = clean_method_name(values["method_name"])
        values["schedule_type"] = normalize_schedule_type(values["schedule_type"])
        values["schedule_config"] = sanitize_schedule_config(values["schedule_type"], values["schedule_config"])
        values["misfire_grace_time"] = clean_misfire_grace_time(values["misfire_grace_time"])
        if source == "db" and values["misfire_grace_time"] is None:
            values["misfire_grace_time"] = 300
        updated = JobDefinition(**values)
        trigger = self._create_trigger(updated.schedule_type, updated.schedule_config)
        enabled = bool(updates.get("enabled", getattr(stored, "enabled", True)))
        if source == "redis":
            kwargs = dict(stored.kwargs)
            kwargs["definition"] = updated.model_dump(mode="json")
            self.scheduler.modify_job(schedule_id, jobstore="redis", kwargs=kwargs, misfire_grace_time=updated.misfire_grace_time)
            self.scheduler.reschedule_job(schedule_id, jobstore="redis", trigger=trigger)
            if "enabled" in updates:
                if enabled:
                    self.scheduler.resume_job(schedule_id, jobstore="redis")
                else:
                    self.scheduler.pause_job(schedule_id, jobstore="redis")
                await self._run_state_for("redis").set_enabled(schedule_id, enabled)
            return updated

        for key, value in updated.model_dump().items():
            if key not in {"schedule_id", "backend", "misfire_grace_time"}:
                setattr(stored, key, value)
        stored.enabled = enabled
        stored.updated_at = utcnow()
        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member
            ServiceSchedule.Meta.connection = conn
            await stored.update()
        with contextlib.suppress(JobLookupError):
            self.scheduler.remove_job(schedule_id, jobstore="default")
        if enabled:
            job = self.scheduler.add_job(
                jobs.run_db_schedule, trigger=trigger, id=schedule_id, name=f"{updated.target_name}_{updated.schedule_type}",
                kwargs=self._db_job_kwargs(updated), jobstore="default", replace_existing=True,
                misfire_grace_time=updated.misfire_grace_time,
            )
            stored.next_run = job.next_run_time
            async with await pool.acquire() as conn:  # pylint: disable=no-member
                ServiceSchedule.Meta.connection = conn
                await stored.update()
        await self._run_state_for("db").set_enabled(schedule_id, enabled)
        return updated

    async def pause_schedule(self, schedule_id: str) -> JobDefinition:
        """Pause an owned schedule while preserving its definition."""
        return await self.update_schedule(schedule_id, {"enabled": False})

    async def delete_schedule(self, schedule_id: str) -> None:
        """Delete a database or Redis schedule and its scheduler state."""
        source, _, stored = await self._locate(schedule_id)
        if source in {"code", "external"}:
            raise NotEditableError(f"{source} schedules cannot be deleted")
        if source == "redis":
            self.scheduler.remove_job(schedule_id, jobstore="redis")
            await self._run_state_for("redis").clear(schedule_id)
            return
        with contextlib.suppress(JobLookupError):
            self.scheduler.remove_job(schedule_id, jobstore="default")
        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member
            ServiceSchedule.Meta.connection = conn
            await stored.delete()
        self._local_callbacks.pop(schedule_id, None)

    async def remove_schedule(self, schedule_id: str) -> None:
        """Backward-compatible alias of :meth:`delete_schedule`."""
        await self.delete_schedule(schedule_id)

    async def load_schedules_from_db(self) -> None:
        """Load enabled database schedules into the default APScheduler jobstore."""
        pool = await self._get_connection_pool()
        query = "SELECT * FROM navigator.service_scheduler WHERE enabled = TRUE ORDER BY created_at"
        async with await pool.acquire() as conn:  # pylint: disable=no-member
            ServiceSchedule.Meta.connection = conn
            rows, error = await conn.query(query)
        if error:
            self.logger.warning("Error querying service schedules: %s", error)
            return
        for record in rows:
            try:
                row = ServiceSchedule(**record)
                definition = row.to_definition()
                job = self.scheduler.add_job(
                    jobs.run_db_schedule, trigger=self._create_trigger(definition.schedule_type, definition.schedule_config),
                    id=definition.schedule_id, name=f"{definition.target_name}_{definition.schedule_type}",
                    kwargs=self._db_job_kwargs(definition), jobstore="default", replace_existing=True,
                    misfire_grace_time=300,
                )
                if job.next_run_time:
                    row.next_run = job.next_run_time
                    row.updated_at = utcnow()
                    async with await pool.acquire() as conn:  # pylint: disable=no-member
                        ServiceSchedule.Meta.connection = conn
                        await row.update()
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Failed to load schedule %s: %s", record.get("schedule_id"), exc)

    def register_object_schedules(self, obj: Any, name: str) -> int:
        """Register ``@schedule`` methods from an object as in-memory code jobs."""
        registered = 0
        for method_name, method in inspect.getmembers(obj, predicate=inspect.ismethod):
            if not hasattr(method, "_schedule_config"):
                continue
            config = method._schedule_config
            configured_name = config.get("method_name", method_name)
            try:
                schedule_type = normalize_schedule_type(config.get("schedule_type"))
                schedule_config = sanitize_schedule_config(schedule_type, config.get("schedule_config", {}))
                trigger = self._create_trigger(schedule_type, schedule_config)
                job_id = f"auto_{name}_{configured_name}"
                record = CodeJobRecord(
                    job_id=job_id, target_name=name, method_name=configured_name, method=method,
                    schedule_type=schedule_type, schedule_config=schedule_config,
                    success_callback=config.get("success_callback"), send_result=config.get("send_result"),
                    callbacks=list(config.get("callbacks") or []),
                )
                self._code_jobs[job_id] = record
                self.scheduler.add_job(
                    jobs.run_auto_schedule, trigger=trigger, id=job_id, name=f"{name}.{configured_name}",
                    kwargs={"manager_name": self.registered_name, "job_id": job_id}, jobstore="default", replace_existing=True,
                )
                registered += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.error("Failed to register auto-schedule for %s.%s: %s", name, configured_name, exc)
        return registered

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
