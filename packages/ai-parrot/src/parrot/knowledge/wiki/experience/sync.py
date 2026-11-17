"""Synchronize and export the experience-memory event plane."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from parrot.knowledge.wiki.experience.fastpath import append_event, is_current_file, lock_exclusive, safe_open
from parrot.knowledge.wiki.experience.models import ExperienceEvent, Lesson, validate_event
from parrot.knowledge.wiki.experience.reducer import reduce_events
from parrot.knowledge.wiki.project import find_shared_root, load_project_config
from parrot.launcher import parrot_home

SHARED_DIR = Path("sdd") / "experience" / "lessons"
DEFINITION_KINDS = frozenset({"lesson.recorded"})
ATTESTATION_KINDS = frozenset({"lesson.confirmed", "lesson.quarantined", "lesson.retired", "lesson.graduated"})

_EVENTS_FILE = "events.jsonl"
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_MAX_SHARED_BYTES = 64 * 1024 * 1024
_MAX_SHARED_FILES = 1024
_MAX_CONFIG_BYTES = 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_ROTATION_LOCK_TIMEOUT_SECONDS = 5.0
_MAX_SPLIT_PASSES = 3
_DERIVED_STATES = frozenset({"confirmed", "quarantined", "retired"})
_STATE_ATTESTATION_KINDS = ATTESTATION_KINDS - frozenset({"lesson.graduated"})

logger = logging.getLogger(__name__)


def global_plane_dir() -> Path:
    """Return the user-global experience plane directory."""
    return parrot_home() / "experience"


def sync_global(repo_plane: Path) -> int:
    """Copy shared-attested, globally routed repository events into the user-global log.

    Only events backed by a shared attestation cross into ``$PARROT_HOME`` and
    therefore into other repositories: an event travels when it is tier
    ``global`` (resolved through its lesson definition) **and** its
    ``event_id`` appears in the primary checkout's reviewed
    ``sdd/experience/lessons`` files (:func:`shared_event_ids`). In practice
    that is an attested lesson's definition (``lesson.recorded``) and its
    reviewed lifecycle attestations (``lesson.confirmed`` / ``quarantined`` /
    ``retired`` / ``graduated``). Evidence events (``lesson.validated`` /
    ``refuted`` / ``injected``) are never exported to the shared directory and
    so never cross: the sandbox-writable repository log can forge them, and
    letting them travel would let a worker confirm or kill a lesson in every
    other repository. For an attested lesson the shared attestation is what
    carries its confirmed / quarantined / retired state globally; forged
    evidence stays in its own repository plane. Unattested events keep working
    locally. When no shared root can be resolved nothing crosses (fail closed).

    Evidence events do not carry their tier. Their tier is resolved from the
    matching lesson definition, including its solution revision when present.

    Args:
        repo_plane: Repository experience plane containing ``events.jsonl``.

    Returns:
        Number of previously absent events durably appended to the global log.
    """
    if not rotate_repo_log(Path(repo_plane)):
        return 0
    repo_events, repo_complete = _read_repo_events(Path(repo_plane))
    global_events, global_complete = _read_events(global_plane_dir() / _EVENTS_FILE)
    if not repo_complete or not global_complete:
        return 0

    try:
        shared_root = find_shared_root(Path(repo_plane))
    except Exception:
        logger.debug("experience sync shared-root lookup failed", exc_info=True)
        shared_root = None
    attested = shared_event_ids(shared_root) if shared_root is not None else set()

    tiers = _definition_tiers(repo_events)
    known = {event.event_id for event in global_events}
    copied = 0
    withheld = 0
    for event in repo_events:
        if event.event_id in known or _event_tier(event, tiers) != "global":
            continue
        if event.event_id not in attested:
            withheld += 1
            continue
        if not append_event(global_plane_dir(), event.model_dump(mode="json")):
            continue
        known.add(event.event_id)
        copied += 1
    if withheld:
        logger.warning("experience sync withheld %d global-tier event(s) lacking a shared attestation", withheld)
    return copied


def shared_event_ids(checkout: Path) -> set[str]:
    """Return validated event IDs from immutable shared definition files.

    Args:
        checkout: Checkout whose tracked ``sdd/experience/lessons`` directory
            should be inspected.

    Returns:
        Validated event identities, or an empty set when the bounded snapshot
        cannot be read safely.
    """
    events, complete = _read_shared_events(Path(checkout))
    return {event.event_id for event in events} if complete else set()


def export_shared(repo_plane: Path, checkout: Path) -> Path | None:
    """Export new definitions and derived lifecycle attestations immutably.

    One export never exceeds the bounded readers' cap. When more is pending,
    it holds the first events by identity and the next export continues.

    Args:
        repo_plane: Repository experience plane containing the local event log.
        checkout: Checkout that receives a new content-addressed shared file.

    Returns:
        Path to a newly created export, or ``None`` when nothing new can be
        exported safely.
    """
    repo_plane = Path(repo_plane)
    checkout = Path(checkout)
    if not rotate_repo_log(repo_plane):
        return None
    repo_events, repo_complete = _read_repo_events(repo_plane)
    global_events, global_complete = _read_events(global_plane_dir() / _EVENTS_FILE)
    shared_events, shared_complete = _read_shared_events(checkout)
    if not repo_complete or not global_complete or not shared_complete:
        return None

    try:
        shared_root = find_shared_root(checkout)
        config = load_project_config(shared_root or checkout).experience
    except Exception:
        logger.debug("experience export config lookup failed", exc_info=True)
        return None

    all_events = [*repo_events, *global_events, *shared_events]
    lessons = reduce_events(all_events, config)
    known_ids = {event.event_id for event in shared_events}
    pending: dict[str, ExperienceEvent] = {}

    for event in repo_events:
        if event.kind in DEFINITION_KINDS and event.event_id not in known_ids:
            pending[event.event_id] = event
        elif event.kind == "lesson.graduated" and event.event_id not in known_ids:
            pending[event.event_id] = event

    shared_state_keys = {_state_key(event) for event in shared_events if event.kind in _STATE_ATTESTATION_KINDS}
    local_retirements = _retirement_events(repo_events)
    for lesson_id, lesson in lessons.items():
        if lesson.state not in _DERIVED_STATES:
            continue
        desired_key = (lesson_id, lesson.state, lesson.solution_rev if lesson.state != "retired" else "")
        if desired_key in shared_state_keys:
            continue
        if lesson.state == "retired":
            retirement = local_retirements.get(lesson_id)
            if retirement is not None and retirement.event_id not in known_ids:
                pending[retirement.event_id] = retirement
            continue
        attestation = _derived_attestation(lesson)
        if attestation is not None and attestation.event_id not in known_ids:
            pending[attestation.event_id] = attestation

    if not pending:
        return None

    batch = bytearray()
    for event_id in sorted(pending):
        line = _canonical_line(pending[event_id])
        if batch and len(batch) + len(line) > _MAX_SOURCE_BYTES:
            break
        batch += line
    content = bytes(batch)
    digest = hashlib.sha256(content).hexdigest()[:16]
    shared_dir = checkout / SHARED_DIR
    if not _ensure_directory(shared_dir):
        return None
    target = shared_dir / f"{digest}.jsonl"
    descriptor = safe_open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    if descriptor is None:
        existing = _read_bytes(target, len(content))
        if existing is not None and existing != content:
            logger.warning("experience export digest collision at %s", target)
        return None

    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    except OSError:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return target


def _read_repo_events(repo_plane: Path) -> tuple[list[ExperienceEvent], bool]:
    """Read every active and sealed repository event segment as one source set."""
    events: list[ExperienceEvent] = []
    for source in _repo_event_sources(repo_plane):
        source_events, complete = _read_events(source)
        if not complete:
            return [], False
        events.extend(source_events)
    return events, True


def _repo_event_sources(repo_plane: Path) -> list[Path]:
    """Return the active log and immutable rotated segments in stable order."""
    return [repo_plane / _EVENTS_FILE, *sorted(repo_plane.glob("events-*.jsonl"))]


def rotate_repo_log(repo_plane: Path) -> bool:
    """Bring every repository event source back within the bounded readers' cap.

    An over-cap active log is first sealed under a unique ``events-*.jsonl``
    name while holding the append lock, so recorders move on to a fresh
    active log. Every over-cap sealed segment, including one sealed earlier
    without being split, is then split at line boundaries into cap-bounded
    parts. The over-cap original is removed only after all of its parts are
    durable; until then it stays in the source set and the bounded readers
    fail closed, so no reader ever observes a partial history.

    Args:
        repo_plane: Repository experience plane.

    Returns:
        ``True`` when every repository source is within the cap, otherwise
        ``False``.
    """
    repo_plane = Path(repo_plane)
    if not _seal_active_log(repo_plane):
        return False
    try:
        segments = sorted(repo_plane.glob("events-*.jsonl"))
    except OSError:
        return False
    for segment in segments:
        try:
            info = segment.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode):
            return False
        if info.st_size > _MAX_SOURCE_BYTES and not _split_segment(segment):
            return False
    return True


def _seal_active_log(repo_plane: Path) -> bool:
    """Rename an over-cap active log to a unique sealed segment under the append lock."""
    source = repo_plane / _EVENTS_FILE
    try:
        info = source.lstat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    if info.st_size <= _MAX_SOURCE_BYTES:
        return True

    descriptor = safe_open(source, os.O_RDONLY)
    if descriptor is None:
        return False
    try:
        if not lock_exclusive(descriptor, _ROTATION_LOCK_TIMEOUT_SECONDS):
            return False
        if not is_current_file(descriptor, source):
            # A concurrent rotation already sealed this log.
            return True
        if os.fstat(descriptor).st_size <= _MAX_SOURCE_BYTES:
            return True
        for _ in range(4):
            sealed = repo_plane / f"events-{time.time_ns()}-{uuid4().hex}.jsonl"
            placeholder = safe_open(sealed, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            if placeholder is None:
                continue
            try:
                os.close(placeholder)
                os.replace(source, sealed)
                return True
            except OSError:
                try:
                    sealed.unlink(missing_ok=True)
                except OSError:
                    pass
                return False
        return False
    except OSError:
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _split_segment(segment: Path) -> bool:
    """Split one over-cap sealed segment into cap-bounded parts, then remove it.

    Part names derive from the segment name and each part is published by an
    atomic replace, so an interrupted or concurrent split converges on the
    same files. A line longer than the cap cannot hold a recorded event and
    is dropped.
    """
    descriptor = safe_open(segment, os.O_RDONLY)
    if descriptor is None:
        return False
    try:
        if not lock_exclusive(descriptor, _ROTATION_LOCK_TIMEOUT_SECONDS):
            return False
        if not is_current_file(descriptor, segment):
            # A concurrent split already published the parts and removed it.
            return True
        for _ in range(_MAX_SPLIT_PASSES):
            consumed = _write_segment_parts(descriptor, segment)
            if consumed is None:
                return False
            # Re-split when a writer that predates the append lock grew the segment meanwhile.
            if os.fstat(descriptor).st_size == consumed:
                segment.unlink()
                return True
        return False
    except FileNotFoundError:
        return True
    except OSError:
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _write_segment_parts(descriptor: int, segment: Path) -> int | None:
    """Publish ``segment`` as line-aligned parts and return the bytes consumed."""
    os.lseek(descriptor, 0, os.SEEK_SET)
    part = bytearray()
    index = 0
    for line in _bounded_lines(descriptor, _MAX_SOURCE_BYTES):
        if part and len(part) + len(line) > _MAX_SOURCE_BYTES:
            if not _atomic_replace(_segment_part(segment, index), bytes(part)):
                return None
            index += 1
            part.clear()
        part += line
    if part and not _atomic_replace(_segment_part(segment, index), bytes(part)):
        return None
    return os.lseek(descriptor, 0, os.SEEK_CUR)


def _segment_part(segment: Path, index: int) -> Path:
    """Return the deterministic name of one split part of ``segment``."""
    return segment.with_name(f"{segment.stem}-{index:06d}.jsonl")


def _bounded_lines(descriptor: int, max_line_bytes: int) -> Iterator[bytes]:
    """Yield lines read from ``descriptor``, dropping any line over ``max_line_bytes``."""
    pending = bytearray()
    oversized = False
    while True:
        chunk = os.read(descriptor, _READ_CHUNK_BYTES)
        if not chunk:
            break
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            end = len(chunk) if newline < 0 else newline + 1
            if not oversized:
                pending += chunk[start:end]
                if len(pending) > max_line_bytes:
                    pending.clear()
                    oversized = True
            if newline < 0:
                break
            if not oversized:
                yield bytes(pending)
            pending.clear()
            oversized = False
            start = end
    if pending:
        yield bytes(pending)


def register_namespace(root: Path) -> bool:
    """Register the absolute primary experience store without clobbering config.

    Args:
        root: Primary checkout or any linked worktree path.

    Returns:
        ``True`` only when a new ``experience`` namespace was written.
    """
    shared_root = find_shared_root(Path(root))
    if shared_root is None:
        return False
    try:
        shared_root = shared_root.resolve()
    except OSError:
        return False

    config_path = shared_root / ".parrot" / "wiki.json"
    config = _read_config(config_path)
    if config is None:
        return False
    namespaces = config.get("namespaces")
    if namespaces is None:
        namespaces = {}
        config["namespaces"] = namespaces
    if not isinstance(namespaces, dict) or "experience" in namespaces:
        return False

    namespaces["experience"] = {"store": str(shared_root / ".parrot" / "experience")}
    try:
        payload = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    return _atomic_replace(config_path, payload)


def _read_events(path: Path, *, shared: bool = False) -> tuple[list[ExperienceEvent], bool]:
    """Read one bounded event source through the safe-open primitive."""
    payload, complete = _read_bounded(path, _MAX_SOURCE_BYTES)
    if not complete:
        return [], False
    if payload is None:
        return [], True

    events: list[ExperienceEvent] = []
    for line in payload.splitlines():
        try:
            decoded = json.loads(line)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        event = validate_event(decoded) if isinstance(decoded, dict) else None
        if event is None:
            continue
        event._shared_attestation = shared
        events.append(event)
    return events, True


def _read_shared_events(checkout: Path) -> tuple[list[ExperienceEvent], bool]:
    """Read a bounded immutable shared-directory snapshot."""
    shared_dir = checkout / SHARED_DIR
    try:
        files = sorted(shared_dir.glob("*.jsonl"))
    except OSError:
        return [], False
    if len(files) > _MAX_SHARED_FILES:
        return [], False

    events: list[ExperienceEvent] = []
    total_bytes = 0
    for path in files:
        try:
            size = path.lstat().st_size
        except OSError:
            return [], False
        total_bytes += size
        if total_bytes > _MAX_SHARED_BYTES:
            return [], False
        source_events, complete = _read_events(path, shared=True)
        if not complete:
            return [], False
        events.extend(source_events)
    return events, True


def _read_bounded(path: Path, max_bytes: int) -> tuple[bytes | None, bool]:
    """Read one regular file without following links and within ``max_bytes``."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, True
    except OSError:
        return None, False
    if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
        return None, False

    descriptor = safe_open(path, os.O_RDONLY)
    if descriptor is None:
        return None, False
    try:
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        return (payload, True) if len(payload) <= max_bytes else (None, False)
    except OSError:
        return None, False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _definition_tiers(events: Iterable[ExperienceEvent]) -> dict[tuple[str, str], str]:
    """Resolve each lesson revision to its earliest definition's tier."""
    definitions: dict[tuple[str, str], tuple[str, str, str]] = {}
    for event in events:
        if event.kind != "lesson.recorded":
            continue
        solution_rev = event.payload.get("solution_rev")
        tier = event.payload.get("tier")
        if not isinstance(solution_rev, str) or tier not in {"repo", "global"}:
            continue
        key = (event.lesson_id, solution_rev)
        candidate = (event.ts, event.event_id, tier)
        if key not in definitions or candidate[:2] < definitions[key][:2]:
            definitions[key] = candidate
    return {key: value[2] for key, value in definitions.items()}


