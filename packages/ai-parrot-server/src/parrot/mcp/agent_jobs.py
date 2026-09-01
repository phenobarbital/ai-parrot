"""Job handles for long-running agent methods (FEAT-477, Module 4, G7).

Agent flows and crews exceed the 300s connector tool-call ceiling
(`AgentMCPMountConfig.call_deadline_seconds`, TASK-2606), so they need a
durable handle rather than a blocking call. This module implements the
declared ``start_*`` -> ``job_id``, ``*_status``, ``*_result`` trio:

- :meth:`AgentJobs.start` persists an :class:`AgentJobRecord` and returns
  its ``job_id`` **immediately** — it never blocks on the work, which runs
  as a background ``asyncio`` task (no queue framework exists in
  ``parrot.mcp`` to import; state is persisted and polled instead).
- :meth:`AgentJobs.status` / :meth:`AgentJobs.result` project a
  **manifest** — counts, summaries, references — **never the raw
  payload**, which would blow the response ceiling TASK-2606 enforces.
- Every read is scoped to the caller's ``(tenant_id, principal)``; a
  mismatched principal gets the same response as a missing job (no
  existence oracle).

:class:`AgentJobStore` persists to Redis reusing
:class:`~parrot.human.suspended_store.SuspendedExecutionStore`'s
*semantics* (caller-provided TTL, a tombstone on delete) — it does **not**
force agent jobs through the HITL-specific ``SuspendedExecution`` record
type, which this module has no business depending on.
"""
import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from parrot.auth.permission import PermissionContext
from pydantic import BaseModel, Field

logger = logging.getLogger("Parrot.MCP.AgentJobs")

JobStatus = Literal["pending", "running", "succeeded", "failed", "expired"]

#: Extra seconds the underlying Redis key survives past the caller's
#: intended TTL, so a logically-expired job can still be *read* as
#: `"expired"` rather than vanish straight into "missing" the instant its
#: TTL notionally elapses.
_EXPIRY_GRACE_SECONDS = 300

#: How long a delete tombstone survives (`SuspendedExecutionStore`-style
#: "tombstone on delete" — see module docstring).
_TOMBSTONE_TTL_SECONDS = 300


class AgentJobRecord(BaseModel):
    """A durable handle for one long-running agent-method invocation.

    Spec §2 Data Models, field-for-field, no extensions. Bookkeeping
    `AgentJobStore` itself needs (the caller's intended TTL, save
    timestamp) lives in the store's own persisted envelope, not here.

    Attributes:
        job_id: Unique job identifier.
        agent: Configured agent name that owns the method.
        tool: The `@mcp_tool`-decorated method's MCP name.
        tenant_id: Tenant the calling principal belongs to.
        principal: The calling principal's identity.
        status: Current lifecycle state. `"expired"` is a **terminal**
            outcome alternative to `"succeeded"`/`"failed"` — a job that
            did not reach either before its retention TTL elapsed.
        created_at: UTC timestamp the job was created.
        manifest: Projection of the result — counts, summaries,
            references. Never the raw payload.
        error: Human-readable failure reason, when `status == "failed"`.
    """

    job_id: str
    agent: str
    tool: str
    tenant_id: str
    principal: str
    status: JobStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    manifest: dict[str, Any] | None = None
    error: str | None = None


def _project_manifest(raw: Any) -> dict[str, Any]:
    """Project a manifest from a raw result — counts/summaries, never the payload.

    Args:
        raw: The long-running method's raw return value.

    Returns:
        A small, bounded manifest dict. Never embeds `raw` itself.
    """
    if isinstance(raw, dict):
        return {"type": "dict", "keys": sorted(map(str, raw.keys())), "item_count": len(raw)}
    if isinstance(raw, list):
        return {"type": "list", "item_count": len(raw)}
    return {"type": type(raw).__name__, "summary": str(raw)[:200]}


