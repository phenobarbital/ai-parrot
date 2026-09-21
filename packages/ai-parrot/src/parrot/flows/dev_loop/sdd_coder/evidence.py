"""Durable execution evidence with atomic publication and confined reads.

Spec `sdd/specs/sdd-execution-optimization.spec.md` (FEAT-584), module M2
(evidence/events, R3). Evidence is persisted OUTSIDE any worktree, under a
root already validated by `telemetry.resolve_durable_root` (this module
only reuses an already-resolved `root`; it never resolves one itself), so
the record survives `git worktree remove` (spec AC7).

Two artifact kinds live under one execution's directory:

- ``executions/<execution_id>/events.jsonl`` — append-only, one canonical
  JSON line per `WorkflowEvent`, deduplicated by `event_id`. A crash mid
  write leaves at most one incomplete trailing line, which the next append
  repairs away before writing; corruption anywhere else in the file blocks
  reliable reading instead of being silently skipped.
- ``executions/<execution_id>/artifacts/<sha256>.json`` — content-addressed
  snapshots published via `put_artifact`, immutable once written and
  published only via a temp-file-then-`os.replace` swap so a reader never
  observes a partial file.

Writers are serialized both within one process (an `asyncio.Lock` per
execution) and across processes (a blocking `fcntl.flock` on a sibling lock
file), because multiple sdd-coder attempts/executions can run concurrently
against the same durable root (spec R3: "concurrencia de executions").
`read_artifact` only ever resolves paths that are structurally confined to
one execution's `artifacts/` directory (a validated sha256-hex filename,
never a symlink), so `artifact_id`/`execution_id` are never caller-
controlled filesystem paths (spec AC4).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterator, List

from pydantic import BaseModel

from parrot.flows.dev_loop.sdd_coder.optimization_models import EvidenceRef, WorkflowEvent

try:  # POSIX only — degrades to a no-op lock on platforms without fcntl.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

#: Upper bound accepted by `read_artifact` (spec AC4: "bytes<=16KiB").
MAX_READ_LIMIT: int = 16384

_EXECUTION_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ARTIFACT_ID_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceConflictError(ValueError):
    """Raised when an `event_id` is re-appended with different content."""


class EvidenceCorruptionError(RuntimeError):
    """Raised when the durable store contains unreadable interior data.

    Never raised for a truncated trailing line — that is a crash tail and
    is repaired transparently. Raised for anything else: invalid JSON or
    invalid UTF-8 anywhere but the last line, or a `<sha>.json` artifact
    whose filename hash does not match its own content.
    """


def _canonical_json(model: BaseModel) -> str:
    """Serialize a model as sorted-key, whitespace-free, UTF-8-safe JSON."""
    data = model.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _atomic_append_line(path: Path, line_bytes: bytes) -> None:
    """Append one already newline-terminated line to *path* and fsync it.

    A single `os.write` to an `O_APPEND` fd; POSIX makes this atomic against
    other appenders on a regular file. Isolated in its own function so tests
    can force a durable-write failure without patching `os.write` globally.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line_bytes)
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_publish_new_file(final_path: Path, encoded: bytes) -> None:
    """Write *encoded* to a temp file, fsync it, then atomically rename it in.

    A reader can only ever see `final_path` fully absent or fully present —
    never a partial write — because `os.replace` is atomic on the same
    filesystem (spec: "nunca exponer refs antes de persistir").
    """
    tmp_path = final_path.with_name(f".{final_path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(tmp_path, final_path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


def _fsync_dir(directory: Path) -> None:
    """Best-effort `fsync` of a directory so a rename/create survives a crash."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - directory must exist by this point
        return
    try:
        os.fsync(dir_fd)
    except OSError:  # pragma: no cover - not every filesystem supports this
        pass
    finally:
        os.close(dir_fd)


@contextlib.contextmanager
def _interprocess_lock(lock_path: Path) -> Iterator[None]:
    """Hold an exclusive, blocking lock on *lock_path* across processes.

    Degrades to a no-op on platforms without `fcntl` (matches the existing
    `knowledge/wiki/project.py` convention): no protection there, but no
    false blocking either.
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


class ExecutionEvidenceStore:
    """Store immutable evidence outside worktrees, keyed by execution UUID."""

    def __init__(self, root: Path) -> None:
        self.logger = logging.getLogger(__name__)
        self.root = Path(root)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def append_event(self, event: WorkflowEvent) -> EvidenceRef:
        """Append once per event_id; reject conflicting content and corruption."""
        execution_dir = self._confined_execution_dir(event.execution_id)
        lock = await self._lock_for(event.execution_id)
        async with lock:
            return await asyncio.to_thread(self._append_event_sync, execution_dir, event)

    async def put_artifact(self, execution_id: str, payload: BaseModel) -> EvidenceRef:
        """Publish canonical JSON and its hash only after durable persistence."""
        execution_dir = self._confined_execution_dir(execution_id)
        lock = await self._lock_for(execution_id)
        async with lock:
            return await asyncio.to_thread(self._put_artifact_sync, execution_dir, payload)

    async def read_artifact(
        self, execution_id: str, artifact_id: str, offset: int = 0, limit: int = 8192
    ) -> dict[str, object]:
        """Return a bounded UTF-8 page with stable cursor and full snapshot hash."""
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError(f"offset must be a non-negative int, got {offset!r}")
        if not isinstance(limit, int) or isinstance(limit, bool) or not (0 < limit <= MAX_READ_LIMIT):
            raise ValueError(f"limit must be an int in 1..{MAX_READ_LIMIT}, got {limit!r}")

        execution_dir = self._confined_execution_dir(execution_id)
        artifact_path = self._confined_artifact_path(execution_dir, artifact_id)
        return await asyncio.to_thread(self._read_artifact_sync, artifact_path, offset, limit)

    # -- confined path resolution -----------------------------------------

    def _confined_execution_dir(self, execution_id: str) -> Path:
        """Resolve `executions/<execution_id>` and refuse any escape from `root`."""
        if not _EXECUTION_ID_RE.match(execution_id or ""):
            raise ValueError(f"execution_id must be a canonical UUID, got {execution_id!r}")
        candidate = self.root / "executions" / execution_id
        if candidate.exists() and candidate.is_symlink():
            raise ValueError(f"execution directory must not be a symlink: {candidate}")
        resolved_root = self.root.resolve()
        resolved_candidate = candidate.resolve()
        if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
            raise ValueError(f"execution_id resolves outside the evidence root: {execution_id!r}")
        return candidate

    def _confined_artifact_path(self, execution_dir: Path, artifact_id: str) -> Path:
        """Resolve `artifacts/<artifact_id>.json` and refuse a symlink or an escape."""
        if not _ARTIFACT_ID_RE.match(artifact_id or ""):
            raise ValueError(f"artifact_id must be a sha256 hex digest, got {artifact_id!r}")
        artifacts_dir = execution_dir / "artifacts"
        candidate = artifacts_dir / f"{artifact_id}.json"
        if candidate.exists() and candidate.is_symlink():
            raise ValueError(f"artifact path must not be a symlink: {candidate}")
        resolved_dir = artifacts_dir.resolve()
        resolved_candidate = candidate.resolve()
        if resolved_candidate.parent != resolved_dir:
            raise ValueError(f"artifact_id resolves outside its execution scope: {artifact_id!r}")
        return candidate

    # -- per-execution locking ---------------------------------------------

    async def _lock_for(self, execution_id: str) -> asyncio.Lock:
        """Return the (lazily created) in-process lock serializing one execution."""
        async with self._locks_guard:
            lock = self._locks.get(execution_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[execution_id] = lock
            return lock

    # -- blocking implementations, run off the event loop -------------------

    def _append_event_sync(self, execution_dir: Path, event: WorkflowEvent) -> EvidenceRef:
        execution_dir.mkdir(parents=True, exist_ok=True)
        events_path = execution_dir / "events.jsonl"
        canonical = _canonical_json(event)
        encoded_line = canonical.encode("utf-8")
        event_sha256 = hashlib.sha256(encoded_line).hexdigest()

        with _interprocess_lock(execution_dir / ".events.lock"):
            existing_lines = self._read_and_repair_tail(events_path)
            for raw_line in existing_lines:
                try:
                    record = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise EvidenceCorruptionError(
                        f"interior corruption in {events_path}: unreadable line: {exc}"
                    ) from exc
                if not isinstance(record, dict) or record.get("event_id") != event.event_id:
                    continue
                if raw_line != canonical:
                    raise EvidenceConflictError(f"event_id {event.event_id!r} already recorded with different content")
                # Idempotent replay: already durably persisted, do not re-append.
                return EvidenceRef(
                    artifact_id=event.event_id,
                    sha256=hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
                    relative_path=str(events_path.relative_to(self.root)),
                    size_bytes=len(raw_line.encode("utf-8")),
                    media_type="application/x-ndjson",
                )

            _atomic_append_line(events_path, encoded_line + b"\n")
            _fsync_dir(execution_dir)

        return EvidenceRef(
            artifact_id=event.event_id,
            sha256=event_sha256,
            relative_path=str(events_path.relative_to(self.root)),
            size_bytes=len(encoded_line),
            media_type="application/x-ndjson",
        )

    def _read_and_repair_tail(self, events_path: Path) -> List[str]:
        """Return every complete line, repairing an incomplete crash tail.

        Must be called while holding the execution's interprocess lock. Only
        the LAST line is ever treated as a possible crash tail (an append
        that never completed); any other unreadable line is interior
        corruption and is reported by the caller instead of dropped.
        """
        if not events_path.exists():
            return []
        raw = events_path.read_bytes()
        if not raw:
            return []

        if not raw.endswith(b"\n"):
            # The file does not end on a line boundary: the last append never
            # durably completed. Repair by truncating that partial tail away —
            # it was never exposed as a published EvidenceRef.
            last_newline = raw.rfind(b"\n")
            good = raw[: last_newline + 1] if last_newline >= 0 else b""
            dropped = raw[len(good) :]
            self.logger.warning(
                "Repairing incomplete crash tail in %s (%d bytes dropped)",
                events_path,
                len(dropped),
            )
            _atomic_publish_new_file(events_path, good)
            raw = good

        lines: List[str] = []
        for raw_line in raw.split(b"\n"):
            if not raw_line:
                continue
            try:
                lines.append(raw_line.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise EvidenceCorruptionError(f"interior corruption in {events_path}: invalid UTF-8: {exc}") from exc
        return lines

    def _put_artifact_sync(self, execution_dir: Path, payload: BaseModel) -> EvidenceRef:
        canonical = _canonical_json(payload)
        encoded = canonical.encode("utf-8")
        sha256 = hashlib.sha256(encoded).hexdigest()
        artifacts_dir = execution_dir / "artifacts"
        final_path = artifacts_dir / f"{sha256}.json"

        with _interprocess_lock(execution_dir / ".artifacts.lock"):
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                if final_path.is_symlink():
                    raise EvidenceCorruptionError(f"artifact path is a symlink, refusing to trust it: {final_path}")
                existing = final_path.read_bytes()
                if existing != encoded:
                    raise EvidenceCorruptionError(
                        f"artifact {sha256} exists with mismatched content (hash collision or corruption)"
                    )
                size_bytes = len(existing)
            else:
                _atomic_publish_new_file(final_path, encoded)
                _fsync_dir(artifacts_dir)
                size_bytes = len(encoded)

        return EvidenceRef(
            artifact_id=sha256,
            sha256=sha256,
            relative_path=str(final_path.relative_to(self.root)),
            size_bytes=size_bytes,
            media_type="application/json",
        )

    def _read_artifact_sync(self, artifact_path: Path, offset: int, limit: int) -> dict[str, object]:
        if not artifact_path.exists():
            raise FileNotFoundError(f"no evidence emitted for this artifact: {artifact_path}")

        data = artifact_path.read_bytes()
        total_size = len(data)
        sha256 = hashlib.sha256(data).hexdigest()
        if offset > total_size:
            raise ValueError(f"offset {offset} is beyond the artifact size {total_size}")

        end = min(offset + limit, total_size)
        # Never split a multi-byte UTF-8 codepoint across a page boundary: a
        # continuation byte (0b10xxxxxx) at `end` means the character that
        # started before it is incomplete, so back off until it is not.
        while end > offset and end < total_size and (data[end] & 0xC0) == 0x80:
            end -= 1

        content = data[offset:end].decode("utf-8")
        eof = end >= total_size
        return {
            "content": content,
            "offset": offset,
            "next_offset": None if eof else end,
            "eof": eof,
            "size_bytes": total_size,
            "sha256": sha256,
        }
