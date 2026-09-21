"""Portable compaction policy; actual host adapters require M0 evidence.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M5
(R6 "Compactación Jev en la frontera"). Python cannot itself prove a host
is idle between turns or that a driver's `compact()` call reached the real
runtime -- this module only expresses POLICY: at most one compaction
attempt per (`checkpoint_id`, `context_id`) (spec: "No hacer más de un
intento por checkpoint_id+context_id"), an honest observable outcome even
when unsupported/off/failed, and no blind retry of an unresolved
(`in_progress`) attempt after a crash or timeout.

`compaction_status` (`packages/ai-parrot/src/parrot/knowledge/wiki/
claude_code/compaction.py:317`) reports whether the `fast-jev-compaction`
plugin/API key/function-hooks flag are *installed* -- spec R6 is explicit
that this is "diagnóstico de instalación, no handshake de capacidades", so
it is never consulted here to decide `driver.supports()`. A driver capable
enough to answer that question honestly is exactly the API contract M0
must homologate first (spec Q1) -- this module never invents one.

Concrete host adapters (the actual `PhaseBoundaryDriver` implementation
that talks to a real Claude Code session) are out of this task's scope by
design ("No implementar adaptador Claude ni instalar plugin"): only the
Protocol and the portable coordination policy around it live here. A real
producer of `ReviewCheckpoint.context_id` (the addressable context to
compact) is itself gated on the same M0 spike, so `prepare_review_boundary`
refuses to guess one -- see its `ValueError` below.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Iterator, Literal, Optional, Protocol

from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.sdd_coder.optimization_models import CompactionReceipt, ReviewCheckpoint

try:  # POSIX only -- degrades to a no-op lock on platforms without fcntl.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class PhaseBoundaryError(RuntimeError):
    """Base class for every domain error this module raises."""

    error_code = "operation_error"


class PhaseBoundaryStaleHandoffError(PhaseBoundaryError):
    """Driver answered for a different checkpoint/context than requested.

    Spec R5/R6: an outcome scoped to the wrong identity must never be
    accepted as this attempt's continuation -- reviewing over the wrong
    context/evidence is exactly what a "stale handoff" would cause, so
    this blocks continuation instead of trusting the driver's own claim.
    """

    error_code = "phase_boundary_stale_handoff"


class PhaseBoundaryDriver(Protocol):
    """Verified target context, safe between-turn boundary and observable receipt."""

    async def supports(self, context_id: str) -> bool:
        """Return false when context, host or version is not homologated."""
        ...

    async def compact(self, checkpoint: ReviewCheckpoint) -> CompactionReceipt:
        """Request one compaction in the checkpoint's actual context."""
        ...


def _idempotency_key(checkpoint_id: str, context_id: str) -> str:
    """Sha256 hex digest binding one compaction attempt to its checkpoint+context.

    Spec R6: "No hacer más de un intento por checkpoint_id+context_id."
    Hashing (rather than concatenating the raw strings into a path) keeps
    the derived filename confined and filesystem-safe regardless of what
    characters a future host-supplied `context_id` may contain.
    """
    return hashlib.sha256(f"{checkpoint_id}:{context_id}".encode("utf-8")).hexdigest()


def _compaction_dir(root: Path, execution_id: str) -> Path:
    """`executions/<execution_id>/compaction/` under the durable root."""
    return root / "executions" / execution_id / "compaction"


def _receipt_path(root: Path, execution_id: str, idempotency_key: str) -> Path:
    return _compaction_dir(root, execution_id) / f"{idempotency_key}.json"


def _lock_path(root: Path, execution_id: str, idempotency_key: str) -> Path:
    return _compaction_dir(root, execution_id) / f".{idempotency_key}.lock"