class AgentJobStore:
    """Redis-backed store for `AgentJobRecord`s.

    Key format: `mcp:agent-job:{job_id}`. Reuses
    `SuspendedExecutionStore`'s semantics (`human/suspended_store.py:64`)
    — caller-provided TTL, a tombstone on delete — without forcing agent
    jobs through the HITL-specific `SuspendedExecution` record type.

    The underlying Redis key survives `ttl + _EXPIRY_GRACE_SECONDS`
    seconds so a read after the caller's intended `ttl` has elapsed can
    still observe `status="expired"` (a real, loadable record) instead of
    a bare miss; only once the grace period also elapses does the job
    become indistinguishable from one that never existed.

    Args:
        redis: An async Redis-like client exposing `setex`/`get`/`delete`.
        clock: Zero-argument callable returning the current epoch
            seconds. Defaults to `time.time` — injectable so tests can
            fast-forward a fake clock instead of sleeping.
    """

    def __init__(self, redis: Any, clock: Callable[[], float] = time.time) -> None:
        self.redis = redis
        self._clock = clock
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _key(job_id: str) -> str:
        """Return the Redis key for `job_id`'s live record."""
        return f"mcp:agent-job:{job_id}"

    @staticmethod
    def _tombstone_key(job_id: str) -> str:
        """Return the Redis key for `job_id`'s delete tombstone."""
        return f"mcp:agent-job:{job_id}:tombstone"

    async def save(self, record: AgentJobRecord, ttl: int) -> None:
        """Persist `record` with a caller-provided TTL.

        Args:
            record: The `AgentJobRecord` to persist.
            ttl: Caller-intended retention in seconds. The underlying
                Redis key is kept slightly longer
                (`_EXPIRY_GRACE_SECONDS`) so a post-TTL read can still
                observe `"expired"` rather than a bare miss.
        """
        envelope = {
            "record": json.loads(record.model_dump_json()),
            "ttl": ttl,
            "saved_at": self._clock(),
        }
        redis_ttl = max(1, ttl) + _EXPIRY_GRACE_SECONDS
        await self.redis.setex(self._key(record.job_id), redis_ttl, json.dumps(envelope))

    async def load(self, job_id: str) -> "AgentJobRecord | None":
        """Load `job_id`, promoting a non-terminal record to `"expired"`.

        Args:
            job_id: The job identifier.

        Returns:
            The `AgentJobRecord` — with `status` promoted to `"expired"`
            when it was still `"pending"`/`"running"` and the caller's
            intended `ttl` has elapsed — or `None` if it was never saved
            or its grace period has also elapsed.
        """
        raw = await self.redis.get(self._key(job_id))
        if raw is None:
            return None
        envelope = json.loads(raw)
        record = AgentJobRecord.model_validate(envelope["record"])
        elapsed = self._clock() - envelope["saved_at"]
        if elapsed >= envelope["ttl"] and record.status in ("pending", "running"):
            record = record.model_copy(update={"status": "expired"})
        return record

    async def delete(self, job_id: str) -> None:
        """Delete `job_id`'s live record, leaving a short-lived tombstone.

        Mirrors `SuspendedExecutionStore.delete()`'s tombstone semantics:
        the live record disappears, but a companion key survives briefly
        so a delete is observably distinct from the record never having
        existed at all.

        Args:
            job_id: The job identifier.
        """
        await self.redis.delete(self._key(job_id))
        await self.redis.setex(self._tombstone_key(job_id), _TOMBSTONE_TTL_SECONDS, "1")


