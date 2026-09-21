"""Authoritative background registrations; never adopt arbitrary process ids.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M8
(background registry/status, R8). `BackgroundRegistry` binds an opaque
``handle`` -- emitted only at registration time, never a PID or caller
path -- to its true launch identity (``execution_id``, ``launch_id``,
``owner_instance_id``, ``authority``) and persists that identity durably
under the shared evidence root (`ExecutionEvidenceStore.root`), so it
survives a process restart.

``status()`` is a bounded, non-blocking snapshot: it never shells out, never
calls ``ps``/``kill -0``, and never waits for a process/job/test suite to
finish. Once the registering process (``owner_instance_id``) is gone and no
terminal receipt was durably recorded, the state degrades to ``unknown``
with ``exit_code=None`` -- it never reconstructs a false "finished" from an
empty log or a reused PID.

Only ``register()``/``status()`` are meant for external (MCP-facing)
callers; ``_record_transition`` is internal bookkeeping for the owning
engine/supervisor/host_observation authority to report a state change in
this same process -- it takes an explicit, already-known state, never a PID
to adopt, and never blocks waiting on anything itself.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration, BackgroundStatus, EvidenceRef

logger = logging.getLogger(__name__)

#: Spec R8: tail reads are bounded to 0..4096 bytes.
_MAX_TAIL_BYTES = 4096
#: Spec R8: a status read has a 1s operational I/O budget; overrun is an
#: explicit error, never a silently-returned terminal state.
_IO_BUDGET_SECONDS = 1.0
#: Spec R8: minimum/maximum recommended polling backoff while unchanged.
_MIN_POLL_INTERVAL_MS = 5000
_MAX_POLL_INTERVAL_MS = 60000

_EXECUTION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _utcnow() -> datetime:
    """Return the current UTC instant (isolated so tests can inject a fake clock)."""
    return datetime.now(timezone.utc)


def _validate_execution_id(execution_id: str) -> str:
    """Reject a caller-supplied `execution_id` that is not a canonical UUID."""
    if not _EXECUTION_ID_RE.match(execution_id or ""):
        raise ValueError(f"execution_id must be a canonical UUID, got {execution_id!r}")
    return execution_id


class BackgroundNotFoundError(KeyError):
    """Raised when no registration exists for the given (execution_id, handle) pair.

    Also covers a "foreign" handle: one that was registered under a
    different `execution_id` than the one supplied -- the record simply
    never exists at that (execution_id, handle) path, so it is
    indistinguishable from (and exactly as safe as) "never registered".
    """


class BackgroundConflictError(ValueError):
    """Raised when a handle is already bound to a different launch identity.

    Never adopt a reused handle/PID: a second registration under the same
    `handle` with a different `launch_id`/`owner_instance_id`/`kind` is
    rejected instead of silently overwriting the original launch's identity.
    """


class BackgroundBudgetExceededError(TimeoutError):
    """Raised when a `status()` read exceeds its bounded 1s I/O budget.

    A timeout here is an explicit error, never a terminal state: the caller
    must not interpret it as `finished` or `unknown`.
    """


def _read_bounded_tail(path: Path, tail_bytes: int) -> Tuple[Optional[str], bool]:
    """Return up to the last *tail_bytes* of *path*, decoded safely.

    Never reads more than `tail_bytes` (plus the few leading continuation
    bytes it discards to keep a UTF-8 codepoint intact) off disk, regardless
    of how large the underlying file has grown -- the read request itself
    is bounded via `seek`, not just the string returned afterwards.
    """
    if not path.exists():
        return None, False
    total_size = path.stat().st_size
    if total_size == 0:
        return "", False
    start = max(0, total_size - tail_bytes)
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read(total_size - start)
    # Never start mid-codepoint: a continuation byte (0b10xxxxxx) at the
    # window's start means the character before it was cut in half.
    while data and (data[0] & 0xC0) == 0x80:
        data = data[1:]
        start += 1
    truncated = start > 0
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return text, truncated


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write *payload* as canonical JSON via temp-file-then-`os.replace`.

    A reader only ever observes *path* fully absent or fully present.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp_path.unlink()
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, path)


class _BackgroundRecord(BaseModel):
    """Internal persisted state for one (execution_id, handle) registration.

    Not part of the shared FEAT-584 contract (`optimization_models.py`) --
    this is `BackgroundRegistry`'s own private bookkeeping, versioned
    independently so it can gain fields later without touching the shared
    `BackgroundRegistration`/`BackgroundStatus` schemas other modules rely on.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    registration: BackgroundRegistration
    revision: int = 0
    revision_changed_at: Optional[datetime] = None
    state: Literal["pending", "running", "finished"] = "pending"
    outcome: Optional[Literal["completed", "failed", "timed_out", "cancelled"]] = None
    exit_code: Optional[int] = None
    verified_at: Optional[datetime] = None
    log_path: Optional[str] = None
    log_bytes_seen: int = 0
    log_ref: Optional[EvidenceRef] = None