def _event_tier(event: ExperienceEvent, tiers: dict[tuple[str, str], str]) -> str | None:
    """Resolve one event's tier through its definition revision."""
    if event.kind == "lesson.recorded":
        tier = event.payload.get("tier")
        return tier if tier in {"repo", "global"} else None
    if not event.lesson_id:
        return None
    solution_rev = event.payload.get("solution_rev")
    if isinstance(solution_rev, str):
        return tiers.get((event.lesson_id, solution_rev))
    candidates = sorted(
        (revision, tier) for (lesson_id, revision), tier in tiers.items() if lesson_id == event.lesson_id
    )
    unique = {tier for _, tier in candidates}
    return next(iter(unique)) if len(unique) == 1 else None


def _state_key(event: ExperienceEvent) -> tuple[str, str, str]:
    """Return a comparable state-attestation identity."""
    state = event.kind.removeprefix("lesson.")
    solution_rev = event.payload.get("solution_rev") if state != "retired" else ""
    return event.lesson_id, state, solution_rev if isinstance(solution_rev, str) else ""


def _retirement_events(events: Iterable[ExperienceEvent]) -> dict[str, ExperienceEvent]:
    """Return the earliest immutable retirement event for each lesson."""
    retirements: dict[str, ExperienceEvent] = {}
    for event in events:
        if event.kind != "lesson.retired":
            continue
        current = retirements.get(event.lesson_id)
        if current is None or (event.ts, event.event_id) < (current.ts, current.event_id):
            retirements[event.lesson_id] = event
    return retirements