class AgentJobs:
    """The `start_*` -> `job_id`, `*_status`, `*_result` trio (spec §3 Module 4).

    Args:
        store: The `AgentJobStore` persisting job records.
        method_resolver: `(agent_name, tool_name) -> async callable`,
            resolving which bound method `start()` runs in the
            background. `None` (default) fails every started job
            immediately with an error manifest — wire in the real
            exposure-set lookup (TASK-2600/2602's `build_exposure_set`)
            when mounting this.
        default_ttl: Retention TTL (seconds) used when `start()`'s caller
            does not pass one explicitly.
    """

    def __init__(
        self,
        store: AgentJobStore,
        method_resolver: "Callable[[str, str], Callable[..., Any]] | None" = None,
        default_ttl: int = 3600,
    ) -> None:
        self._store = store
        self._method_resolver = method_resolver
        self._default_ttl = default_ttl
        self.logger = logging.getLogger("Parrot.MCP.AgentJobs")
        # Strong references so fire-and-forget background jobs are not
        # garbage-collected mid-execution.
        self._background_tasks: set[asyncio.Task] = set()

    async def start(
        self,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        pctx: PermissionContext,
        *,
        ttl: "int | None" = None,
    ) -> str:
        """Start a long-running call and return its `job_id` immediately.

        Persists a `"pending"` record and schedules the work as a
        background `asyncio` task — this coroutine returns as soon as
        that record is saved, never waiting on the work itself.

        Args:
            agent_name: The owning agent's configured name.
            tool_name: The `@mcp_tool`-decorated method's MCP name.
            arguments: Call arguments for the method.
            pctx: The caller's resolved `PermissionContext`.
            ttl: Retention TTL in seconds. Defaults to `default_ttl`.

        Returns:
            The new job's `job_id`.
        """
        job_id = str(uuid.uuid4())
        effective_ttl = ttl if ttl is not None else self._default_ttl
        record = AgentJobRecord(
            job_id=job_id,
            agent=agent_name,
            tool=tool_name,
            tenant_id=pctx.tenant_id,
            principal=pctx.user_id,
            status="pending",
        )
        await self._store.save(record, effective_ttl)
        task = asyncio.create_task(
            self._run(job_id, agent_name, tool_name, arguments, effective_ttl)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return job_id

    async def _run(
        self,
        job_id: str,
        agent_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        ttl: int,
    ) -> None:
        """Execute the resolved method out of band and persist its outcome.

        Args:
            job_id: The job identifier.
            agent_name: The owning agent's configured name.
            tool_name: The method's MCP name.
            arguments: Call arguments for the method.
            ttl: Retention TTL in seconds, reused for every state transition.
        """
        record = await self._store.load(job_id)
        if record is None:
            return
        record = record.model_copy(update={"status": "running"})
        await self._store.save(record, ttl)

        if self._method_resolver is None:
            await self._store.save(
                record.model_copy(
                    update={
                        "status": "failed",
                        "error": "no method resolver configured for agent jobs",
                    }
                ),
                ttl,
            )
            return

        try:
            method = self._method_resolver(agent_name, tool_name)
            raw_result = await method(**arguments)
        except Exception as exc:
            self.logger.exception(
                "Agent job %s failed: agent=%s tool=%s", job_id, agent_name, tool_name
            )
            await self._store.save(
                record.model_copy(update={"status": "failed", "error": str(exc)}), ttl
            )
            return

        await self._store.save(
            record.model_copy(
                update={"status": "succeeded", "manifest": _project_manifest(raw_result)}
            ),
            ttl,
        )

    @staticmethod
    def _scoped(
        record: "AgentJobRecord | None", pctx: PermissionContext
    ) -> "AgentJobRecord | None":
        """Return `record` only if it belongs to `pctx`'s `(tenant_id, principal)`.

        Args:
            record: The loaded record, or `None`.
            pctx: The caller's resolved `PermissionContext`.

        Returns:
            `record` if it is `None` already, or if it belongs to the
            caller; `None` otherwise — a mismatched principal gets the
            same response as a missing job (no existence oracle).
        """
        if record is None:
            return None
        if record.tenant_id != pctx.tenant_id or record.principal != pctx.user_id:
            return None
        return record

    async def status(self, job_id: str, pctx: PermissionContext) -> "dict[str, Any] | None":
        """Return a status projection for `job_id`, scoped to `pctx`.

        Args:
            job_id: The job identifier.
            pctx: The caller's resolved `PermissionContext`.

        Returns:
            `{"job_id", "status", "agent", "tool", "created_at"}`, or
            `None` if missing or owned by a different `(tenant_id,
            principal)`.
        """
        record = self._scoped(await self._store.load(job_id), pctx)
        if record is None:
            return None
        return {
            "job_id": record.job_id,
            "status": record.status,
            "agent": record.agent,
            "tool": record.tool,
            "created_at": record.created_at.isoformat(),
        }

    async def result(self, job_id: str, pctx: PermissionContext) -> "dict[str, Any] | None":
        """Return a manifest projection for `job_id`, scoped to `pctx`.

        Never returns the raw payload — only the small manifest `start()`'s
        background run computed on success.

        Args:
            job_id: The job identifier.
            pctx: The caller's resolved `PermissionContext`.

        Returns:
            `{"job_id", "status", "manifest", "error"}`, or `None` if
            missing or owned by a different `(tenant_id, principal)`.
        """
        record = self._scoped(await self._store.load(job_id), pctx)
        if record is None:
            return None
        return {
            "job_id": record.job_id,
            "status": record.status,
            "manifest": record.manifest,
            "error": record.error,
        }

    async def delete(self, job_id: str) -> None:
        """Delete `job_id`'s live record, leaving a tombstone.

        Args:
            job_id: The job identifier.
        """
        await self._store.delete(job_id)


__all__ = ["AgentJobRecord", "AgentJobStore", "AgentJobs"]
