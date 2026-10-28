"""Durable ledger outbox: sealed batches of journal events awaiting delivery."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps, compute_event_id
from parrot.knowledge.wiki.ledger.shared_log import is_shareable

logger = logging.getLogger(__name__)

OUTBOX_DIRNAME = "outbox"


class LedgerBatch(BaseModel):
    """Manifest of one sealed batch (spec §2 Data Models)."""

    schema_version: Literal[1] = 1
    batch_id: str
    source_ref: str
    source_head: str
    source_end_offset: int
    source_sha256: str
    events_sha256: str
    event_ids: list[str]
    remote: str = "origin"
    branch: str = "dev"
    prepared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LedgerDeliveryConflict(BaseModel):
    """One event that cannot be delivered without review."""

    event_id: str
    subject: str
    reason: str


class LedgerDeliveryReport(BaseModel):
    """Typed outcome of one delivery attempt sequence (spec §2)."""

    status: Literal["delivered", "already_delivered", "pending", "conflict", "unsupported"]
    batch_id: str
    attempts: int
    remote_head: str | None
    commit_sha: str | None
    added: int
    remaining: int
    conflicts: list[LedgerDeliveryConflict] = Field(default_factory=list)
    error_code: str | None = None
    recovery_path: str | None = None


class LedgerReceipt(BaseModel):
    """Audit record written only after remote content verification."""

    schema_version: Literal[1] = 1
    batch_id: str
    manifest_sha256: str
    remote: str
    branch: str
    remote_head: str
    verified_digest: str
    acknowledged_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StrictLedgerReadError(ValueError):
    """A complete line is malformed, or an event id does not match its content."""


class OutboxLockedError(RuntimeError):
    """Another preparer holds the outbox lock, or the filesystem cannot lock."""


class StrictRead(BaseModel):
    """Result of a strict read: raw lines and events up to the complete-line boundary."""

    raw_lines: list[bytes]
    events: list[LedgerEvent]
    end_offset: int
    truncated_tail: bool

    model_config = {"arbitrary_types_allowed": True}


def verify_event_identity(event: LedgerEvent) -> None:
    """Raise when ``event.event_id`` is not the hash of its own content."""
    expected = compute_event_id(event.kind, event.subject, event.actor, event.ts, event.payload)
    if event.event_id != expected:
        raise StrictLedgerReadError(f"event {event.event_id!r} does not match its content (expected {expected})")


def read_strict_events(path: Path, *, end_offset: int | None = None) -> StrictRead:
    """Strictly parse complete JSONL lines of ``path`` up to ``end_offset``.

    Missing files yield an empty result.  A non-newline-terminated suffix is
    reported but deliberately not parsed.
    """
    if not path.exists():
        return StrictRead(raw_lines=[], events=[], end_offset=0, truncated_tail=False)
    if path.is_symlink():
        raise StrictLedgerReadError(f"{path} is a symlink")

    data = path.read_bytes()
    if end_offset is None:
        boundary = data.rfind(b"\n") + 1
    else:
        if end_offset < 0 or end_offset > len(data):
            raise StrictLedgerReadError(f"{path}: end offset {end_offset} is outside the file")
        boundary = end_offset
    complete = data[:boundary]
    if complete and not complete.endswith(b"\n"):
        raise StrictLedgerReadError(f"{path}: end offset does not end after a complete line")

    raw_lines: list[bytes] = []
    events: list[LedgerEvent] = []
    for line_number, line in enumerate(complete.splitlines(), start=1):
        raw_line = line.rstrip(b"\r")
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
            event = LedgerEvent(**payload)
            verify_event_identity(event)
        except Exception as exc:
            if isinstance(exc, StrictLedgerReadError) and "does not match" in str(exc):
                raise StrictLedgerReadError(f"{path}:{line_number}: {exc}") from exc
            raise StrictLedgerReadError(f"{path}:{line_number}: malformed complete ledger line") from exc
        raw_lines.append(raw_line)
        events.append(event)
    return StrictRead(raw_lines=raw_lines, events=events, end_offset=boundary, truncated_tail=boundary < len(data))


def _fsync_dir(path: Path) -> None:
    """Flush a directory entry so a rename survives a crash."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write ``dest`` via temp file, fsync, replace, and parent-directory fsync."""
    tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise


