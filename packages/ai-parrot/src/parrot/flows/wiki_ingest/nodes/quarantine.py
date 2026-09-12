"""Failure quarantine, rollback & bounded reprocess (FEAT-481, spec Module 17).

When the LLM cannot compile a meeting into valid structured output (``InvokeError``,
unparseable/degenerate output, or any exception in the per-meeting pipeline), the
orchestrator (Module 6) rolls back every compiled page (via ``runner._rollback``) and
calls into this module to:

1. **Quarantine** the raw bundle to ``Raw/Failed/<source-id>/`` (never ``Raw/Processed/``,
   so the fetch-gate's raw-id scan does not treat it as done) with a ``failure.json``
   sidecar tracking ``attempts`` and the last error. The raw bytes are preserved
   (transcript hash verified across the move; on a retry-before-promote failure the bytes
   are re-materialised from the in-memory :class:`GatedMeeting`).
2. On subsequent ingests, **auto-retry** each quarantined bundle up to
   :data:`conf.WIKI_KB_MAX_REPROCESS_ATTEMPTS` (no re-download — the bytes are local),
   after which it is parked as ``reprocess-exhausted`` for a human.

All functions here are synchronous file I/O — the orchestrator dispatches them via
``asyncio.to_thread`` so they never stall the event loop.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .. import conf
from .fetch_gate import GatedMeeting

logger = logging.getLogger(__name__)

#: Sub-directory of ``Raw/`` holding quarantined bundles (parallel to
#: ``Processed``/``Incoming``/``Duplicates``/``Uncategorized``).
FAILED_DIRNAME = "Failed"


class FailureRecord(BaseModel):
    """``Raw/Failed/<source-id>/failure.json`` — quarantine metadata."""

    source_id: str
    fireflies_id: str
    attempts: int = 0
    last_error: str = ""
    first_failed_at: str = ""
    last_failed_at: str = ""
    models: dict[str, str] = Field(default_factory=dict)
    title: str = ""
    meeting_date: str = ""
    meeting_date_iso: str | None = None
    participants: list[str] = Field(default_factory=list)
    duration_minutes: float = 0.0


def _failed_root(vault_path: str | Path) -> Path:
    return Path(vault_path) / conf.WIKI_KB_RAW_ROOT / FAILED_DIRNAME


def _processed_root(vault_path: str | Path) -> Path:
    return Path(vault_path) / conf.WIKI_KB_RAW_ROOT / "Processed"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_processed_bundle_dir(vault_path: str | Path, fireflies_id: str) -> Path | None:
    """Return the ``Raw/Processed/**/<fireflies_id>/`` bundle dir, if present."""
    root = _processed_root(vault_path)
    if not root.is_dir():
        return None
    for transcript in root.rglob("transcript.*"):
        if transcript.parent.name == fireflies_id:
            return transcript.parent
    return None


def _read_record(failed_dir: Path) -> FailureRecord | None:
    sidecar = failed_dir / "failure.json"
    if not sidecar.is_file():
        return None
    try:
        return FailureRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt sidecar must not crash ingest
        logger.warning("Corrupt failure.json in %s; treating as attempts=0", failed_dir)
        return None


def _write_record(failed_dir: Path, record: FailureRecord) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    (failed_dir / "failure.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")


def quarantine(
    vault_path: str | Path,
    meeting: GatedMeeting,
    *,
    error: str,
    models: dict[str, str],
    prior_attempts: int = 0,
) -> int:
    """Move the meeting's raw bundle into ``Raw/Failed/<id>/`` + write ``failure.json``.

    Prefers moving an existing ``Raw/Processed/`` bundle (first-failure path, or a
    retry that reached the promote step). If none is found (e.g. a retry that failed
    before promotion), the bytes are re-materialised from the in-memory
    ``GatedMeeting`` so nothing is ever lost.

    Args:
        vault_path: Obsidian vault root.
        meeting: The gated meeting whose compile failed.
        error: The failure message (truncated in the record).
        models: ``{"strong": ..., "cheap": ...}`` config strings, for the record.
        prior_attempts: The attempt count *before* this failure (0 on first failure,
            the quarantined record's prior count on a retry). ``attempts`` becomes
            ``prior_attempts + 1``.

    Returns:
        The new ``attempts`` count (``>= 1``).
    """
    fid = meeting.fireflies_id
    failed_dir = _failed_root(vault_path) / fid
    src = _find_processed_bundle_dir(vault_path, fid)
    pre_hash = _sha256(src / "transcript.md") if src else None

    if src is not None and src.resolve() != failed_dir.resolve():
        failed_dir.parent.mkdir(parents=True, exist_ok=True)
        if failed_dir.exists():
            shutil.rmtree(failed_dir)
        shutil.move(str(src), str(failed_dir))
        post_hash = _sha256(failed_dir / "transcript.md")
        if pre_hash is not None and post_hash is not None and pre_hash != post_hash:
            raise RuntimeError(f"quarantine hash mismatch for {fid}: raw bytes changed during move")
    else:
        # No processed bundle to move — re-materialise from the in-memory meeting.
        failed_dir.mkdir(parents=True, exist_ok=True)
        if meeting.transcript_text is not None and not (failed_dir / "transcript.md").exists():
            (failed_dir / "transcript.md").write_text(meeting.transcript_text, encoding="utf-8")
        if meeting.summary_text is not None and not (failed_dir / "summary.md").exists():
            (failed_dir / "summary.md").write_text(meeting.summary_text, encoding="utf-8")

    existing = _read_record(failed_dir)
    first_failed = existing.first_failed_at if (existing and existing.first_failed_at) else _now()
    attempts = prior_attempts + 1
    record = FailureRecord(
        source_id=meeting.source_id,
        fireflies_id=fid,
        attempts=attempts,
        last_error=error[:1000],
        first_failed_at=first_failed,
        last_failed_at=_now(),
        models=models,
        title=meeting.title,
        meeting_date=meeting.meeting_date,
        meeting_date_iso=meeting.meeting_date_iso,
        participants=list(meeting.participants),
        duration_minutes=meeting.duration_minutes,
    )
    _write_record(failed_dir, record)
    logger.warning("Quarantined %s to Raw/Failed/%s/ (attempt %d): %s", meeting.source_id, fid, attempts, error[:120])
    return attempts


def failed_ids(vault_path: str | Path) -> set[str]:
    """Return the set of ``fireflies_id`` currently quarantined in ``Raw/Failed/``.

    Used by the fetch-gate so a quarantined id is not re-downloaded (it is retried
    from the local bytes instead).
    """
    root = _failed_root(vault_path)
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir() if d.is_dir() and (d / "failure.json").is_file()}


def build_retry_batch(vault_path: str | Path, *, cap: int) -> list[tuple[GatedMeeting, int]]:
    """Return ``(GatedMeeting, prior_attempts)`` for each retry-eligible quarantine.

    Eligible = a ``Raw/Failed/<id>/`` with ``attempts < cap``. The meeting is rebuilt
    from the local bytes (``outcome="fetch"``) so the normal compile path runs without
    a Fireflies re-download. Exhausted bundles (``attempts >= cap``) are skipped.
    """
    root = _failed_root(vault_path)
    out: list[tuple[GatedMeeting, int]] = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        record = _read_record(d)
        if record is None or record.attempts >= cap:
            continue
        transcript = d / "transcript.md"
        summary = d / "summary.md"
        meeting = GatedMeeting(
            fireflies_id=record.fireflies_id,
            source_id=record.source_id,
            title=record.title or "Untitled Meeting",
            meeting_date=record.meeting_date or "1970-01-01",
            meeting_date_iso=record.meeting_date_iso,
            participants=record.participants,
            duration_minutes=record.duration_minutes,
            outcome="fetch",
            transcript_text=transcript.read_text(encoding="utf-8") if transcript.is_file() else None,
            summary_text=summary.read_text(encoding="utf-8") if summary.is_file() else None,
        )
        out.append((meeting, record.attempts))
    return out


def discard_failed_dir(vault_path: str | Path, fireflies_id: str) -> None:
    """Remove ``Raw/Failed/<id>/`` (retry re-materialises the bundle from memory)."""
    d = _failed_root(vault_path) / fireflies_id
    if d.is_dir():
        shutil.rmtree(d)
