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
import shlex
import signal
import subprocess
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import BackgroundRegistration, BackgroundStatus, EvidenceRef
from parrot.flows.dev_loop.test_scope import baseline, green_cache
from parrot.flows.dev_loop.test_scope import report as test_report
from parrot.flows.dev_loop.test_scope.contract import (
    contract_from_index_header,
    load_index_header,
    parse_validation_commands,
)
from parrot.flows.dev_loop.test_scope.datatypes import BaselineVerdict, RunReport, ValidationVerdict
from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry, load_registry
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests
from parrot.flows.dev_loop.test_scope.verdict import build_verdict, verdict_from_json, verdict_to_json
from parrot.flows.dev_loop.task_scheduler import iter_index_files
from parrot.flows.dev_loop.worktree_environment import protected_argv

if TYPE_CHECKING:  # never imported at runtime -- annotations only (deferred by `__future__`).
    from parrot.flows.dev_loop.test_scope.datatypes import Invocation, ScopePlan

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
#: Same closed shape as `optimization_models._TASK_ID_PATTERN` (not imported --
#: that module's validators are private to its own field declarations).
#: FEAT-698: brief tasks carry local `HOTFIX-<KEY>-<N>` ids as well as `TASK-<NNN>`.
_TASK_ID_RE = re.compile(r"^(?:TASK-\d{1,5}|HOTFIX-[A-Za-z0-9][A-Za-z0-9._-]*-\d{1,5})$")
#: FEAT-695: canonical feature id shape for test-result records.
_FEATURE_ID_RE = re.compile(r"^(?:FEAT-\d+|BRIEF-[A-Za-z0-9][A-Za-z0-9._-]*)$")

#: Spec R8: `coder_run_validation(..., timeout_seconds)` is mandatory, 1..7200.
_MIN_TIMEOUT_SECONDS = 1
_MAX_TIMEOUT_SECONDS = 7200
#: `select_tests.py`'s own CLI default base ref (spec R8 gives `ValidationSupervisor.start()`
#: no base_ref parameter of its own; mirroring the existing tool's default is a
#: bounded, documented choice, not an invented API -- see module docstring below).
_DEFAULT_BASE_REF = "origin/dev"
#: Bound the on-disk supervised log growth independently of `status()`'s own
#: 0..4096 `tail_bytes` read budget -- a "log grande" child must never grow the
#: registered log file unboundedly, but draining the pipe itself must never
#: stall waiting on the caller (spec R8: acotar log en disco).
_MAX_SUPERVISED_LOG_BYTES = 1_048_576
_DRAIN_CHUNK_BYTES = 65536
#: Grace window between an owned tree's SIGTERM and an escalation to SIGKILL
#: once a deadline is imposed (spec R8: "terminar árbol propio, esperar reap").
_TERMINATE_GRACE_SECONDS = 5.0


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


class _VerdictArtifact(BaseModel):
    """Pydantic envelope accepted by ``ExecutionEvidenceStore.put_artifact``."""

    payload: dict[str, object]


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


