"""Shared ledger event log: append-only export/import between a machine's log and git (FEAT-694)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
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
SUPERSEDING_CLAIM_KINDS: frozenset[str] = frozenset({"issue.unclaimed", "issue.closed", "issue.superseded"})
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


def live_claims(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    """Return the ``issue.claimed`` events that still stand within ``events``.

    Walks ``events`` in order, keeping at most one claim per subject — the most
    recent one — and dropping a subject entirely when a kind in
    :data:`SUPERSEDING_CLAIM_KINDS` for it follows its last claim. Pure: no I/O
    and the input is never mutated.

    This is the ONLY definition of a live claim. Both the import path
    (:func:`import_events`) and the audit path
    (:meth:`~parrot.knowledge.wiki.ledger.service.LedgerService._shared_log_audit`)
    route through it so they can never disagree about what counts as a conflict.

    Args:
        events: Ledger events in log order (archives before the current log).

    Returns:
        The surviving ``issue.claimed`` events, in the order their claim events
        appeared in ``events``.
    """
    survivors: dict[str, tuple[int, LedgerEvent]] = {}
    for position, event in enumerate(events):
        if event.kind == "issue.claimed":
            survivors[event.subject] = (position, event)
        elif event.kind in SUPERSEDING_CLAIM_KINDS:
            survivors.pop(event.subject, None)
    return [event for _, event in sorted(survivors.values(), key=lambda item: item[0])]


def import_events(
    local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
) -> tuple[SharedLogImportReport, list[LedgerEvent]]:
    """Append committed unknown events to a local log, archives before the current log.

    The returned claim list contains only live claims (:func:`live_claims`) — a claim
    superseded within the same batch is never reported as a conflict.
    """
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
        live_claims(imported_claims),
    )


def _parse_event_timestamp(timestamp: str) -> datetime | None:
    """Parse an event timestamp, interpreting naive timestamps as UTC."""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def rotate_events(
    repo_root: Path, *, older_than_days: int = ROTATION_DAYS_DEFAULT, now: datetime | None = None
) -> SharedLogRotateReport:
    """Move old terminal lines of the committed log into monthly archive files (deterministic)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    current = repo_root / SHARED_LOG_REL_PATH
    if not current.exists():
        return SharedLogRotateReport(current=current, moved=0, kept=0, cutoff=cutoff.isoformat())

    raw_lines = current.read_bytes().splitlines(keepends=True)
    parsed_lines: list[tuple[bytes, LedgerEvent | None, datetime | None]] = []
    issue_states: dict[str, tuple[str, datetime | None]] = {}
    for raw_line in raw_lines:
        event: LedgerEvent | None = None
        event_timestamp: datetime | None = None
        try:
            event = LedgerEvent(**json.loads(raw_line.decode("utf-8")))
            event_timestamp = _parse_event_timestamp(event.ts)
        except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            pass
        parsed_lines.append((raw_line, event, event_timestamp))
        if event is None or not event.kind.startswith("issue."):
            continue

        status, terminal_timestamp = issue_states.get(event.subject, ("", None))
        if event.kind == "issue.opened" and not status:
            status, terminal_timestamp = "open", None
        elif event.kind == "issue.claimed" and status == "open":
            status, terminal_timestamp = "claimed", None
        elif event.kind == "issue.closed" and status:
            status, terminal_timestamp = "closed", event_timestamp
        elif event.kind == "issue.superseded" and status:
            status, terminal_timestamp = "superseded", event_timestamp
        elif event.kind == "issue.unclaimed" and status == "claimed":
            status, terminal_timestamp = "open", None
        issue_states[event.subject] = (status, terminal_timestamp)

    moved_by_month: dict[str, list[bytes]] = {}
    kept_lines: list[bytes] = []
    for raw_line, event, event_timestamp in parsed_lines:
        movable = event is not None and event_timestamp is not None and event_timestamp < cutoff
        if movable and event.kind.startswith("issue."):
            status, terminal_timestamp = issue_states.get(event.subject, ("", None))
            movable = (
                status in TERMINAL_ISSUE_STATUSES and terminal_timestamp is not None and terminal_timestamp < cutoff
            )
        if movable:
            month = event_timestamp.strftime("%Y-%m")
            moved_by_month.setdefault(month, []).append(raw_line)
        else:
            kept_lines.append(raw_line)

    if not moved_by_month:
        return SharedLogRotateReport(current=current, moved=0, kept=len(kept_lines), cutoff=cutoff.isoformat())

    archive_dir = repo_root / ARCHIVE_REL_DIR
    archives_touched: list[Path] = []
    for month in sorted(moved_by_month):
        archive = archive_dir / ARCHIVE_FILENAME_FMT.format(yyyy_mm=month)
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("ab") as handle:
            for raw_line in moved_by_month[month]:
                handle.write(raw_line)
                if not raw_line.endswith((b"\n", b"\r")):
                    handle.write(b"\n")
        archives_touched.append(archive)

    temporary_current = current.with_suffix(f"{current.suffix}.tmp")
    temporary_current.write_bytes(b"".join(kept_lines))
    os.replace(temporary_current, current)
    return SharedLogRotateReport(
        current=current,
        moved=sum(len(lines) for lines in moved_by_month.values()),
        kept=len(kept_lines),
        archives_touched=archives_touched,
        cutoff=cutoff.isoformat(),
    )
