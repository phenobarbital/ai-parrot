"""Run-state persistence for scheduled jobs (FEAT-644 spec §3 Module 2)."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

import redis.asyncio as aioredis
from redis.exceptions import WatchError

from .models import FireContext, RunState, utcnow

logger = logging.getLogger("Parrot.Scheduler.runstate")

LAST_RESULT_MAX_CHARS: int = 10_000
STATUS_LOCK_UNAVAILABLE = "lock_unavailable"


def truncate(text: Optional[str]) -> Optional[str]:
    """Cap a stored string at ``LAST_RESULT_MAX_CHARS`` with a truncation suffix."""
    if text is None or len(text) <= LAST_RESULT_MAX_CHARS:
        return text
    return text[:LAST_RESULT_MAX_CHARS] + "…(truncated)"


def aggregate_delivery_status(outcomes: list[dict[str, Any]]) -> Optional[str]:
    """Reduce outcomes to ``ok`` / ``partial`` / ``failed``."""
    if not outcomes:
        return None
    statuses = {outcome.get("status") for outcome in outcomes}
    if statuses <= {"sent", "saved"}:
        return "ok"
    if statuses == {"failed"}:
        return "failed"
    return "partial"


@runtime_checkable
class RunStateStore(Protocol):
    """Backend contract for per-job run state (spec §2)."""

    async def stamp_success(
        self, job_id: str, *, result_text: str | None, fire: FireContext, next_run: Any | None
    ) -> RunState: ...

    async def stamp_failure(
        self, job_id: str, *, status: str, error: str, fire: FireContext, threshold: int
    ) -> tuple[RunState, bool]: ...

    async def stamp_delivery(self, job_id: str, outcomes: list[dict[str, Any]]) -> None: ...

    async def read(self, job_id: str) -> RunState | None: ...

    async def set_enabled(self, job_id: str, enabled: bool) -> None: ...

    async def clear(self, job_id: str) -> None: ...


class MemoryRunState:
    """Process-local store for ``code`` jobs."""

    def __init__(self, backend: str = "code") -> None:
        self._backend = backend
        self._states: dict[str, RunState] = {}

    def _state(self, job_id: str) -> RunState:
        """Return the state for a job, creating its initial enabled state when needed."""
        if job_id not in self._states:
            self._states[job_id] = RunState(schedule_id=job_id, backend=self._backend, enabled=True)
        return self._states[job_id]

    async def stamp_success(
        self, job_id: str, *, result_text: str | None, fire: FireContext, next_run: Any | None
    ) -> RunState:
        """Record a successful execution and reset the failure state."""
        state = self._state(job_id)
        timestamp = utcnow()
        state.last_run = timestamp
        state.next_run = next_run
        state.run_count += 1
        state.last_status = "success"
        state.last_result = truncate(result_text)
        state.last_result_at = timestamp
        state.last_error = None
        state.last_error_at = None
        state.consecutive_failures = 0
        return state

    async def stamp_failure(
        self, job_id: str, *, status: str, error: str, fire: FireContext, threshold: int
    ) -> tuple[RunState, bool]:
        """Record a failed or unavailable execution and report a threshold crossing."""
        state = self._state(job_id)
        timestamp = utcnow()
        state.last_status = status
        state.last_error = truncate(error)
        state.last_error_at = timestamp
        if status == STATUS_LOCK_UNAVAILABLE:
            return state, False

        state.last_run = timestamp
        state.run_count += 1
        state.consecutive_failures += 1
        crossed_threshold = state.consecutive_failures == threshold
        if state.consecutive_failures >= threshold:
            state.enabled = False
        return state, crossed_threshold

    async def stamp_delivery(self, job_id: str, outcomes: list[dict[str, Any]]) -> None:
        """Record normalized delivery outcomes without changing the run state."""
        state = self._state(job_id)
        stored = []
        for outcome in outcomes:
            stored_outcome = dict(outcome)
            if stored_outcome.get("error") is not None:
                stored_outcome["error"] = truncate(str(stored_outcome["error"]))
            stored.append(stored_outcome)
        state.last_callbacks = stored
        state.last_delivery_status = aggregate_delivery_status(outcomes)
        state.last_delivery_at = utcnow()

    async def read(self, job_id: str) -> RunState | None:
        """Return the current job state when it has been initialized."""
        return self._states.get(job_id)

    async def set_enabled(self, job_id: str, enabled: bool) -> None:
        """Change enabled state and reset failures when re-enabling a job."""
        state = self._state(job_id)
        state.enabled = enabled
        if enabled:
            state.consecutive_failures = 0

    async def clear(self, job_id: str) -> None:
        """Remove process-local state for a deleted job."""
        self._states.pop(job_id, None)


class PostgresRunState:
    """Run state as columns of ``navigator.service_scheduler`` (single-statement transitions)."""

    _FAILURE_SQL = """
        UPDATE navigator.service_scheduler
           SET last_run = $1, run_count = run_count + 1, last_status = $2, last_error = $3, last_error_at = $1,
               consecutive_failures = consecutive_failures + 1,
               enabled = (consecutive_failures + 1 < $4) AND enabled
         WHERE schedule_id = $5
        RETURNING *
    """
    _LOCK_SQL = """
        UPDATE navigator.service_scheduler
           SET last_status = $1, last_error = $2, last_error_at = $3
         WHERE schedule_id = $4
        RETURNING *
    """
    _SUCCESS_SQL = """
        UPDATE navigator.service_scheduler
           SET last_run = $1, run_count = run_count + 1, last_status = 'success', last_result = $2,
               last_result_at = $1, last_error = NULL, last_error_at = NULL, consecutive_failures = 0,
               next_run = $3
         WHERE schedule_id = $4
        RETURNING *
    """
    _DELIVERY_SQL = """
        UPDATE navigator.service_scheduler
           SET last_callbacks = $1, last_delivery_status = $2, last_delivery_at = $3
         WHERE schedule_id = $4
        RETURNING *
    """
    _READ_SQL = "SELECT * FROM navigator.service_scheduler WHERE schedule_id = $1"
    _SET_ENABLED_SQL = """
        UPDATE navigator.service_scheduler
           SET enabled = $1, consecutive_failures = CASE WHEN $1 THEN 0 ELSE consecutive_failures END
         WHERE schedule_id = $2
        RETURNING *
    """

    def __init__(self, acquire: Callable[[], Awaitable[Any]]) -> None:
        """Store the bound pool-acquire method used for database operations."""
        self._acquire = acquire

    async def _one(self, sql: str, *args: Any) -> Any:
        """Execute a single-row statement through one acquired connection."""
        async with await self._acquire() as conn:  # pylint: disable=no-member
            return await conn.fetch_one(sql, *args)

    def _row_to_state(self, row: Any) -> RunState:
        """Map a ``service_scheduler`` row to ``RunState(backend='db')``."""
        return RunState(
            schedule_id=str(row["schedule_id"]),
            backend="db",
            enabled=bool(row["enabled"]),
            last_run=row.get("last_run"),
            next_run=row.get("next_run"),
            run_count=row.get("run_count", 0),
            last_status=row.get("last_status"),
            last_error=row.get("last_error"),
            last_error_at=row.get("last_error_at"),
            last_result=row.get("last_result"),
            last_result_at=row.get("last_result_at"),
            consecutive_failures=row.get("consecutive_failures", 0),
            last_delivery_status=row.get("last_delivery_status"),
            last_delivery_at=row.get("last_delivery_at"),
            last_callbacks=row.get("last_callbacks") or [],
        )

    @staticmethod
    def _missing_state(job_id: str) -> RunState:
        """Provide a safe default when a manager has deleted the row mid-transition."""
        return RunState(schedule_id=job_id, backend="db", enabled=False)

    async def stamp_failure(
        self, job_id: str, *, status: str, error: str, fire: FireContext, threshold: int
    ) -> tuple[RunState, bool]:
        """Atomically record a failure and report exactly one threshold crossing."""
        job_uuid = uuid.UUID(job_id)
        timestamp = utcnow()
        if status == STATUS_LOCK_UNAVAILABLE:
            row = await self._one(self._LOCK_SQL, status, truncate(error), timestamp, job_uuid)
            if row is None:
                logger.warning("Cannot stamp lock-unavailable state for missing schedule %s", job_id)
                return self._missing_state(job_id), False
            return self._row_to_state(row), False

        row = await self._one(self._FAILURE_SQL, timestamp, status, truncate(error), threshold, job_uuid)
        if row is None:
            logger.warning("Cannot stamp failure state for missing schedule %s", job_id)
            return self._missing_state(job_id), False
        state = self._row_to_state(row)
        return state, state.consecutive_failures == threshold

    async def stamp_success(
        self, job_id: str, *, result_text: str | None, fire: FireContext, next_run: Any | None
    ) -> RunState:
        """Atomically record a successful execution and reset failure state."""
        row = await self._one(self._SUCCESS_SQL, utcnow(), truncate(result_text), next_run, uuid.UUID(job_id))
        if row is None:
            logger.warning("Cannot stamp success state for missing schedule %s", job_id)
            return self._missing_state(job_id)
        return self._row_to_state(row)

    async def stamp_delivery(self, job_id: str, outcomes: list[dict[str, Any]]) -> None:
        """Persist delivery outcomes without changing execution state."""
        stored = []
        for outcome in outcomes:
            stored_outcome = dict(outcome)
            if stored_outcome.get("error") is not None:
                stored_outcome["error"] = truncate(str(stored_outcome["error"]))
            stored.append(stored_outcome)
        row = await self._one(
            self._DELIVERY_SQL,
            stored,
            aggregate_delivery_status(outcomes),
            utcnow(),
            uuid.UUID(job_id),
        )
        if row is None:
            logger.warning("Cannot stamp delivery state for missing schedule %s", job_id)

    async def read(self, job_id: str) -> RunState | None:
        """Read the database-backed state for a schedule."""
        row = await self._one(self._READ_SQL, uuid.UUID(job_id))
        return self._row_to_state(row) if row is not None else None

    async def set_enabled(self, job_id: str, enabled: bool) -> None:
        """Set enabled state and reset failures when a job is re-enabled."""
        row = await self._one(self._SET_ENABLED_SQL, enabled, uuid.UUID(job_id))
        if row is None:
            logger.warning("Cannot set enabled state for missing schedule %s", job_id)

    async def clear(self, job_id: str) -> None:
        """Do nothing because the manager deletes database rows itself."""
        return None


class RedisRunState:
    """Run state as a Redis hash ``{prefix}{job_id}``.

    The prefix is normally ``parrot:scheduler:{registered_name}:runstate:``.
    """

    _MAX_WATCH_RETRIES = 10
    _DATETIME_FIELDS = frozenset(
        {
            "last_run",
            "next_run",
            "last_error_at",
            "last_result_at",
            "last_delivery_at",
        }
    )
    _INT_FIELDS = frozenset({"run_count", "consecutive_failures"})

    def __init__(self, client: "aioredis.Redis", *, prefix: str) -> None:
        """Bind a Redis client and the namespace reserved for this manager's state."""
        self._client = client
        self._prefix = prefix

    def _key(self, job_id: str) -> str:
        """Return the namespaced Redis hash key for ``job_id``."""
        return f"{self._prefix}{job_id}"

    @staticmethod
    def _encode(fields: dict[str, Any]) -> dict[str, str]:
        """Encode state fields as Redis hash strings."""
        encoded: dict[str, str] = {}
        for name, value in fields.items():
            if value is None:
                encoded[name] = ""
            elif isinstance(value, datetime):
                encoded[name] = value.isoformat()
            elif isinstance(value, bool):
                encoded[name] = "1" if value else "0"
            elif isinstance(value, int):
                encoded[name] = str(value)
            elif isinstance(value, (list, dict)):
                encoded[name] = json.dumps(value)
            else:
                encoded[name] = str(value)
        return encoded

    def _decode(self, job_id: str, raw: dict[str, Any]) -> RunState:
        """Decode a Redis hash, returning a new enabled state when it is absent."""
        if not raw:
            return RunState(schedule_id=job_id, backend="redis", enabled=True)

        values = {
            (name.decode() if isinstance(name, bytes) else name): (
                value.decode() if isinstance(value, bytes) else value
            )
            for name, value in raw.items()
        }
        fields: dict[str, Any] = {
            "schedule_id": job_id,
            "backend": "redis",
            "enabled": values.get("enabled", "1") == "1",
            "last_callbacks": json.loads(values.get("last_callbacks") or "[]"),
        }
        for name in self._INT_FIELDS:
            fields[name] = int(values.get(name) or 0)
        for name in self._DATETIME_FIELDS:
            value = values.get(name)
            fields[name] = datetime.fromisoformat(value) if value else None
        for name in (
            "last_status",
            "last_error",
            "last_result",
            "last_delivery_status",
        ):
            fields[name] = values.get(name) or None
        return RunState(**fields)

    async def _state(self, job_id: str) -> RunState:
        """Read a state hash or construct the enabled initial state."""
        return self._decode(job_id, await self._client.hgetall(self._key(job_id)))

    async def _write(self, job_id: str, state: RunState) -> None:
        """Persist the Redis-owned fields of ``state`` to its hash."""
        fields = state.model_dump(exclude={"schedule_id", "backend"})
        await self._client.hset(self._key(job_id), mapping=self._encode(fields))

    async def stamp_success(
        self, job_id: str, *, result_text: str | None, fire: FireContext, next_run: Any | None
    ) -> RunState:
        """Record a successful execution and reset the failure state."""
        state = await self._state(job_id)
        timestamp = utcnow()
        state.last_run = timestamp
        state.next_run = next_run
        state.run_count += 1
        state.last_status = "success"
        state.last_result = truncate(result_text)
        state.last_result_at = timestamp
        state.last_error = None
        state.last_error_at = None
        state.consecutive_failures = 0
        await self._write(job_id, state)
        return state

    async def stamp_failure(
        self, job_id: str, *, status: str, error: str, fire: FireContext, threshold: int
    ) -> tuple[RunState, bool]:
        """Atomically record a failure and report exactly one threshold crossing."""
        key = self._key(job_id)
        for attempt in range(self._MAX_WATCH_RETRIES):
            try:
                async with self._client.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)
                    state = self._decode(job_id, await pipe.hgetall(key))
                    timestamp = utcnow()
                    state.last_status = status
                    state.last_error = truncate(error)
                    state.last_error_at = timestamp
                    crossed_threshold = False
                    if status != STATUS_LOCK_UNAVAILABLE:
                        state.last_run = timestamp
                        state.run_count += 1
                        state.consecutive_failures += 1
                        crossed_threshold = state.consecutive_failures == threshold
                        if state.consecutive_failures >= threshold:
                            state.enabled = False

                    pipe.multi()
                    fields = state.model_dump(exclude={"schedule_id", "backend"})
                    pipe.hset(key, mapping=self._encode(fields))
                    await pipe.execute()
                    return state, crossed_threshold
            except WatchError:
                if attempt == self._MAX_WATCH_RETRIES - 1:
                    raise
        raise RuntimeError("Redis WATCH retry loop exhausted")

    async def stamp_delivery(self, job_id: str, outcomes: list[dict[str, Any]]) -> None:
        """Record normalized delivery outcomes without changing execution state."""
        state = await self._state(job_id)
        stored = []
        for outcome in outcomes:
            stored_outcome = dict(outcome)
            if stored_outcome.get("error") is not None:
                stored_outcome["error"] = truncate(str(stored_outcome["error"]))
            stored.append(stored_outcome)
        state.last_callbacks = stored
        state.last_delivery_status = aggregate_delivery_status(outcomes)
        state.last_delivery_at = utcnow()
        await self._write(job_id, state)

    async def read(self, job_id: str) -> RunState | None:
        """Return the current state when its Redis hash has been initialized."""
        raw = await self._client.hgetall(self._key(job_id))
        return self._decode(job_id, raw) if raw else None

    async def set_enabled(self, job_id: str, enabled: bool) -> None:
        """Set enabled state and reset failures when a job is re-enabled."""
        state = await self._state(job_id)
        state.enabled = enabled
        if enabled:
            state.consecutive_failures = 0
        await self._write(job_id, state)

    async def clear(self, job_id: str) -> None:
        """Delete Redis state for a removed job."""
        await self._client.delete(self._key(job_id))
