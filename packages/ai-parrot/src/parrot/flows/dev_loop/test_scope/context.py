"""Attempt context and escalation ledger stored in the per-worktree git dir (FEAT-563 M3)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .datatypes import AttemptContext, CoreHit, LedgerEntry

CONTEXT_FILENAME: str = "parrot-test-scope.json"
LEDGER_FILENAME: str = "parrot-test-scope-escalations.json"

_CONTEXT_FIELDS = ("tier", "task_id", "task_file", "base_ref")


def worktree_git_dir(worktree: Path) -> Path | None:
    """Per-worktree admin dir (the `gitdir:` target, NOT commondir); None outside git."""
    proc = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=worktree, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip())


def _atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON to ``path`` via a temp file in the same directory and ``os.replace``."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _read_json(path: Path) -> object | None:
    """Parsed JSON or None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_attempt_context(worktree: Path, ctx: AttemptContext) -> Path:
    """Write ``ctx`` to ``<per-worktree git dir>/parrot-test-scope.json``.

    Raises:
        RuntimeError: when ``worktree`` is not inside a git worktree.
    """
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        raise RuntimeError(f"not a git worktree: {worktree}")
    target = git_dir / CONTEXT_FILENAME
    _atomic_write_json(target, asdict(ctx))
    return target


def read_attempt_context(worktree: Path) -> AttemptContext | None:
    """None when absent or malformed — the guard is then inactive."""
    git_dir = worktree_git_dir(worktree)
    data = _read_json(git_dir / CONTEXT_FILENAME) if git_dir else None
    if not isinstance(data, dict):
        return None
    if set(data.keys()) != set(_CONTEXT_FIELDS):
        return None
    if not all(isinstance(data[field], str) for field in _CONTEXT_FIELDS):
        return None
    return AttemptContext(**data)


def _blob(worktree: Path, path: str) -> str | None:
    """Current git blob hash of a working-tree file, or None when unavailable."""
    proc = subprocess.run(["git", "hash-object", "--", path], cwd=worktree, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def read_ledger(worktree: Path) -> dict[str, LedgerEntry]:
    """Empty when absent or malformed (→ escalations re-run; never silently skipped)."""
    git_dir = worktree_git_dir(worktree)
    data = _read_json(git_dir / LEDGER_FILENAME) if git_dir else None
    ledger: dict[str, LedgerEntry] = {}
    if not isinstance(data, dict):
        return ledger
    for distribution, entry in data.items():
        if not isinstance(distribution, str) or not isinstance(entry, dict):
            return {}
        core_blobs = entry.get("core_blobs")
        if not isinstance(core_blobs, dict) or set(entry.keys()) != {"core_blobs"}:
            return {}
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in core_blobs.items()):
            return {}
        ledger[distribution] = LedgerEntry(distribution=distribution, core_blobs=dict(core_blobs))
    return ledger


def record_green_escalation(worktree: Path, hit_dists: Sequence[str], core_files: Sequence[str]) -> None:
    """Store current blob hashes of core_files for each distribution after a green run."""
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        return
    blobs = {p: b for p in core_files if (b := _blob(worktree, p))}
    current = {d: {"core_blobs": dict(e.core_blobs)} for d, e in read_ledger(worktree).items()}
    for dist in hit_dists:
        current[dist] = {"core_blobs": blobs}
    _atomic_write_json(git_dir / LEDGER_FILENAME, current)
    return None


def record_red_run(worktree: Path, hit_dists: Sequence[str]) -> None:
    """Drop each `hit_dists` distribution's ledger entry after a red escalated run (spec R14/AC9c:
    "any content change or red run re-arms it"). `record_green_escalation` is the only writer of a
    ledger entry, so without this a red run on otherwise-unchanged core-file content silently
    leaves the stale green record in place — `pending_escalations` would then keep skipping the
    same escalation on every later plan even though it is currently failing.
    """
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        return
    current = {d: {"core_blobs": dict(e.core_blobs)} for d, e in read_ledger(worktree).items()}
    changed = False
    for dist in hit_dists:
        if current.pop(dist, None) is not None:
            changed = True
    if changed:
        _atomic_write_json(git_dir / LEDGER_FILENAME, current)
    return None


def pending_escalations(worktree: Path, hits: Sequence[CoreHit]) -> tuple[list[str], list[str]]:
    """(distributions to run, distributions skipped because ledger blobs match current content)."""
    ledger = read_ledger(worktree)
    to_run: list[str] = []
    skipped: list[str] = []
    for dist in sorted({d for h in hits for d in h.distributions}):
        relevant = [h.path for h in hits if dist in h.distributions]
        entry = ledger.get(dist)
        if entry is not None and all(
            (blob := _blob(worktree, path)) is not None and blob == entry.core_blobs.get(path) for path in relevant
        ):
            skipped.append(dist)
        else:
            to_run.append(dist)
    return to_run, skipped