class ValidationSupervisor:
    """Own admitted validation processes, bounded log drains, deadlines and terminal receipts.

    ``start()`` admits ONE `coder_run_validation`-shaped request: it validates
    the request's own shape, persists it via `BackgroundRegistry.register`
    (idempotent by construction -- see `_payload_hash`), builds the tier-scoped
    selection from the existing test-scope selector (never a free-form argv),
    and spawns its first protected subprocess -- but it never awaits the
    *suite's* completion (spec R8: "devuelve handle sin esperar la suite").
    Draining, the deadline and the terminal receipt run in a background
    `asyncio.Task` that reports through `BackgroundRegistry._record_transition`
    -- the SAME internal method `BackgroundRegistry.status()` already reads
    (spec/TASK-3563: no parallel state-transition path).

    A `request_id` reused with an IDENTICAL payload never spawns a second
    process (idempotent replay, in-process claim); reused with a DIFFERENT
    payload is rejected by `BackgroundRegistry.register` itself
    (`BackgroundConflictError`), because `launch_id` is a canonical hash of
    that payload. A genuine admission failure (bad selection, a missing
    `bwrap`, a spawn error) never leaves a falsely-settled record: the
    registration stays `pending` (still blocking checkpoint/cleanup, per this
    module's own docstring) and the in-process claim is released so a later
    retry under the SAME `request_id` is not permanently locked out.

    Known, bounded scope decisions: `task_ids` is validated for shape
    (`TASK-<1-5 digits>`, non-empty) and folded into the payload hash. When
    the engine supplies `index_path`, the supervisor reads those tasks'
    declared `Validation Commands` plus the index `test_contract`; legacy
    callers without an index retain the bounded fallback selector. The diff
    base remains server-derived and is deliberately excluded from the
    caller payload hash. Baseline comparison uses the index header's
    `base_branch`, falling back to `origin/dev` when unavailable.
    """

    def __init__(self, *, registry: BackgroundRegistry, store: ExecutionEvidenceStore) -> None:
        self.registry = registry
        self.store = store
        self.logger = logging.getLogger(__name__)
        # In-process admission guard: keyed by (execution_id, handle), true only
        # once a process has actually been spawned (or the selection settled
        # with nothing to run). Never persisted -- a real restart must reconcile
        # through `BackgroundRegistry.status()`'s own owner-loss/`unknown` path,
        # never resurrect a claim from memory.
        self._claims: Dict[Tuple[str, str], bool] = {}
        self._claims_guard = asyncio.Lock()
        # Test/introspection seam: the background task settling this handle's
        # terminal receipt, so a caller that needs to observe settlement (e.g.
        # this task's own test suite) can await it deterministically instead
        # of polling `coder_bg_status` in a tight loop.
        self._background_tasks: Dict[Tuple[str, str], "asyncio.Task[None]"] = {}
        self._verdict_refs: Dict[Tuple[str, str], EvidenceRef] = {}

    async def start(
        self,
        *,
        feature: str,
        worktree: Path,
        execution_id: str,
        task_ids: list[str],
        tier: Literal["task", "merge", "feature"],
        timeout_seconds: int,
        request_id: str,
        base_ref: Optional[str] = None,
        index_path: Optional[Path] = None,
        attempt_uid: Optional[str] = None,
    ) -> BackgroundRegistration:
        """Admit only a declared, protected, idempotent selection; never await the suite.

        `base_ref` is the diff base the tier-scoped selection is computed from.
        The caller (`SddCoderEngine.run_validation`) resolves it deterministically
        from the merged task branches themselves, so a merge-tier check covers
        what THIS chunk introduced instead of the feature branch's whole
        cumulative diff against `origin/dev` -- re-validating every previously
        merged task on every merge made the selection grow with the feature and
        escalated whole package suites (impact cap / core paths) long before the
        feature was done. `None` keeps the historical `_DEFAULT_BASE_REF`
        behaviour, which is also the deliberate fallback whenever the caller
        cannot resolve a narrower base: slower, never less covered.

        It is deliberately NOT part of `_payload_hash`: the base is derived
        server-side from repository state, not declared by the caller, so
        folding it in would turn a legitimate idempotent replay (same
        `request_id`, same declared payload) into a `BackgroundConflictError`
        as soon as another task merged in between.

        `index_path` is likewise resolved by the engine from the feature
        context and is not caller-declared payload, so it is deliberately
        excluded from `_payload_hash`.

        Raises:
            ValueError: a malformed request (bad ids, tier, timeout, paths).
            BackgroundConflictError: `request_id` reused with a different payload.
            RuntimeError: `bwrap` is unavailable -- never silently unsandboxed.
            OSError: the protected subprocess itself could not be spawned.
        """
        _validate_execution_id(execution_id)
        if not feature:
            raise ValueError("feature must be a non-empty string")
        if not worktree.is_absolute():
            raise ValueError(f"worktree must be an absolute path, got {worktree!r}")
        if tier not in ("task", "merge", "feature"):
            raise ValueError(f"tier must be 'task', 'merge' or 'feature', got {tier!r}")
        if tier == "task":
            if len(task_ids) != 1:
                raise ValueError("tier='task' admits exactly one task id")
            if not base_ref or not attempt_uid:
                raise ValueError("tier='task' requires an explicit base_ref (fork SHA) and attempt_uid")
        if not (_MIN_TIMEOUT_SECONDS <= timeout_seconds <= _MAX_TIMEOUT_SECONDS):
            raise ValueError(
                f"timeout_seconds must be within {_MIN_TIMEOUT_SECONDS}..{_MAX_TIMEOUT_SECONDS},"
                f" got {timeout_seconds!r}"
            )
        if not task_ids:
            raise ValueError("task_ids must be a non-empty list")
        for task_id in task_ids:
            if not _TASK_ID_RE.match(task_id):
                raise ValueError(
                    f"invalid task id {task_id!r}; expected TASK-<1-5 digits>"
                    " or HOTFIX-<KEY>-<1-5 digits> (never a foreign id)"
                )
        if not request_id:
            raise ValueError("request_id must be a non-empty string")
        if base_ref is not None and not base_ref.strip():
            raise ValueError("base_ref must be a non-empty string when supplied")

        handle = request_id
        launch_id = self._payload_hash(
            feature=feature,
            worktree=worktree,
            task_ids=task_ids,
            tier=tier,
            timeout_seconds=timeout_seconds,
            attempt_uid=attempt_uid,
        )
        registration = BackgroundRegistration(
            handle=handle,
            execution_id=execution_id,
            launch_id=launch_id,
            owner_instance_id=self.registry.owner_instance_id,
            kind="validation",
            authority="supervisor",
            worktree=str(worktree),
            backend="validation-subprocess",
            started_at=_utcnow(),
        )
        # Idempotent by construction: a `request_id` replayed with the SAME
        # payload round-trips through the SAME `launch_id` (no conflict, no new
        # process below); replayed with a DIFFERENT payload raises here,
        # before anything is spawned (spec R8: "payload distinto es error,
        # nunca segundo proceso silencioso").
        await self.registry.register(registration)

        if not await self._claim(execution_id, handle):
            # Another call already admitted (or is admitting) this exact
            # request in this process -- idempotent no-op, never a second spawn.
            return registration

        try:
            feature_id = await asyncio.to_thread(self._resolve_feature_id, worktree, feature)
            runner_registry = await asyncio.to_thread(load_registry, worktree)
            plan = await self._plan_selection(
                worktree=worktree,
                tier=tier,
                base_ref=base_ref,
                index_path=index_path,
                task_ids=task_ids,
                feature_id=feature_id,
                registry=runner_registry,
            )
            baseline_ref, contract_digest = await asyncio.to_thread(self._index_runtime_metadata, index_path)
            namespace = await asyncio.to_thread(
                green_cache.cache_namespace,
                feature_id=feature_id,
                base_ref=baseline_ref,
                contract_digest=contract_digest,
            )
            log_path = self._log_path(execution_id, handle)
            await asyncio.to_thread(log_path.parent.mkdir, parents=True, exist_ok=True)

            if plan.cached:
                head_sha = await asyncio.to_thread(self._head_sha, worktree)
                for task_id in task_ids:
                    await asyncio.to_thread(
                        test_report.append_cached,
                        feature_id,
                        task_id,
                        plan.cached,
                        head_sha=head_sha,
                        base_ref=baseline_ref,
                        tier=tier,
                        source="coder_run_validation",
                    )

            if not plan.invocations:
                await asyncio.to_thread(
                    self._append_log,
                    log_path,
                    self._selection_header(plan) + "# no applicable pytest invocations for this selection\n",
                )
                await self._persist_verdict_and_settle(
                    execution_id=execution_id,
                    handle=handle,
                    log_path=log_path,
                    verdict=build_verdict(tier=tier, reports=(), cached=plan.cached, notes=plan.notes),
                    outcome="completed",
                    exit_code=0,
                )
                return registration

            first, *rest = plan.invocations
            await asyncio.to_thread(self._append_log, log_path, self._selection_header(plan))
            first, first_argv, first_report = self._prepare_invocation(feature_id, task_ids[0], first, 0)
            sandboxed_argv = protected_argv(worktree, first_argv)
            await asyncio.to_thread(
                self._append_log, log_path, f"# $ {shlex.join(first.argv)} (distribution={first.distribution})\n"
            )
            process = await asyncio.create_subprocess_exec(
                *sandboxed_argv,
                cwd=worktree / first.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,  # own process group -- a deadline can kill the whole owned tree.
            )
            await self.registry._record_transition(execution_id, handle, state="running", log_path=log_path)
        except Exception:
            # A spawn/admission failure must never look like a settled
            # validation: the registry's own record stays `pending` (still
            # blocking checkpoint/cleanup), and the claim is released so a
            # later retry under the SAME request_id is not locked out forever.
            await self._release_claim(execution_id, handle)
            self.logger.exception(
                "validation supervisor failed to admit handle=%s execution_id=%s", handle, execution_id
            )
            raise

        deadline = time.monotonic() + timeout_seconds
        first_deadline = min(deadline, time.monotonic() + runner_registry.timeout_for(first.runner))
        task = asyncio.ensure_future(
            self._supervise(
                execution_id=execution_id,
                handle=handle,
                process=process,
                log_path=log_path,
                deadline=deadline,
                invocation_deadline=first_deadline,
                remaining_invocations=list(rest),
                first_invocation=first,
                plan=plan,
                worktree=worktree,
                feature_id=feature_id,
                task_ids=list(task_ids),
                tier=tier,
                base_ref=baseline_ref,
                cache_namespace=namespace,
                first_report_path=first_report,
                runner_registry=runner_registry,
            )
        )
        self._background_tasks[(execution_id, handle)] = task
        return registration

    async def wait_verdict(self, execution_id: str, handle: str, timeout_s: float) -> "ValidationVerdict":
        """Block until ``handle`` settles, then return its persisted validation verdict."""
        await self.wait(execution_id, handle, timeout_s)
        status = await self.registry.status(execution_id, handle, tail_bytes=_MAX_TAIL_BYTES)
        if status.state != "finished":
            raise asyncio.TimeoutError(f"validation handle {handle!r} did not settle within {timeout_s} seconds")

        evidence_ref = self._verdict_refs.get((execution_id, handle))
        if evidence_ref is None:
            ref_path = self._verdict_ref_path(execution_id, handle)
            try:
                ref_payload = await asyncio.to_thread(json.loads, ref_path.read_text(encoding="utf-8"))
                artifact_id = str(ref_payload["artifact_id"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise RuntimeError(f"validation handle {handle!r} settled without a verdict artifact") from exc
            if not re.fullmatch(r"[0-9a-f]{64}", artifact_id):
                raise RuntimeError(f"validation handle {handle!r} has an invalid verdict artifact id")
        else:
            artifact_id = evidence_ref.artifact_id

        page = await self.store.read_artifact(execution_id, artifact_id, limit=16384)
        if not page["eof"]:
            raise RuntimeError(f"validation verdict artifact {artifact_id!r} exceeds the bounded read budget")
        envelope = json.loads(str(page["content"]))
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(payload, dict):
            raise RuntimeError(f"validation verdict artifact {artifact_id!r} has an invalid envelope")
        verdict = verdict_from_json(payload)
        return replace(verdict, evidence=(*verdict.evidence, artifact_id))

    async def wait(self, execution_id: str, handle: str, timeout_seconds: float) -> bool:
        """Block up to *timeout_seconds* for this handle's OWN settlement task, without cancelling it.

        Returns True when a settlement task for `(execution_id, handle)` is
        owned by THIS supervisor instance and was awaited (whether it settled
        within the budget or the wait expired), False when there is nothing to
        await here -- a handle registered by another launch path, an already
        drained entry, or a process this instance no longer owns. The caller
        (`SddCoderEngine.bg_wait`) falls back to bounded polling on False, so a
        `False` answer never means "finished" and never invents a receipt.

        The task is `shield`-ed: a caller's expiring budget must never cancel
        the supervision that owns the child process, its deadline and its
        terminal receipt. A settlement failure is not re-raised either -- it is
        already logged and recorded by `_supervise`; this method only ever
        reports *whether it waited*, never an outcome. The authoritative state
        stays `BackgroundRegistry.status()`.
        """
        task = self._background_tasks.get((execution_id, handle))
        if task is None:
            return False
        if timeout_seconds > 0 and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout_seconds)
            except asyncio.TimeoutError:
                pass
            except Exception:
                # `_supervise` already logged and recorded whatever went wrong;
                # the authoritative answer is the registry's, not this wait's.
                # `CancelledError` is deliberately NOT swallowed: it means the
                # CALLER was cancelled (the shielded task never is).
                self.logger.debug(
                    "background settlement raised while waiting on handle=%s; status stays authoritative", handle
                )
        return True

    # -- admission helpers ---------------------------------------------------

    async def _claim(self, execution_id: str, handle: str) -> bool:
        """Atomically claim (execution_id, handle) once per supervisor instance."""
        key = (execution_id, handle)
        async with self._claims_guard:
            if self._claims.get(key):
                return False
            self._claims[key] = True
            return True

    async def _release_claim(self, execution_id: str, handle: str) -> None:
        """Undo a claim after an admission failure, so a retry is not locked out."""
        async with self._claims_guard:
            self._claims.pop((execution_id, handle), None)

    @staticmethod
    def _payload_hash(
        *,
        feature: str,
        worktree: Path,
        task_ids: list[str],
        tier: str,
        timeout_seconds: int,
        attempt_uid: Optional[str] = None,
    ) -> str:
        """Deterministic identity for one validation request's own payload.

        Bound into `BackgroundRegistration.launch_id`: `BackgroundRegistry.register`
        already refuses a same-handle replay whose identity differs, so
        encoding the full request payload here turns that EXISTING conflict
        check into `request_id`-level idempotency without a second bookkeeping
        path (spec R8).
        """
        canonical = json.dumps(
            {
                "feature": feature,
                "worktree": str(worktree),
                "task_ids": sorted(task_ids),
                "tier": tier,
                "timeout_seconds": timeout_seconds,
                "attempt_uid": attempt_uid,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def _plan_selection(
        self,
        *,
        worktree: Path,
        tier: Literal["task", "merge", "feature"],
        base_ref: Optional[str] = None,
        index_path: Optional[Path] = None,
        task_ids: Sequence[str] = (),
        feature_id: str = "",
        registry: Optional[RunnerRegistry] = None,
    ) -> "ScopePlan":
        """Tier-scoped selection: task declarations plus spec contract; never a free-form argv.

        Raises:
            ValueError: The index or its ``test_contract`` is malformed.
        """
        changed = await asyncio.to_thread(changed_files, worktree, base_ref or _DEFAULT_BASE_REF)
        declared: list[list[str]] = []
        contract = None
        baseline_ref = _DEFAULT_BASE_REF
        if index_path is not None:
            header = await asyncio.to_thread(load_index_header, index_path)
            contract = await asyncio.to_thread(contract_from_index_header, header)
            baseline_ref = self._base_ref_from_header(header)
            declared = await asyncio.to_thread(self._load_declared_commands, index_path, worktree, task_ids)
        if index_path is None:
            return await asyncio.to_thread(
                plan_tests, worktree=worktree, changed_files=changed, tier=tier, registry=registry
            )
        plan = await asyncio.to_thread(
            plan_tests,
            worktree=worktree,
            changed_files=changed,
            tier=tier,
            declared=declared,
            contract=contract,
            registry=registry,
        )
        if tier == "merge":
            namespace = await asyncio.to_thread(
                green_cache.cache_namespace,
                feature_id=feature_id,
                base_ref=baseline_ref,
                contract_digest=contract.digest if contract is not None else "",
            )
            plan = await asyncio.to_thread(
                green_cache.filter_cached,
                worktree,
                plan,
                namespace=namespace,
                contract=contract,
            )
            self.logger.info(
                "validation green cache feature=%s selected=%d cached=%d",
                feature_id,
                len(plan.invocations),
                len(plan.cached),
            )
        return plan

    @staticmethod
    def _load_declared_commands(index_path: Path, worktree: Path, task_ids: Sequence[str]) -> list[list[str]]:
        """Read selected task files from one per-spec index and parse their validation commands."""
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"unable to read task declarations from {index_path}") from exc
        tasks = payload.get("tasks") if isinstance(payload, dict) else None
        if not isinstance(tasks, list):
            raise ValueError("index tasks must be a list")
        by_id = {
            item.get("id"): item.get("file")
            for item in tasks
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("file"), str)
        }
        declared: list[list[str]] = []
        for task_id in task_ids:
            task_file = by_id.get(task_id)
            if task_file is None:
                raise ValueError(f"task {task_id!r} is not declared in {index_path}")
            try:
                task_markdown = (worktree / task_file).read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"unable to read task file {task_file!r} for {task_id}") from exc
            declared.extend(parse_validation_commands(task_markdown))
        return declared

    @staticmethod
    def _base_ref_from_header(header: dict[str, object]) -> str:
        """Return ``origin/<base_branch>`` or the safe historical default."""
        base_branch = header.get("base_branch")
        if isinstance(base_branch, str) and base_branch.strip():
            return f"origin/{base_branch.strip()}"
        return _DEFAULT_BASE_REF

    @classmethod
    def _index_runtime_metadata(cls, index_path: Optional[Path]) -> tuple[str, str]:
        """Return baseline ref and contract digest for cache/report wiring."""
        if index_path is None:
            return _DEFAULT_BASE_REF, ""
        header = load_index_header(index_path)
        contract = contract_from_index_header(header)
        return cls._base_ref_from_header(header), contract.digest if contract is not None else ""

    @staticmethod
    def _head_sha(worktree: Path) -> str:
        """Return the worktree HEAD SHA, or an empty string when unavailable."""
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, timeout=30, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else ""

    def _log_path(self, execution_id: str, handle: str) -> Path:
        """Confined, opaque-named slot for this handle's supervised log (mirrors `_record_path`)."""
        digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()
        return self.store.root / "executions" / execution_id / "background_logs" / f"{digest}.log"

    def _verdict_ref_path(self, execution_id: str, handle: str) -> Path:
        """Return the durable, handle-keyed link to a persisted verdict artifact."""
        _validate_execution_id(execution_id)
        digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()
        return self.store.root / "executions" / execution_id / "background_verdicts" / f"{digest}.json"

    # -- background supervision (never awaited by `start()` itself) ---------

    async def _supervise(
        self,
        *,
        execution_id: str,
        handle: str,
        process: "asyncio.subprocess.Process",
        log_path: Path,
        deadline: float,
        invocation_deadline: float,
        remaining_invocations: list["Invocation"],
        first_invocation: "Invocation",
        plan: "ScopePlan",
        worktree: Path,
        feature_id: str = "",
        task_ids: Optional[list[str]] = None,
        tier: str = "merge",
        base_ref: str = _DEFAULT_BASE_REF,
        cache_namespace: str = "",
        first_report_path: Optional[Path] = None,
        runner_registry: RunnerRegistry,
    ) -> None:
        """Run every invocation with its own deadline under the overall cap, then settle."""
        reports: list[RunReport] = []
        baseline_verdicts: list[BaselineVerdict] = []
        cache_candidates: list[tuple["Invocation", test_report.SuiteResult]] = []
        invocation_records = [(first_invocation, process, first_report_path, invocation_deadline)]

        for invocation in remaining_invocations:
            invocation_records.append((invocation, None, None, 0.0))

        last_exit_code = 0
        for ordinal, (invocation, owned_process, report_path, runner_deadline) in enumerate(invocation_records):
            started = time.monotonic()
            log_offset = await asyncio.to_thread(lambda: log_path.stat().st_size if log_path.exists() else 0)
            if owned_process is None:
                invocation, argv, report_path = self._prepare_invocation(
                    feature_id, (task_ids or ["TASK-0"])[0], invocation, ordinal
                )
                if time.monotonic() >= deadline:
                    report = await self._parse_invocation_report(
                        registry=runner_registry,
                        invocation=invocation,
                        report_path=report_path,
                        exit_code=124,
                        duration_s=0.0,
                        timed_out=True,
                        stdout="",
                    )
                    reports.append(report)
                    last_exit_code = 124
                    continue
                try:
                    sandboxed_argv = protected_argv(worktree, argv)
                    await asyncio.to_thread(
                        self._append_log,
                        log_path,
                        f"# $ {shlex.join(invocation.argv)} (distribution={invocation.distribution})\n",
                    )
                    owned_process = await asyncio.create_subprocess_exec(
                        *sandboxed_argv,
                        cwd=worktree / invocation.cwd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        start_new_session=True,
                    )
                    runner_deadline = min(deadline, time.monotonic() + runner_registry.timeout_for(invocation.runner))
                except Exception:
                    self.logger.exception(
                        "validation supervisor failed to launch a chained invocation for handle=%s", handle
                    )
                    report = await self._parse_invocation_report(
                        registry=runner_registry,
                        invocation=invocation,
                        report_path=report_path,
                        exit_code=1,
                        duration_s=time.monotonic() - started,
                        timed_out=False,
                        stdout="",
                    )
                    reports.append(report)
                    last_exit_code = 1
                    continue

            invocation_outcome, exit_code = await self._await_one(
                process=owned_process, log_path=log_path, deadline=runner_deadline
            )
            stdout = await asyncio.to_thread(self._read_log_since, log_path, log_offset)
            last_exit_code = exit_code
            report = await self._parse_invocation_report(
                registry=runner_registry,
                invocation=invocation,
                report_path=report_path,
                exit_code=exit_code,
                duration_s=time.monotonic() - started,
                timed_out=invocation_outcome == "timed_out",
                stdout=stdout,
            )
            report, invocation_baseline, suite_result = await self._record_run_report(
                worktree=worktree,
                feature_id=feature_id,
                task_ids=task_ids or [],
                invocation=invocation,
                report=report,
                tier=tier,
                base_ref=base_ref,
                deadline=deadline,
            )
            reports.append(report)
            baseline_verdicts.extend(invocation_baseline)
            if suite_result is not None:
                cache_candidates.append((invocation, suite_result))

        verdict = build_verdict(
            tier=tier,
            reports=reports,
            baseline=baseline_verdicts,
            cached=plan.cached,
            notes=plan.notes,
        )
        if verdict.status != "timed_out":
            for invocation, result in cache_candidates:
                if invocation.runner == "pytest":
                    await self._record_green_cache(
                        worktree=worktree,
                        namespace=cache_namespace,
                        plan=plan,
                        invocation=invocation,
                        result=result,
                    )

        outcome: Literal["completed", "failed", "timed_out"]
        if verdict.status == "passed":
            outcome, last_exit_code = "completed", 0
            if baseline_verdicts and all(item.status == "baseline_red" for item in baseline_verdicts):
                await asyncio.to_thread(self._append_log, log_path, "# baseline: only baseline reds — gate passes\n")
        elif verdict.status == "timed_out":
            outcome = "timed_out"
        else:
            outcome = "failed"
        await self._persist_verdict_and_settle(
            execution_id=execution_id,
            handle=handle,
            log_path=log_path,
            verdict=verdict,
            outcome=outcome,
            exit_code=last_exit_code,
        )

    def _prepare_invocation(
        self, feature_id: str, task_id: str, invocation: "Invocation", ordinal: int
    ) -> tuple["Invocation", list[str], Optional[Path]]:
        """Attach a fresh adapter report path and return the executable argv."""
        report_path: Optional[Path] = None
        prepared = invocation
        if invocation.report_path:
            candidate = Path(invocation.report_path)
            report_path = candidate if candidate.is_absolute() else Path(invocation.cwd) / candidate
        elif invocation.report_format in {"junit", "json"}:
            try:
                suite = f"{invocation.runner}-{invocation.distribution}".replace("/", "-")
                report_path = test_report.junit_path_for(feature_id, task_id, suite, ordinal)
                if invocation.report_format == "json":
                    report_path = report_path.with_suffix(".json")
            except Exception:  # noqa: BLE001 — report setup must never alter the validation outcome
                self.logger.warning(
                    "could not prepare a %s report path for %s",
                    invocation.runner,
                    invocation.distribution,
                    exc_info=True,
                )

        prepared = replace(invocation, report_path=str(report_path) if report_path is not None else "")
        argv = list(prepared.argv)
        if prepared.runner == "pytest" and report_path is not None:
            argv = list(test_report.with_report(prepared, report_path))
        elif prepared.runner == "vitest" and report_path is not None:
            argv = [
                f"--outputFile={report_path}" if argument.startswith("--outputFile=") else argument for argument in argv
            ]
            prepared = replace(prepared, argv=tuple(argv))
        return prepared, argv, report_path

    @staticmethod
    async def _parse_invocation_report(
        *,
        registry: RunnerRegistry,
        invocation: "Invocation",
        report_path: Optional[Path],
        exit_code: int,
        duration_s: float,
        timed_out: bool,
        stdout: str,
    ) -> RunReport:
        """Parse one runner-owned report without blocking the event loop."""
        adapter = registry.adapter_for_kind(invocation.runner)
        suite = test_report.suite_name(invocation)
        return await asyncio.to_thread(
            adapter.parse_report,
            report_path=report_path,
            exit_code=exit_code,
            stdout=stdout,
            stderr="",
            duration_s=duration_s,
            timed_out=timed_out,
            suite=suite,
        )

    @staticmethod
    def _read_log_since(log_path: Path, offset: int) -> str:
        """Return the bounded output appended by one invocation."""
        with log_path.open("rb") as log_handle:
            log_handle.seek(offset)
            return log_handle.read(_MAX_SUPERVISED_LOG_BYTES).decode("utf-8", errors="replace")

    async def _record_run_report(
        self,
        *,
        worktree: Path,
        feature_id: str,
        task_ids: list[str],
        invocation: "Invocation",
        report: RunReport,
        tier: str,
        base_ref: str,
        deadline: float,
    ) -> tuple[RunReport, tuple[BaselineVerdict, ...], Optional[test_report.SuiteResult]]:
        """Persist compatibility evidence and classify pytest failures against baseline."""
        if invocation.runner != "pytest":
            return report, (), None

        failed_nodes = [nodeid for nodeid, status in report.nodes if status in ("failed", "error")]
        verdicts: tuple[BaselineVerdict, ...] = ()
        if report.exit_code != 0 and failed_nodes:
            remaining = deadline - time.monotonic()
            if remaining < 30:
                verdicts = tuple(
                    BaselineVerdict(nodeid, "unknown", "less than 30 seconds remained") for nodeid in failed_nodes
                )
            else:
                try:
                    verdicts = await asyncio.wait_for(
                        asyncio.to_thread(
                            baseline.classify_failures,
                            worktree=worktree,
                            base_ref=base_ref,
                            failed_nodeids=failed_nodes,
                            timeout_s=max(1, int(remaining)),
                        ),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    verdicts = tuple(
                        BaselineVerdict(nodeid, "unknown", "baseline classification timed out")
                        for nodeid in failed_nodes
                    )

        suite_result = test_report.SuiteResult(
            suite=report.suite,
            tests=report.tests,
            passed=report.passed,
            failed=report.failed,
            errors=report.errors,
            skipped=report.skipped,
            duration_s=report.duration_s,
            exit_code=report.exit_code,
            argv=tuple(invocation.argv),
            status=report.status,
            nodes=report.nodes,
            unmapped=report.unmapped,
            baseline=tuple((item.nodeid, item.status) for item in verdicts),
        )
        head_sha = await asyncio.to_thread(self._head_sha, worktree)
        for task_id in task_ids:
            await asyncio.to_thread(
                test_report.append_suite,
                feature_id,
                task_id,
                suite_result,
                head_sha=head_sha,
                base_ref=base_ref,
                tier=tier,
                source="coder_run_validation",
            )
        return report, verdicts, suite_result

    async def _persist_verdict_and_settle(
        self,
        *,
        execution_id: str,
        handle: str,
        log_path: Path,
        verdict: ValidationVerdict,
        outcome: Literal["completed", "failed", "timed_out"],
        exit_code: int,
    ) -> None:
        """Persist the verdict and its receipt link before publishing terminal state."""
        evidence_ref = await self.store.put_artifact(execution_id, _VerdictArtifact(payload=verdict_to_json(verdict)))
        self._verdict_refs[(execution_id, handle)] = evidence_ref
        await asyncio.to_thread(
            _atomic_write_json,
            self._verdict_ref_path(execution_id, handle),
            {"artifact_id": evidence_ref.artifact_id},
        )
        await self.registry._record_transition(
            execution_id,
            handle,
            state="finished",
            outcome=outcome,
            exit_code=exit_code,
            log_path=log_path,
        )

    @staticmethod
    def _resolve_feature_id(worktree: Path, feature: str) -> str:
        """Resolve *feature* to ``FEAT-<NNN>``/``BRIEF-<KEY>`` via the feature or brief index header; fall back to the raw value."""
        if _FEATURE_ID_RE.match(feature):
            return feature
        try:
            for index_path in iter_index_files(worktree):
                try:
                    header = json.loads(index_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(header, dict):
                    continue
                feature_id = header.get("feature_id")
                if (
                    header.get("feature") == feature
                    and isinstance(feature_id, str)
                    and _FEATURE_ID_RE.match(feature_id)
                ):
                    return feature_id
        except OSError:
            pass
        logger.warning(
            "could not resolve feature %r to a FEAT-<NNN>/BRIEF-<KEY> id; recording under the raw value", feature
        )
        return feature

    @staticmethod
    def _argv_with_junit(
        feature_id: str, task_id: str, invocation: "Invocation", ordinal: int, *, enabled: bool = True
    ) -> Tuple[list[str], Optional[Path]]:
        """Return the invocation argv plus a unique junit path; plain argv when the path is unavailable."""
        if not enabled:
            return list(invocation.argv), None
        try:
            junit = test_report.junit_path_for(feature_id, task_id, invocation.distribution, ordinal)
            return list(test_report.with_report(invocation, junit)), junit
        except Exception:  # noqa: BLE001 — recording setup must never block a validation
            logger.warning("could not prepare a junit report path for %s", invocation.distribution, exc_info=True)
            return list(invocation.argv), None

    async def _record_test_results(
        self,
        *,
        worktree: Path,
        feature_id: str,
        task_ids: list[str],
        invocation: "Invocation",
        junit_path: Path,
        exit_code: int,
        duration_s: float,
        timed_out: bool,
        tier: str,
        base_ref: str,
        deadline: float,
    ) -> Optional[test_report.SuiteResult]:
        """Write one test-report record per task id and return its parsed evidence."""
        try:
            head_sha = await asyncio.to_thread(self._head_sha, worktree)
            suite = await asyncio.to_thread(test_report.suite_name, invocation)
            result = await asyncio.to_thread(
                test_report.parse_junit,
                junit_path,
                suite=suite,
                argv=tuple(invocation.argv),
                exit_code=exit_code,
                duration_s=duration_s,
                timed_out=timed_out,
            )
            failed_nodes = [nodeid for nodeid, status in result.nodes if status in ("failed", "error")]
            if exit_code != 0 and failed_nodes:
                remaining = deadline - time.monotonic()
                if remaining < 30:
                    self.logger.warning(
                        "baseline classification skipped with %.1fs remaining for %s", remaining, result.suite
                    )
                    verdicts = tuple(
                        baseline.BaselineVerdict(nodeid, "unknown", "less than 30 seconds remained")
                        for nodeid in failed_nodes
                    )
                else:
                    try:
                        verdicts = await asyncio.wait_for(
                            asyncio.to_thread(
                                baseline.classify_failures,
                                worktree=worktree,
                                base_ref=base_ref,
                                failed_nodeids=failed_nodes,
                                timeout_s=max(1, int(remaining)),
                            ),
                            timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        self.logger.warning(
                            "baseline classification exceeded the remaining deadline for %s", result.suite
                        )
                        verdicts = tuple(
                            baseline.BaselineVerdict(nodeid, "unknown", "baseline classification timed out")
                            for nodeid in failed_nodes
                        )
                result = replace(result, baseline=tuple((item.nodeid, item.status) for item in verdicts))
            for task_id in task_ids:
                await asyncio.to_thread(
                    test_report.append_suite,
                    feature_id,
                    task_id,
                    result,
                    head_sha=head_sha,
                    base_ref=base_ref,
                    tier=tier,
                    source="coder_run_validation",
                )
            return result
        except Exception:  # noqa: BLE001 — recording must never fail a validation
            self.logger.warning("could not record test results for %s", invocation.distribution, exc_info=True)
            return None

    async def _record_green_cache(
        self,
        *,
        worktree: Path,
        namespace: str,
        plan: "ScopePlan",
        invocation: "Invocation",
        result: Optional[test_report.SuiteResult],
    ) -> None:
        """Record one invocation's node evidence without letting cache I/O affect the gate."""
        if result is None:
            return
        baseline_reds = [nodeid for nodeid, status in result.baseline if status == "baseline_red"]
        invocation_plan = replace(plan, invocations=(invocation,))
        await asyncio.to_thread(
            green_cache.record_green,
            worktree,
            namespace=namespace,
            plan=invocation_plan,
            nodes=result.nodes,
            unmapped=result.unmapped,
            baseline_reds=baseline_reds,
        )

    @staticmethod
    def _only_baseline_reds(result: Optional[test_report.SuiteResult]) -> bool:
        """True only when every observed failure was classified baseline-red."""
        if result is None or result.unmapped:
            return False
        failed_nodes = {nodeid for nodeid, status in result.nodes if status in ("failed", "error")}
        verdicts = dict(result.baseline)
        return (
            bool(failed_nodes)
            and set(verdicts) == failed_nodes
            and all(verdicts[nodeid] == "baseline_red" for nodeid in failed_nodes)
        )

    async def _await_one(
        self, *, process: "asyncio.subprocess.Process", log_path: Path, deadline: float
    ) -> Tuple[Literal["completed", "failed", "timed_out"], int]:
        """Drain one process to completion or its own deadline slice, then reap it.

        Terminal truth is always this `process.wait()` receipt (spec R8): a
        negative `returncode` (killed by a signal) is preserved as-is, never
        converted into success, and an isolated `124` from the CHILD is
        preserved as a plain `failed` exit code -- only a deadline THIS
        method itself imposes yields `outcome="timed_out"`.
        """
        drain_task = asyncio.ensure_future(self._drain(process, log_path))
        remaining = max(0.0, deadline - time.monotonic())
        try:
            await asyncio.wait_for(process.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            await self._terminate_owned_tree(process)
            await process.wait()  # never assume termination -- reap the real receipt.
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task
            return "timed_out", process.returncode if process.returncode is not None else 124
        await drain_task
        returncode = process.returncode if process.returncode is not None else -1
        if returncode == 0:
            return "completed", 0
        return "failed", returncode

    async def _drain(self, process: "asyncio.subprocess.Process", log_path: Path) -> None:
        """Copy the child's merged stdout/stderr into *log_path*, capped at a bounded size.

        Always keeps reading the pipe to EOF -- even once the cap is reached
        -- so a "log grande" child is never stalled waiting on a full pipe
        buffer; only the on-disk file's growth is bounded.
        """
        assert process.stdout is not None
        written = await asyncio.to_thread(lambda: log_path.stat().st_size if log_path.exists() else 0)
        while True:
            chunk = await process.stdout.read(_DRAIN_CHUNK_BYTES)
            if not chunk:
                break
            if written >= _MAX_SUPERVISED_LOG_BYTES:
                continue
            allowed = chunk[: max(0, _MAX_SUPERVISED_LOG_BYTES - written)]
            if allowed:
                await asyncio.to_thread(self._append_log_bytes, log_path, allowed)
                written += len(allowed)

    async def _terminate_owned_tree(self, process: "asyncio.subprocess.Process") -> None:
        """Terminate the process's OWN process group (itself, plus any child it spawned).

        `start_new_session=True` at spawn time made this process its own
        session/group leader, so its pid IS its pgid -- no `getpgid` needed,
        and no other unrelated process shares that group.
        """
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_SECONDS)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

    @staticmethod
    def _selection_header(plan: "ScopePlan") -> str:
        """One `# selection …` line + one `# note: …` line per plan note (FEAT-604, OQ3)."""
        lines = [f"# selection tier={plan.tier}\n"]
        lines += [f"# note: {note}\n" for note in plan.notes]
        lines += [f"# cached: {target}\n" for target in plan.cached]
        return "".join(lines)

    @staticmethod
    def _append_log(log_path: Path, text: str) -> None:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(text)

    @staticmethod
    def _append_log_bytes(log_path: Path, data: bytes) -> None:
        with open(log_path, "ab") as handle:
            handle.write(data)
