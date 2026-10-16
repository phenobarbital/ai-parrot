"""Shared ledger event log: append-only export/import between a machine's log and git (FEAT-694)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.coder_suspensions import CODER_SUSPENSION_CATEGORY
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog

logger = logging.getLogger(__name__)

SHARED_LOG_REL_PATH: Path = Path("sdd/ledger/events.jsonl")
ARCHIVE_REL_DIR: Path = Path("sdd/ledger/archive")
ARCHIVE_FILENAME_FMT: str = "events-{yyyy_mm}.jsonl"
MARKER_FILENAME: str = "shared_log.marker"
ROTATION_DAYS_DEFAULT: int = 30
TERMINAL_ISSUE_STATUSES: frozenset[str] = frozenset({"closed", "superseded"})
LOCAL_ONLY_INSIGHT_CATEGORIES: frozenset[str] = frozenset({CODER_SUSPENSION_CATEGORY})


class SharedLogRotateReport(BaseModel):
    """Result of rotating the committed shared event log."""

    current: Path
    moved: int
    kept: int
    archives_touched: list[Path] = Field(default_factory=list)
    cutoff: str


class ClaimConflict(BaseModel):
    """An imported ``issue.claimed`` that lost to a different local claimant."""

    issue_id: str
    local_claimed_by: str
    foreign_claimed_by: str
    foreign_event_id: str


class SharedLogExportReport(BaseModel):
    """Result of appending local events to the committed shared log."""

    dest: Path
    created: bool
    added: int
    skipped_local_only: int
    total_committed: int


class SharedLogImportReport(BaseModel):
    """Result of importing committed shared events into a local log."""

    files: list[Path]
    fast_path: bool
    added: int
    skipped_known: int
    skipped_unparseable: int
    synced_events: int
    index_busy: bool
    claim_conflicts: list[ClaimConflict] = Field(default_factory=list)


def is_shareable(event: LedgerEvent) -> bool:
    """Return whether an event belongs in the cross-machine shared log."""
    return not (event.kind.startswith("insight.") and event.payload.get("category") in LOCAL_ONLY_INSIGHT_CATEGORIES)


def _read_raw_events(path: Path) -> tuple[list[tuple[str, LedgerEvent]], int]:
    """Read parseable event lines and return their malformed-line count."""
    if not path.exists():
        return [], 0

    events: list[tuple[str, LedgerEvent]] = []
    skipped = 0
    with path.open("rb") as handle:
        for lineno, line in enumerate(handle, start=1):
            raw_bytes = line.rstrip(b"\r\n")
            if not raw_bytes.strip():
                continue
            try:
                raw = raw_bytes.decode("utf-8")
                events.append((raw, LedgerEvent(**json.loads(raw))))
            except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
                skipped += 1
                logger.warning("%s:%d unparseable ledger line skipped", path, lineno)
    return events, skipped


def read_raw_events(path: Path) -> list[tuple[str, LedgerEvent]]:
    """Return parseable raw event lines in file order, skipping malformed lines."""
    events, _ = _read_raw_events(path)
    return events


def shared_log_files(repo_root: Path) -> list[Path]:
    """Return existing archive files followed by the current shared log."""
    archive_dir = repo_root / ARCHIVE_REL_DIR
    archives = sorted(path for path in archive_dir.glob("events-*.jsonl") if path.is_file())
    current = repo_root / SHARED_LOG_REL_PATH
    return [*archives, *([current] if current.is_file() else [])]


def read_shared_event_ids(files: list[Path]) -> set[str]:
    """Return event IDs from every parseable shared-log line."""
    return {event.event_id for path in files for _, event in read_raw_events(path)}


def _stable_relative_path(path: Path) -> Path:
    """Return the repository-stable path beginning with ``sdd`` when possible."""
    parts = path.parts
    try:
        return Path(*parts[parts.index("sdd") :])
    except ValueError:
        return path


def digest_files(files: list[Path]) -> str:
    """Return a SHA-256 digest of ordered stable paths and file content digests."""
    if not files:
        return ""
    digest = hashlib.sha256()
    for path in files:
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{_stable_relative_path(path).as_posix()}\0{content_digest}\n".encode("utf-8"))
    return digest.hexdigest()


def export_events(local: LedgerLog, repo_root: Path) -> SharedLogExportReport:
    """Append unknown, shareable local events to the committed log in local order."""
    known = read_shared_event_ids(shared_log_files(repo_root))
    dest = repo_root / SHARED_LOG_REL_PATH
    created = not dest.exists()
    added = 0
    skipped_local_only = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as handle:
        for raw, event in read_raw_events(Path(local.path)):
            if not is_shareable(event):
                skipped_local_only += 1
                continue
            if event.event_id in known:
                continue
            handle.write(raw + "\n")
            known.add(event.event_id)
            added += 1
    with dest.open(encoding="utf-8") as handle:
        total_committed = sum(1 for line in handle if line.strip())
    return SharedLogExportReport(
        dest=dest,
        created=created,
        added=added,
        skipped_local_only=skipped_local_only,
        total_committed=total_committed,
    )


def import_events(
    local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
) -> tuple[SharedLogImportReport, list[LedgerEvent]]:
    """Append committed unknown events to a local log, archives before the current log."""
    files = shared_log_files(repo_root)
    digest = digest_files(files)
    if not force and marker.exists() and marker.read_text(encoding="utf-8") == digest:
        return (
            SharedLogImportReport(
                files=files,
                fast_path=True,
                added=0,
                skipped_known=0,
                skipped_unparseable=0,
                synced_events=0,
                index_busy=False,
            ),
            [],
        )

    known = {event.event_id for event, _ in local.iter_events()}
    added = 0
    skipped_known = 0
    skipped_unparseable = 0
    imported_claims: list[LedgerEvent] = []
    for path in files:
        events, skipped = _read_raw_events(path)
        skipped_unparseable += skipped
        for raw, event in events:
            if event.event_id in known:
                skipped_known += 1
                continue
            local.append_line(raw)
            known.add(event.event_id)
            added += 1
            if event.kind == "issue.claimed":
                imported_claims.append(event)

    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary_marker = marker.with_suffix(".tmp")
    temporary_marker.write_text(digest, encoding="utf-8")
    os.replace(temporary_marker, marker)
    return (
        SharedLogImportReport(
            files=files,
            fast_path=False,
            added=added,
            skipped_known=skipped_known,
            skipped_unparseable=skipped_unparseable,
            synced_events=0,
            index_busy=False,
        ),
        imported_claims,
    )
