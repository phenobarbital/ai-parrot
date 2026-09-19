"""Worktree-local run-state persistence and process-identity validation (FEAT-581, M3).

Implements the spec §2 "Process Lifecycle and Worktree Isolation" contract for
:class:`parrot.e2e.models.RunState`:

    State is worktree-local ``sdd/state/e2e/<run-id>.json``, mode 0600; sockets
    and private profiles reside in a mode-0700 run directory. ... Atomic
    replacement and advisory file locks serialize state changes and concurrent
    down/stale commands. ... Revalidate boot ID/process creation time and
    ownership before every signal. ... Adopted browser processes are never
    signaled.

This module owns exactly three responsibilities, no more:

1. **Storage** — ``read_state``/``write_state`` (the task's fixed interfaces)
   plus the small set of path helpers (`state_dir`, `state_path`, `run_dir`,
   `list_run_ids`, `delete_state`) and the advisory lock (`locked_run`) that
   together implement mode-0600 atomic state files and mode-0700 run
   directories, safe against symlink/traversal attacks and concurrent
   competing commands (spec §2; research contract item 8,
   ``sdd/state/FEAT-581/research/lifecycle.md`` §5).
2. **Identity** — reading a live process's boot ID, PID, PGID and creation
   time (`get_boot_id`, `capture_process_identity`, `process_identity_matches`)
   per :class:`parrot.e2e.models.ProcessIdentity`'s frozen field contract
   (research contract item 10).
3. **Authorization** — a pure predicate (`is_authorized_to_signal`) that
   combines (1) and (2) to decide whether a recorded run may safely be acted
   on, *before* any signal is sent. This module never calls ``os.kill``
   itself: sending the signal is the supervisor/watchdog's job (a separate,
   not-yet-implemented M3 file); this module only ever refuses or authorizes.

Every persisted field comes from ``parrot.e2e.models`` (schema-frozen by
TASK-3520); this module adds no new persisted field and no new public class.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import psutil
from pydantic import ValidationError

from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import ProcessIdentity, RunState

__all__ = [
    "STATE_FILE_MODE",
    "RUN_DIR_MODE",
    "state_dir",
    "state_path",
    "run_dir",
    "read_state",
    "write_state",
    "delete_state",
    "list_run_ids",
    "locked_run",
    "get_boot_id",
    "capture_process_identity",
    "process_identity_matches",
    "is_authorized_to_signal",
    "is_stale",
]

# Spec §2: "State is worktree-local sdd/state/e2e/<run-id>.json, mode 0600;
# sockets and private profiles reside in a mode-0700 run directory."
STATE_FILE_MODE = 0o600
RUN_DIR_MODE = 0o700

_STATE_RELATIVE_PARTS = ("sdd", "state", "e2e")

# A nonempty "safe slug" — same convention as parrot.e2e.models' private
# `_validate_safe_id` (duplicated here, not imported: this module validates a
# raw run_id argument *before* any RunState/Pydantic model exists, to build a
# filesystem path safely; the module boundary between "validate a persisted
# field" and "validate a path-building argument" is intentional).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")

# psutil's create_time() resolution is limited by the OS clock-tick rate
# (typically 1/100s on Linux); half a second is generous slack for float
# round-tripping through a UTC datetime without weakening PID-reuse detection
# (an unrelated process reused onto the same PID differs by far more than this).
_CREATE_TIME_TOLERANCE_S = 0.5

_LOCK_POLL_INTERVAL_S = 0.02


def _validate_run_id(run_id: str) -> str:
    """Validate a run ID used to build a filesystem path (spec §2: "IDs and
    state locations never accept arbitrary filesystem paths from agent output.").

    Args:
        run_id: Candidate run ID.

    Returns:
        The validated run ID, unchanged.

    Raises:
        E2EConfigError: If ``run_id`` is empty or not a safe, single-component
            slug (rejects path separators, traversal and wildcard characters).
    """
    if not run_id or not _SAFE_ID_RE.match(run_id) or "/" in run_id or "\\" in run_id:
        raise E2EConfigError(f"run_id must be a nonempty safe slug: {run_id!r}", reason_code="run_id_unsafe")
    return run_id


def _resolve_worktree(worktree: Path) -> Path:
    """Resolve the worktree root, requiring it to already exist.

    Args:
        worktree: Candidate worktree root.

    Returns:
        The canonical (symlink-resolved, absolute) worktree path.

    Raises:
        E2EConfigError: If ``worktree`` cannot be resolved or is not a directory.
    """
    try:
        resolved = worktree.resolve(strict=True)
    except OSError as exc:
        raise E2EConfigError(
            f"worktree root does not exist or is unreadable: {worktree}: {exc}", reason_code="worktree_missing"
        ) from exc
    if not resolved.is_dir():
        raise E2EConfigError(f"worktree root is not a directory: {worktree}", reason_code="worktree_not_directory")
    return resolved


def _reject_symlink_components(path: Path, *, root: Path) -> None:
    """Refuse any path whose components (under ``root``, inclusive of ``path``) are symlinks.

    Checked component-by-component *before* any directory is created or any
    file is opened, so a pre-planted symlink can never be silently traversed
    into or through (spec §2: "reject traversal and escaping symlinks").

    Args:
        path: Absolute path to check; must already be located under ``root``
            (as a plain string/path join, not yet resolved).
        root: Canonical root every component is checked against.

    Raises:
        E2EConfigError: If any component from ``root`` down to ``path``
            (inclusive) is a symlink.
    """
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise E2EConfigError(
                f"refusing to traverse a symlink on an E2E state/run path: {current}",
                reason_code="path_symlink_escape",
            )


def state_dir(worktree: Path) -> Path:
    """Return (creating if needed) this worktree's E2E state directory.

    ``<worktree>/sdd/state/e2e`` — the shared ``sdd``/``sdd/state`` ancestors
    are ordinary checkout directories (not restricted); only paths inside the
    ``e2e`` subtree are this module's own, symlink-checked territory.

    Args:
        worktree: The owning worktree root.

    Returns:
        The resolved, existing state directory.

    Raises:
        E2EConfigError: If ``worktree`` is invalid, or any component of the
            ``sdd/state/e2e`` path is a symlink or escapes ``worktree``.
    """
    resolved_worktree = _resolve_worktree(worktree)
    (resolved_worktree / "sdd").mkdir(exist_ok=True)
    (resolved_worktree / "sdd" / "state").mkdir(exist_ok=True)
    target = resolved_worktree
    for part in _STATE_RELATIVE_PARTS:
        target = target / part
    _reject_symlink_components(target, root=resolved_worktree)
    target.mkdir(exist_ok=True)
    resolved_target = target.resolve(strict=True)
    if resolved_target != resolved_worktree and resolved_worktree not in resolved_target.parents:
        raise E2EConfigError(
            f"E2E state directory escapes worktree root: {target} -> {resolved_target}", reason_code="path_escape"
        )
    return resolved_target


def state_path(run_id: str, *, worktree: Path) -> Path:
    """Return this run's state-file path (created parent directory, file itself not created).

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.

    Returns:
        ``<worktree>/sdd/state/e2e/<run_id>.json``.

    Raises:
        E2EConfigError: If ``run_id`` or ``worktree`` is invalid.
    """
    validated_run_id = _validate_run_id(run_id)
    return state_dir(worktree) / f"{validated_run_id}.json"


def run_dir(run_id: str, *, worktree: Path) -> Path:
    """Return (creating if needed) this run's private, mode-0700 directory.

    Used for control sockets and private target profiles (spec §2), never for
    the state file itself (`state_path` is a JSON file, a sibling of this
    directory, never inside it).

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.

    Returns:
        The resolved, existing, mode-0700 run directory.

    Raises:
        E2EConfigError: If ``run_id``/``worktree`` is invalid, the path
            already exists as something other than a directory, or any
            component is a symlink or escapes ``worktree``.
    """
    validated_run_id = _validate_run_id(run_id)
    resolved_worktree = _resolve_worktree(worktree)
    directory = state_dir(resolved_worktree)
    target = directory / validated_run_id
    _reject_symlink_components(target, root=resolved_worktree)
    if target.exists() and not target.is_dir():
        raise E2EConfigError(f"expected a directory for the run dir, found a file: {target}", reason_code="path_not_directory")
    target.mkdir(mode=RUN_DIR_MODE, exist_ok=True)
    os.chmod(target, RUN_DIR_MODE)
    resolved_target = target.resolve(strict=True)
    if resolved_target != resolved_worktree and resolved_worktree not in resolved_target.parents:
        raise E2EConfigError(
            f"run directory escapes worktree root: {target} -> {resolved_target}", reason_code="path_escape"
        )
    return resolved_target


def _reject_symlink_leaf(path: Path, *, reason_code: str) -> None:
    """Refuse to use ``path`` if it is itself a symlink.

    Args:
        path: The candidate leaf path (a state file).
        reason_code: Reason code attached to the raised error.

    Raises:
        E2EConfigError: If ``path`` exists and is a symlink.
    """
    if path.is_symlink():
        raise E2EConfigError(f"refusing to use a symlinked E2E state path: {path}", reason_code=reason_code)


def read_state(run_id: str, *, worktree: Path) -> RunState:
    """Read and validate one run's persisted state.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.

    Returns:
        The validated :class:`RunState`.

    Raises:
        E2EConfigError: If ``run_id``/``worktree`` is invalid, the state file
            is a symlink, is missing, is unreadable, fails schema validation,
            or its own ``run_id`` field disagrees with the requested ``run_id``.
    """
    target = state_path(run_id, worktree=worktree)
    _reject_symlink_leaf(target, reason_code="state_symlink_escape")
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise E2EConfigError(
            f"no persisted run state for run_id={run_id!r} in {target.parent}", reason_code="state_missing"
        ) from exc
    except OSError as exc:
        raise E2EConfigError(f"run state file could not be read: {target}: {exc}", reason_code="state_unreadable") from exc

    try:
        state = RunState.model_validate_json(raw)
    except ValidationError as exc:
        raise E2EConfigError(f"run state file failed schema validation: {target}: {exc}", reason_code="state_invalid") from exc

    if state.run_id != run_id:
        raise E2EConfigError(
            f"run state run_id mismatch: {target} contains run_id={state.run_id!r}, expected {run_id!r}",
            reason_code="state_run_id_mismatch",
        )
    return state


def write_state(state: RunState, *, worktree: Path) -> None:
    """Atomically persist one run's state, mode 0600.

    Writes to a temporary file in the same directory, ``fsync``s it, then
    ``os.replace``s it onto the final path — a single atomic filesystem
    rename that either fully lands or fully fails, never a partially-written
    or interleaved state file, and never one that "follows" a symlinked
    destination through to some other file (``os.replace`` unlinks the
    destination directory entry itself, it does not write through it).

    Args:
        state: The state to persist. Must already carry ``state.worktree ==
            str(worktree.resolve())`` — this function refuses to persist a
            run under a worktree its own recorded identity disagrees with.
        worktree: The owning worktree root.

    Raises:
        E2EConfigError: If ``worktree`` is invalid, ``state.worktree``
            disagrees with the resolved ``worktree``, or the destination path
            is a symlink.
    """
    resolved_worktree = _resolve_worktree(worktree)
    if state.worktree != str(resolved_worktree):
        raise E2EConfigError(
            f"RunState.worktree {state.worktree!r} does not match the target worktree {resolved_worktree}",
            reason_code="worktree_mismatch",
        )

    target = state_path(state.run_id, worktree=resolved_worktree)
    _reject_symlink_leaf(target, reason_code="state_symlink_escape")

    payload = state.model_dump_json()
    directory = target.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{state.run_id}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, STATE_FILE_MODE)
        os.replace(tmp_name, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def delete_state(run_id: str, *, worktree: Path) -> None:
    """Remove a run's persisted state file, if present (idempotent).

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.

    Raises:
        E2EConfigError: If ``run_id``/``worktree`` is invalid, or the
            existing path is a symlink (refused rather than unlinked blindly).
    """
    target = state_path(run_id, worktree=worktree)
    _reject_symlink_leaf(target, reason_code="state_symlink_escape")
    target.unlink(missing_ok=True)


def list_run_ids(*, worktree: Path) -> list[str]:
    """List every run ID with a persisted state file in this worktree.

    Symlinked entries are skipped, never followed.

    Args:
        worktree: The owning worktree root.

    Returns:
        Sorted run IDs (state-file stems), excluding symlinks and non-files.
    """
    directory = state_dir(worktree)
    run_ids: list[str] = []
    for entry in directory.iterdir():
        if entry.is_symlink():
            continue
        if entry.is_file() and entry.suffix == ".json":
            run_ids.append(entry.stem)
    return sorted(run_ids)


@contextlib.contextmanager
def locked_run(run_id: str, *, worktree: Path, timeout_s: float = 10.0) -> Iterator[None]:
    """Serialize competing commands (e.g. concurrent ``down``/stale reconciliation) for one run.

    An advisory (``flock``) exclusive lock on a dedicated ``<run_id>.lock``
    file, held for the duration of the ``with`` block. Cooperative only (as
    all advisory locks are) — every reader/writer of this run's state must
    go through this context manager for the guarantee to hold.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
        timeout_s: Maximum seconds to wait for the lock before giving up.

    Yields:
        None, once the lock is held.

    Raises:
        E2EConfigError: If ``run_id``/``worktree`` is invalid.
        TimeoutError: If the lock could not be acquired within ``timeout_s``.
    """
    validated_run_id = _validate_run_id(run_id)
    directory = state_dir(worktree)
    lock_path = directory / f"{validated_run_id}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, STATE_FILE_MODE)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for the run lock: {run_id}") from exc
                time.sleep(_LOCK_POLL_INTERVAL_S)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def get_boot_id() -> str:
    """Read the host's boot identifier (spec §2 `ProcessIdentity.boot_id`).

    Used to detect a reboot that invalidates every previously-recorded PID on
    this host, guarding against a stale ``RunState`` surviving across a
    restart (research contract item 3, `sdd/state/FEAT-581/research/lifecycle.md`).

    Returns:
        The host boot ID string.

    Raises:
        E2EConfigError: If the boot ID cannot be read (non-Linux host, or the
            file is unavailable/unreadable).
    """
    try:
        return _BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise E2EConfigError(
            f"host boot ID is unavailable: {_BOOT_ID_PATH}: {exc}", reason_code="boot_id_unavailable"
        ) from exc


def _read_live_identity(pid: int) -> tuple[int, datetime, str]:
    """Read a live process's PGID, creation time and the host boot ID.

    Args:
        pid: The OS process ID to inspect.

    Returns:
        ``(pgid, create_time_utc, boot_id)``.

    Raises:
        E2EConfigError: If ``pid`` does not name a live, inspectable process,
            or the boot ID cannot be read.
    """
    try:
        process = psutil.Process(pid)
        create_time = process.create_time()
    except psutil.Error as exc:
        raise E2EConfigError(f"process identity unavailable for pid={pid}: {exc}", reason_code="process_unavailable") from exc
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError as exc:
        raise E2EConfigError(f"process identity unavailable for pid={pid}: {exc}", reason_code="process_unavailable") from exc
    return pgid, datetime.fromtimestamp(create_time, tz=timezone.utc), get_boot_id()


def capture_process_identity(pid: int, *, owned: bool) -> ProcessIdentity:
    """Capture a verifiable :class:`ProcessIdentity` for a live process.

    Args:
        pid: The OS process ID to capture identity for.
        owned: Whether this process was spawned by the supervisor (``True``)
            or is an adopted/foreign endpoint (``False``). Spec §2: "Adopted
            browser processes are never signaled" — this flag is what a later
            authorization check gates on.

    Returns:
        The captured :class:`ProcessIdentity`.

    Raises:
        E2EConfigError: If ``pid`` does not name a live, inspectable process.
    """
    pgid, create_time, boot_id = _read_live_identity(pid)
    return ProcessIdentity(pid=pid, pgid=pgid, create_time=create_time, boot_id=boot_id, owned=owned)


def process_identity_matches(pid: int, expected: ProcessIdentity) -> bool:
    """Revalidate that the live process at ``pid`` is provably ``expected`` (spec §2).

    Never trusts a bare PID: PGID, creation time (within a small tolerance)
    and boot ID must all agree with the *live* process, guarding against PID
    reuse (a different process later reusing the same PID) and against a
    stale record surviving a host reboot.

    Args:
        pid: The OS process ID to check (normally ``expected.pid``).
        expected: The previously recorded identity to verify against.

    Returns:
        ``True`` only if the live process's PGID, boot ID and creation time
        (within tolerance) all agree with ``expected``; ``False`` for a dead
        process, an inspection error, or any disagreement.
    """
    try:
        pgid, create_time, boot_id = _read_live_identity(pid)
    except E2EConfigError:
        return False
    if pgid != expected.pgid:
        return False
    if boot_id != expected.boot_id:
        return False
    if abs((create_time - expected.create_time).total_seconds()) > _CREATE_TIME_TOLERANCE_S:
        return False
    return True


def is_authorized_to_signal(state: RunState, *, worktree: Path, owner_id: Optional[str] = None) -> bool:
    """Decide whether ``state``'s target process may safely be signaled.

    A pure predicate: never sends a signal, only authorizes or refuses one.
    Checked in order of authority, most-definitive first — an adopted
    (non-owned) process identity refuses signaling regardless of any other
    match (spec §2: "Adopted browser processes are never signaled"), before
    the weaker worktree/owner/live-identity checks are even considered.

    Args:
        state: The recorded run state naming the candidate target process.
        worktree: The worktree the caller believes it owns this run from.
        owner_id: If given, the caller's own identity; the run's recorded
            ``owner_id`` must match.

    Returns:
        ``True`` only if the process identity is owned, the recorded
        worktree matches, the (optional) owner matches, and the live process
        still provably matches the recorded identity; ``False`` otherwise.
    """
    if not state.process_identity.owned:
        return False
    resolved_worktree = _resolve_worktree(worktree)
    if state.worktree != str(resolved_worktree):
        return False
    if owner_id is not None and state.owner_id != owner_id:
        return False
    return process_identity_matches(state.process_identity.pid, state.process_identity)


def is_stale(state: RunState, *, now: Optional[datetime] = None) -> bool:
    """Return ``True`` if ``state`` describes an expired or orphaned run.

    A run is stale when its absolute deadline has passed, or its recorded
    process identity no longer matches a live process (exited, crashed, or
    its PID was reused). Never used to authorize a signal by itself — pair
    with :func:`is_authorized_to_signal` before ever sending one, since a
    stale, non-owned (adopted) record must still never be signaled.

    Args:
        state: The recorded run state to evaluate.
        now: The current UTC instant to compare against; defaults to
            ``datetime.now(timezone.utc)``.

    Returns:
        ``True`` if the run's deadline has passed or its process identity no
        longer matches a live process; ``False`` otherwise.
    """
    current = now if now is not None else datetime.now(timezone.utc)
    if state.deadline < current:
        return True
    return not process_identity_matches(state.process_identity.pid, state.process_identity)