def _derived_attestation(lesson: Lesson) -> ExperienceEvent | None:
    """Create a deterministic reviewed-log attestation for derived state."""
    return validate_event(
        {
            "schema_version": 1,
            "event_id": "",
            "kind": f"lesson.{lesson.state}",
            "lesson_id": lesson.lesson_id,
            "session": "experience-export",
            "actor": "agent:experience",
            "ts": lesson.recorded_at,
            "payload": {"solution_rev": lesson.solution_rev},
        }
    )


def _canonical_line(event: ExperienceEvent) -> bytes:
    """Serialize one event into the canonical shared JSONL representation."""
    return (
        json.dumps(event.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _ensure_directory(path: Path) -> bool:
    """Create and verify a non-symlink directory."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return stat.S_ISDIR(path.lstat().st_mode)
    except OSError:
        return False


def _read_bytes(path: Path, expected_size: int) -> bytes | None:
    """Read exactly one expected-size immutable export safely."""
    payload, complete = _read_bounded(path, expected_size)
    return payload if complete else None


def _read_config(path: Path) -> dict[str, Any] | None:
    """Read an existing config without replacing invalid or unsafe content."""
    payload, complete = _read_bounded(path, _MAX_CONFIG_BYTES)
    if not complete:
        return None
    if payload is None:
        return {}
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_replace(path: Path, payload: bytes) -> bool:
    """Atomically publish a complete config file beside its destination."""
    if not _ensure_directory(path.parent):
        return False
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    descriptor = safe_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    if descriptor is None:
        return False
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    try:
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _write_all(descriptor: int, payload: bytes) -> None:
    """Write all payload bytes to an open descriptor."""
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("short write")
        offset += written
