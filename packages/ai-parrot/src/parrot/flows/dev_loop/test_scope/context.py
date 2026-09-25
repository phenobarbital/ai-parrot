"""Attempt context and escalation ledger stored in the per-worktree git dir (FEAT-563 M3)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
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
        if not isinstance(core_blobs, dict) or not set(entry.keys()) <= {"core_blobs", "impact_blobs", "impacted_hash"}:
            return {}
        impact_blobs = entry.get("impact_blobs", {})
        impacted_hash = entry.get("impacted_hash", "")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in core_blobs.items()):
            return {}
        if not isinstance(impact_blobs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in impact_blobs.items()
        ):
            return {}
        if not isinstance(impacted_hash, str):
            return {}
        ledger[distribution] = LedgerEntry(
            distribution=distribution,
            core_blobs=dict(core_blobs),
            impact_blobs=dict(impact_blobs),
            impacted_hash=impacted_hash,
        )
    return ledger


def _entry_payload(entry: LedgerEntry) -> dict[str, object]:
    """Serialize a ledger entry while retaining older-reader compatibility for core-only records."""
    payload: dict[str, object] = {"core_blobs": dict(entry.core_blobs)}
    if entry.impact_blobs:
        payload["impact_blobs"] = dict(entry.impact_blobs)
    if entry.impacted_hash:
        payload["impacted_hash"] = entry.impacted_hash
    return payload


def record_green_escalation(
    worktree: Path,
    hit_dists: Sequence[str],
    core_files: Sequence[str],
    impact_files: Sequence[str] = (),
    impacted_hashes: Mapping[str, str] = {},
) -> None:
    """Store blob hashes of core and impact files for each distribution after a green run."""
    git_dir = worktree_git_dir(worktree)
    if git_dir is None:
        return
    core_blobs = {p: b for p in core_files if (b := _blob(worktree, p))}
    impact_blobs = {p: b for p in impact_files if (b := _blob(worktree, p))}
    current = {d: _entry_payload(e) for d, e in read_ledger(worktree).items()}
    for dist in hit_dists:
        entry = LedgerEntry(
            distribution=dist,
            core_blobs=core_blobs,
            impact_blobs=impact_blobs,
            impacted_hash=impacted_hashes.get(dist, ""),
        )
        current[dist] = _entry_payload(entry)
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
    current = {d: _entry_payload(e) for d, e in read_ledger(worktree).items()}
    changed = False
    for dist in hit_dists:
        if current.pop(dist, None) is not None:
            changed = True
    if changed:
        _atomic_write_json(git_dir / LEDGER_FILENAME, current)
    return None


def pending_escalations(
    worktree: Path,
    hits: Sequence[CoreHit],
    cap_hits: Mapping[str, Sequence[str]] = {},
    cap_impacted: Mapping[str, str] = {},
) -> tuple[list[str], list[str]]:
    """Return distributions to run and those whose core and cap records still match."""
    ledger = read_ledger(worktree)
    to_run: list[str] = []
    skipped: list[str] = []
    for dist in sorted({d for h in hits for d in h.distributions} | set(cap_hits)):
        relevant = [h.path for h in hits if dist in h.distributions]
        entry = ledger.get(dist)
        core_matches = not relevant or (
            entry is not None
            and all(
                (blob := _blob(worktree, path)) is not None and blob == entry.core_blobs.get(path) for path in relevant
            )
        )
        cap_files = cap_hits.get(dist)
        # A present-but-EMPTY cap_files tuple (an unattributed cap escalation: the
        # policy flagged it but no changed file could be traced to it) must never
        # match vacuously via `all(...)` over an empty sequence -- there is nothing
        # to prove "unchanged" from, so it must run. Only a genuinely absent key
        # (cap_files is None, i.e. this distribution has no cap escalation at all)
        # skips the cap check entirely.
        cap_matches = cap_files is None or (
            len(cap_files) > 0
            and entry is not None
            and entry.impacted_hash != ""
            and cap_impacted.get(dist) == entry.impacted_hash
            and all(
                (blob := _blob(worktree, path)) is not None and blob == entry.impact_blobs.get(path)
                for path in cap_files
            )
        )
        if core_matches and cap_matches:
            skipped.append(dist)
        else:
            to_run.append(dist)
    return to_run, skipped