def _sha256(data: bytes) -> str:
    """Return the SHA-256 digest for bytes stored by the outbox."""
    return hashlib.sha256(data).hexdigest()


def _validate_batch_id(batch_id: str) -> str:
    """Return ``batch_id`` when it is a canonical UUID4 string, else raise ``ValueError``."""
    parsed = uuid.UUID(batch_id)
    if parsed.version != 4 or str(parsed) != batch_id:
        raise ValueError(f"invalid UUID4 batch id: {batch_id!r}")
    return batch_id


def _write_durable(path: Path, data: bytes) -> None:
    """Write one new file and flush its content before directory publication."""
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _remove_temp_batch(path: Path) -> None:
    """Remove only the known files in an unpublished temporary batch directory."""
    for name in ("manifest.json", "events.jsonl"):
        candidate = path / name
        if candidate.exists() or candidate.is_symlink():
            candidate.unlink()
    if path.exists():
        path.rmdir()


class LedgerOutbox:
    """Own durable pending batches beside one resolved local event journal."""

    def __init__(self, ledger_dir: Path, *, branch: str = "dev") -> None:
        """Bind an existing local ledger directory without selecting another checkout.

        Args:
            ledger_dir: Local ledger directory holding ``events.jsonl``.
            branch: Remote branch that sealed batches are destined for (``sdd/config.json``).
        """
        self.ledger_dir = Path(ledger_dir).resolve()
        self.branch = branch
        self.source_path = self.ledger_dir / "events.jsonl"
        self.root = self.ledger_dir / OUTBOX_DIRNAME
        self.pending_dir = self.root / "pending"
        self.receipts_dir = self.root / "receipts"
        self.lock_path = self.root / "prepare.lock"
        self.logger = logging.getLogger(__name__)

    def _ensure_dirs(self) -> None:
        """Create outbox directories and reject symlinked storage roots."""
        for path in (self.root, self.pending_dir, self.receipts_dir):
            if path.is_symlink():
                raise StrictLedgerReadError(f"outbox storage path is a symlink: {path}")
            path.mkdir(parents=True, exist_ok=True)

    def _batch_dir(self, batch_id: str) -> Path:
        """Return a validated non-symlink pending batch location."""
        return self.pending_dir / _validate_batch_id(batch_id)

    def _receipt_path(self, batch_id: str) -> Path:
        """Return a validated receipt path."""
        return self.receipts_dir / f"{_validate_batch_id(batch_id)}.json"

    def _receipt_exists(self, batch_id: str) -> bool:
        """Check whether a receipt exists without following a symlink."""
        receipt = self._receipt_path(batch_id)
        if receipt.is_symlink():
            raise StrictLedgerReadError(f"receipt is a symlink: {receipt}")
        return receipt.exists()

    def _load_pending_sync(self) -> list[LedgerBatch]:
        """Read unacknowledged batches and validate their sealed byte digests."""
        if not self.pending_dir.exists():
            return []
        if self.pending_dir.is_symlink():
            raise StrictLedgerReadError(f"pending directory is a symlink: {self.pending_dir}")
        batches: list[LedgerBatch] = []
        for candidate in self.pending_dir.iterdir():
            if candidate.name.startswith("."):
                continue
            if candidate.is_symlink():
                raise StrictLedgerReadError(f"pending batch is a symlink: {candidate}")
            if not candidate.is_dir():
                raise StrictLedgerReadError(f"pending entry is not a batch directory: {candidate}")
            batch_id = _validate_batch_id(candidate.name)
            manifest_path = candidate / "manifest.json"
            events_path = candidate / "events.jsonl"
            if manifest_path.is_symlink() or events_path.is_symlink():
                raise StrictLedgerReadError(f"batch contains a symlink: {candidate}")
            try:
                manifest = LedgerBatch.model_validate_json(manifest_path.read_bytes())
            except Exception as exc:
                raise StrictLedgerReadError(f"invalid batch manifest: {manifest_path}") from exc
            if manifest.batch_id != batch_id:
                raise StrictLedgerReadError(f"manifest batch id does not match directory: {candidate}")
            if _sha256(events_path.read_bytes()) != manifest.events_sha256:
                raise StrictLedgerReadError(f"sealed batch digest mismatch: {events_path}")
            if not self._receipt_exists(batch_id):
                batches.append(manifest)
        return sorted(batches, key=lambda batch: (batch.prepared_at, batch.batch_id))

    async def prepare(
        self, *, repo_root: Path, source_ref: str, source_head: str, known_ids: set[str] | None = None
    ) -> LedgerBatch | None:
        """Seal complete shareable events absent from the fetched dev baseline; return None if empty."""
        return await asyncio.to_thread(self._prepare_sync, repo_root, source_ref, source_head, known_ids or set())

    def _prepare_sync(
        self, repo_root: Path, source_ref: str, source_head: str, known_ids: set[str]
    ) -> LedgerBatch | None:
        """Synchronously seal a stable complete prefix while holding the preparer lock."""
        if not Path(repo_root).exists():
            raise ValueError(f"repository root does not exist: {repo_root}")
        self._ensure_dirs()
        if self.lock_path.is_symlink():
            raise StrictLedgerReadError(f"prepare lock is a symlink: {self.lock_path}")
        with self.lock_path.open("a+b") as lock_handle:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise OutboxLockedError("ledger outbox preparation is already locked") from exc
            except OSError as exc:
                if exc.errno in (errno.ENOLCK, errno.EOPNOTSUPP, errno.ENOTSUP):
                    raise OutboxLockedError("ledger outbox locking is unsupported") from exc
                raise
            try:
                source = read_strict_events(self.source_path)
                pending_ids = {event_id for batch in self._load_pending_sync() for event_id in batch.event_ids}
                selected = [
                    (raw, event)
                    for raw, event in zip(source.raw_lines, source.events, strict=True)
                    if is_shareable(event) and event.event_id not in known_ids and event.event_id not in pending_ids
                ]
                if not selected:
                    return None

                batch_id = str(uuid.uuid4())
                batch_dir = self._batch_dir(batch_id)
                temp_dir = self.pending_dir / f".tmp-{uuid.uuid4().hex}"
                raw_events = b"".join(raw + b"\n" for raw, _ in selected)
                batch = LedgerBatch(
                    batch_id=batch_id,
                    source_ref=source_ref,
                    source_head=source_head,
                    source_end_offset=source.end_offset,
                    source_sha256=_sha256(self.source_path.read_bytes()[: source.end_offset]),
                    events_sha256=_sha256(raw_events),
                    event_ids=[event.event_id for _, event in selected],
                    branch=self.branch,
                )
                temp_dir.mkdir()
                try:
                    _write_durable(temp_dir / "events.jsonl", raw_events)
                    _write_durable(
                        temp_dir / "manifest.json",
                        canonical_json_dumps(batch.model_dump(mode="json")).encode("utf-8"),
                    )
                    _fsync_dir(temp_dir)
                    os.rename(temp_dir, batch_dir)
                    _fsync_dir(self.pending_dir)
                except Exception:
                    _remove_temp_batch(temp_dir)
                    raise
                self.logger.info("prepared ledger outbox batch %s with %d events", batch_id, len(selected))
                return batch
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    async def pending(self) -> list[LedgerBatch]:
        """Return validated unacknowledged batches in preparation order."""
        return await asyncio.to_thread(self._load_pending_sync)

    async def batch_events(self, batch: LedgerBatch) -> StrictRead:
        """Strictly read a sealed batch's events with its recorded identity and hash checks."""
        return await asyncio.to_thread(self._batch_events_sync, batch)

    def _batch_events_sync(self, batch: LedgerBatch) -> StrictRead:
        """Blocking half of :meth:`batch_events`."""
        batch_dir = self._batch_dir(batch.batch_id)
        if batch_dir.is_symlink():
            raise StrictLedgerReadError(f"pending batch is a symlink: {batch_dir}")
        events_path = batch_dir / "events.jsonl"
        if events_path.is_symlink():
            raise StrictLedgerReadError(f"sealed events file is a symlink: {events_path}")
        data = events_path.read_bytes()
        if _sha256(data) != batch.events_sha256:
            raise StrictLedgerReadError(f"sealed batch digest mismatch: {events_path}")
        events = read_strict_events(events_path)
        if [event.event_id for event in events.events] != batch.event_ids:
            raise StrictLedgerReadError(f"sealed batch event ids mismatch: {events_path}")
        return events

    async def acknowledge(self, batch: LedgerBatch, *, remote_head: str, verified_digest: str) -> None:
        """Persist a receipt only for the exact remotely verified batch."""
        await asyncio.to_thread(self._acknowledge_sync, batch, remote_head, verified_digest)

    def _acknowledge_sync(self, batch: LedgerBatch, remote_head: str, verified_digest: str) -> None:
        """Blocking half of :meth:`acknowledge`."""
        self._ensure_dirs()
        batch_dir = self._batch_dir(batch.batch_id)
        if batch_dir.is_symlink():
            raise StrictLedgerReadError(f"pending batch is a symlink: {batch_dir}")
        manifest_path = batch_dir / "manifest.json"
        if manifest_path.is_symlink():
            raise StrictLedgerReadError(f"batch manifest is a symlink: {manifest_path}")
        manifest_data = manifest_path.read_bytes()
        manifest = LedgerBatch.model_validate_json(manifest_data)
        if manifest != batch:
            raise StrictLedgerReadError(f"acknowledgement batch differs from sealed manifest: {manifest_path}")
        receipt = LedgerReceipt(
            batch_id=batch.batch_id,
            manifest_sha256=_sha256(manifest_data),
            remote=batch.remote,
            branch=batch.branch,
            remote_head=remote_head,
            verified_digest=verified_digest,
        )
        _atomic_write_bytes(
            self._receipt_path(batch.batch_id), canonical_json_dumps(receipt.model_dump(mode="json")).encode("utf-8")
        )

    async def receipt_for(self, batch_id: str) -> LedgerReceipt | None:
        """Return the receipt for ``batch_id`` or ``None``."""
        return await asyncio.to_thread(self._receipt_for_sync, batch_id)

    def _receipt_for_sync(self, batch_id: str) -> LedgerReceipt | None:
        """Blocking half of :meth:`receipt_for`."""
        receipt_path = self._receipt_path(batch_id)
        if receipt_path.is_symlink():
            raise StrictLedgerReadError(f"receipt is a symlink: {receipt_path}")
        if not receipt_path.exists():
            return None
        return LedgerReceipt.model_validate_json(receipt_path.read_bytes())

    async def status(self, known_ids: set[str] | None = None) -> dict[str, int | bool]:
        """Read-only counts for sealed and unsealed events without acquiring the preparation lock."""
        return await asyncio.to_thread(self._status_sync, known_ids or set())

    def _status_sync(self, known_ids: set[str]) -> dict[str, int | bool]:
        """Blocking half of :meth:`status`."""
        pending = self._load_pending_sync()
        pending_ids = {event_id for batch in pending for event_id in batch.event_ids}
        source = read_strict_events(self.source_path)
        unsealed = sum(
            1
            for event in source.events
            if is_shareable(event) and event.event_id not in known_ids and event.event_id not in pending_ids
        )
        return {
            "pending_batches": len(pending),
            "pending_events": sum(len(batch.event_ids) for batch in pending),
            "unsealed_events": unsealed,
            "truncated_tail": source.truncated_tail,
        }