@contextlib.contextmanager
def _interprocess_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive, blocking lock on *lock_path* across processes.

    Local copy of the same pattern `evidence.py`/`checkpoint.py` use for
    their own per-resource locks (private helper, duplicated per the
    established convention in this task family rather than imported --
    it is not part of either module's public API). Degrades to a no-op on
    platforms without `fcntl`: no protection there, but no false blocking
    either.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write *payload* as canonical JSON via temp-file-then-`os.replace` (mirrors `checkpoint.py`)."""
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


def _load_receipt_sync(path: Path) -> Optional[CompactionReceipt]:
    """Return the durably recorded receipt for one idempotency key, or None if never attempted."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CompactionReceipt.model_validate(data)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise PhaseBoundaryError(f"durable compaction record at {path} is corrupted: {exc}") from exc


def _check_or_place_intent_sync(
    receipt_path: Path, lock_path: Path, *, checkpoint_id: str, context_id: str
) -> Optional[CompactionReceipt]:
    """Under the per-key lock: return the existing receipt, or place an `in_progress` intent.

    Returning an existing record here -- whether terminal or still
    `in_progress` -- is the ONLY way this module ever answers a
    concurrent/replayed request: it never calls the driver a second time
    for the same `checkpoint_id`+`context_id` (spec R6). A `None` return
    means *this* call is the exclusive owner of a brand-new attempt, and
    the `in_progress` placeholder is already durably persisted before
    control returns to the caller -- so a crash right after this point
    leaves that placeholder for the NEXT call to observe and refuse to
    retry (spec M5: "in_progress tras crash exige reconciliación; no retry
    automático de una operación de estado desconocido").
    """
    with _interprocess_lock(lock_path):
        existing = _load_receipt_sync(receipt_path)
        if existing is not None:
            return existing
        placeholder = CompactionReceipt(
            checkpoint_id=checkpoint_id,
            context_id=context_id,
            status="in_progress",
            reason="compaction requested; awaiting driver outcome",
            backend="unknown",
            elapsed_ms=0,
        )
        _atomic_write_json(receipt_path, placeholder.model_dump(mode="json"))
        return None


def _persist_receipt_sync(receipt_path: Path, lock_path: Path, receipt: CompactionReceipt) -> None:
    """Overwrite the durable per-key record with its final (or still `in_progress`) outcome."""
    with _interprocess_lock(lock_path):
        _atomic_write_json(receipt_path, receipt.model_dump(mode="json"))


async def prepare_review_boundary(
    checkpoint: ReviewCheckpoint,
    *,
    driver: PhaseBoundaryDriver,
    policy: Literal["auto", "off"],
    store: ExecutionEvidenceStore,
) -> CompactionReceipt:
    """Persist intent, enforce one request and return an honest continuation receipt.

    Sequence (spec R6): persist intent under the durable
    `checkpoint_id`+`context_id` key BEFORE calling the driver (so a
    concurrent/replayed call never triggers a second request) -> policy
    `off` short-circuits to `skipped` -> `driver.supports()` false short-
    circuits to `unsupported` -> `driver.compact()` runs exactly once ->
    the returned receipt is revalidated against the requested
    checkpoint/context identity (a mismatch is a stale handoff, rejected
    rather than trusted) -> the final outcome is persisted and returned.

    Args:
        checkpoint: The neutral continuation identity/evidence to compact
            around. `checkpoint.context_id` must already be set by the
            caller to the addressable host context -- this function never
            invents one.
        driver: The host-specific capability under test; this module never
            assumes it can reach a real runtime on its own.
        policy: `'auto'` requests a compaction when the driver reports
            support; `'off'` always records `skipped` without ever calling
            the driver.
        store: Durable evidence store; only its `root` is used to locate
            this execution's `compaction/` directory, the same convention
            `checkpoint.py` uses for its own keyed `review/` manifests
            (rather than the content-addressed `put_artifact`, which
            cannot be looked up by idempotency key before its content is
            known).

    Returns:
        The durable `CompactionReceipt` for this `checkpoint_id`+
        `context_id` -- `completed`/`skipped`/`unsupported`/`failed`, or a
        still-unresolved `in_progress` record inherited from a prior
        crash/timeout that this call refused to retry.

    Raises:
        ValueError: *policy* is neither `'auto'` nor `'off'`, or
            *checkpoint* carries no `context_id` to address.
        PhaseBoundaryError: the durable per-key record is corrupted.
        PhaseBoundaryStaleHandoffError: the driver answered for a
            different checkpoint/context than requested.
        Exception: whatever `driver.compact()` itself raises propagates
            unchanged -- a crash/timeout leaves the durable record
            `in_progress` for the NEXT call to reconcile, never a blind
            retry (spec M5).
    """
    if policy not in ("auto", "off"):
        raise ValueError(f"policy must be 'auto' or 'off', got {policy!r}")
    context_id = checkpoint.context_id
    if not context_id:
        raise ValueError(
            "checkpoint.context_id must be set to coordinate a phase boundary; host-specific "
            "context addressing is gated on M0 (spec Q1) and is never fabricated here"
        )

    idempotency_key = _idempotency_key(checkpoint.checkpoint_id, context_id)
    receipt_path = _receipt_path(store.root, checkpoint.execution_id, idempotency_key)
    lock_path = _lock_path(store.root, checkpoint.execution_id, idempotency_key)

    existing = await asyncio.to_thread(
        _check_or_place_intent_sync,
        receipt_path,
        lock_path,
        checkpoint_id=checkpoint.checkpoint_id,
        context_id=context_id,
    )
    if existing is not None:
        # Replayed/concurrent request, or a prior crash/timeout left this
        # `in_progress`: honor whatever is durably recorded, never retry.
        return existing

    start = time.monotonic()

    if policy == "off":
        receipt = CompactionReceipt(
            checkpoint_id=checkpoint.checkpoint_id,
            context_id=context_id,
            status="skipped",
            reason="pre_review_compaction policy is 'off'",
            backend="unknown",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        await asyncio.to_thread(_persist_receipt_sync, receipt_path, lock_path, receipt)
        return receipt

    supported = await driver.supports(context_id)
    if not supported:
        receipt = CompactionReceipt(
            checkpoint_id=checkpoint.checkpoint_id,
            context_id=context_id,
            status="unsupported",
            reason=f"driver does not support context {context_id!r} (host/scope not homologated)",
            backend="unknown",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        await asyncio.to_thread(_persist_receipt_sync, receipt_path, lock_path, receipt)
        return receipt

    # Never caught here: an exception from the driver is a crash/timeout.
    # The durable record stays `in_progress` (already written above) for
    # a later call to reconcile -- never a blind retry (spec M5).
    driver_receipt = await driver.compact(checkpoint)

    if driver_receipt.checkpoint_id != checkpoint.checkpoint_id or driver_receipt.context_id != context_id:
        stale = CompactionReceipt(
            checkpoint_id=checkpoint.checkpoint_id,
            context_id=context_id,
            status="failed",
            reason=(
                f"driver returned a receipt for checkpoint_id={driver_receipt.checkpoint_id!r} "
                f"context_id={driver_receipt.context_id!r}, not the requested "
                f"{checkpoint.checkpoint_id!r}/{context_id!r} (stale handoff)"
            ),
            backend="unknown",
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        await asyncio.to_thread(_persist_receipt_sync, receipt_path, lock_path, stale)
        raise PhaseBoundaryStaleHandoffError(stale.reason)

    await asyncio.to_thread(_persist_receipt_sync, receipt_path, lock_path, driver_receipt)
    return driver_receipt