class BackgroundRegistry:
    """Bind opaque handles to execution, worktree, owner instance and authority."""

    def __init__(self, *, store: ExecutionEvidenceStore, owner_instance_id: str) -> None:
        self.store = store
        self.owner_instance_id = owner_instance_id
        self.logger = logging.getLogger(__name__)
        self._locks: Dict[Tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def register(self, registration: BackgroundRegistration) -> str:
        """Persist a launch-bound registration and emit its idempotent handle."""
        lock = await self._lock_for(registration.execution_id, registration.handle)
        async with lock:
            path = self._record_path(registration.execution_id, registration.handle)
            existing = await asyncio.to_thread(self._read_record, path)
            if existing is not None:
                prior = existing.registration
                if (
                    prior.launch_id != registration.launch_id
                    or prior.owner_instance_id != registration.owner_instance_id
                    or prior.kind != registration.kind
                    or prior.worktree != registration.worktree
                    or prior.backend != registration.backend
                ):
                    raise BackgroundConflictError(
                        f"handle {registration.handle!r} is already bound to a different launch"
                        " identity -- refusing to adopt a reused handle (spec R8: never adopt by"
                        " PID/handle reuse)"
                    )
                # Idempotent replay of an identical registration: return the same
                # handle without disturbing whatever state has already progressed.
                return prior.handle

            record = _BackgroundRecord(registration=registration, revision_changed_at=_utcnow())
            await asyncio.to_thread(self._write_record, path, record)
            return registration.handle

    async def status(
        self,
        execution_id: str,
        handle: str,
        since_revision: int | None = None,
        tail_bytes: int = 2048,
    ) -> BackgroundStatus:
        """Read known state and a bounded registered log without waiting for completion."""
        if not (0 <= tail_bytes <= _MAX_TAIL_BYTES):
            raise ValueError(f"tail_bytes must be within 0..{_MAX_TAIL_BYTES}, got {tail_bytes!r}")

        started = time.monotonic()
        path = self._record_path(execution_id, handle)
        record = await asyncio.to_thread(self._read_record, path)
        if record is None:
            raise BackgroundNotFoundError(
                f"no background registration for execution_id={execution_id!r} handle={handle!r}"
            )

        registration = record.registration
        state = record.state
        outcome = record.outcome
        exit_code = record.exit_code
        verified_at = record.verified_at
        stale = False

        # Owner loss without a terminal receipt => unknown, never a resurrected
        # "running"/"finished" inferred from PID absence or PID reuse.
        owner_lost = registration.owner_instance_id != self.owner_instance_id
        if state != "finished" and owner_lost:
            state = "unknown"
            outcome = None
            exit_code = None
            verified_at = None
            stale = True

        changed = since_revision is None or since_revision != record.revision

        log_tail: Optional[str] = None
        log_truncated = False
        if changed and tail_bytes > 0 and record.log_path is not None:
            log_tail, log_truncated = await asyncio.to_thread(_read_bounded_tail, Path(record.log_path), tail_bytes)

        if changed:
            next_poll_after_ms = _MIN_POLL_INTERVAL_MS
        else:
            since_change_s = 0.0
            if record.revision_changed_at is not None:
                since_change_s = (_utcnow() - record.revision_changed_at).total_seconds()
            next_poll_after_ms = int(min(_MAX_POLL_INTERVAL_MS, max(_MIN_POLL_INTERVAL_MS, since_change_s * 1000)))

        elapsed = time.monotonic() - started
        if elapsed > _IO_BUDGET_SECONDS:
            raise BackgroundBudgetExceededError(
                f"coder_bg_status exceeded its {_IO_BUDGET_SECONDS}s I/O budget ({elapsed:.3f}s elapsed)"
            )

        return BackgroundStatus(
            state=state,
            outcome=outcome,
            exit_code=exit_code,
            source=f"background-registry:{registration.kind}",
            authority=registration.authority,
            verified_at=verified_at,
            stale=stale,
            revision=record.revision,
            changed=changed,
            log_tail=log_tail if changed else None,
            log_ref=record.log_ref if state == "finished" else None,
            log_truncated=log_truncated,
            elapsed_ms=max(0, int(elapsed * 1000)),
            next_poll_after_ms=next_poll_after_ms,
        )

    # -- internal: reported only by the owning authority, never the LLM ----

    async def _record_transition(
        self,
        execution_id: str,
        handle: str,
        *,
        state: Literal["running", "finished"],
        outcome: Optional[Literal["completed", "failed", "timed_out", "cancelled"]] = None,
        exit_code: Optional[int] = None,
        log_path: Optional[Path | str] = None,
    ) -> None:
        """Record a state transition reported by the authority owning this handle.

        Internal only -- called by the engine/supervisor/host_observation code
        that actually owns the process/job, in this same process. Takes an
        explicit, already-known `state`; never a PID to "adopt" and never
        waits here for a subprocess or test suite -- the caller decides when
        a transition happened. Revision only advances when `state` or the
        registered log's byte size actually changed, never from elapsed time
        alone.
        """
        lock = await self._lock_for(execution_id, handle)
        async with lock:
            path = self._record_path(execution_id, handle)
            record = await asyncio.to_thread(self._read_record, path)
            if record is None:
                raise BackgroundNotFoundError(
                    f"no background registration for execution_id={execution_id!r} handle={handle!r}"
                )

            registration = record.registration
            if registration.kind == "mcp_job" and exit_code is not None:
                raise ValueError("a logical MCP job never carries a POSIX exit_code (spec R8)")
            if registration.authority == "host_observation" and exit_code is not None:
                raise ValueError("host_observation authority never yields a POSIX exit_code (spec R8)")

            resolved_log_path: Optional[Path] = None
            log_bytes = record.log_bytes_seen
            if log_path is not None:
                resolved_log_path, log_bytes = await asyncio.to_thread(
                    self._resolve_confined_log_path, log_path, log_bytes
                )

            changed = state != record.state or log_bytes != record.log_bytes_seen
            if changed:
                record.revision += 1
                record.revision_changed_at = _utcnow()

            record.state = state
            record.outcome = outcome
            record.exit_code = exit_code
            record.verified_at = _utcnow()
            if resolved_log_path is not None:
                record.log_path = str(resolved_log_path)
                record.log_bytes_seen = log_bytes

            if state == "finished" and record.log_path is not None:
                final_bytes = await asyncio.to_thread(Path(record.log_path).read_bytes)
                digest = hashlib.sha256(final_bytes).hexdigest()
                record.log_ref = EvidenceRef(
                    artifact_id=digest,
                    sha256=digest,
                    relative_path=str(Path(record.log_path).relative_to(self.store.root)),
                    size_bytes=len(final_bytes),
                    media_type="text/plain",
                )

            await asyncio.to_thread(self._write_record, path, record)

    # -- confined path resolution + persistence -----------------------------

    def _record_path(self, execution_id: str, handle: str) -> Path:
        """Resolve the durable slot for (execution_id, handle) via a safe filename.

        `handle` is caller-opaque free text; it is never used verbatim as a
        path component -- only its sha256 digest is, so it can never escape
        `executions/<execution_id>/background/`.
        """
        _validate_execution_id(execution_id)
        if not handle:
            raise ValueError("handle must be a non-empty string")
        digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()
        return self.store.root / "executions" / execution_id / "background" / f"{digest}.json"

    def _resolve_confined_log_path(self, log_path: Path | str, previous_log_bytes: int) -> Tuple[Path, int]:
        """Resolve *log_path*, reject an escape from the durable root, and stat it.

        Run off the event loop via `asyncio.to_thread` -- `Path.resolve()`
        and `Path.stat()` are blocking filesystem calls.
        """
        resolved_log_path = Path(log_path).resolve()
        store_root = self.store.root.resolve()
        if resolved_log_path != store_root and store_root not in resolved_log_path.parents:
            raise ValueError(f"log_path must stay confined under the durable evidence root: {log_path!r}")
        log_bytes = previous_log_bytes
        if resolved_log_path.exists():
            log_bytes = resolved_log_path.stat().st_size
        return resolved_log_path, log_bytes

    def _read_record(self, path: Path) -> Optional[_BackgroundRecord]:
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return _BackgroundRecord.model_validate(raw)

    def _write_record(self, path: Path, record: _BackgroundRecord) -> None:
        _atomic_write_json(path, record.model_dump(mode="json"))

    async def _lock_for(self, execution_id: str, handle: str) -> asyncio.Lock:
        """Return the (lazily created) in-process lock serializing one handle."""
        key = (execution_id, handle)
        async with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock
