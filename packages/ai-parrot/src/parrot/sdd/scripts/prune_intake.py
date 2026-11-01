"""``prune_intake.py`` — prune stale /sdd-spec intake staging (FEAT-577).

Staged intake runs live under ``sdd/state/.intake/<slug>-<RUN_ID>/`` (git-ignored).
A git hook (installed by ``scripts/sdd/install_hooks.py``) calls this with
``--daily --apply`` on checkout/merge/commit; ``--daily`` lets it run at most once
per 24 h. Dry-run by default; only direct, non-symlink child directories of a
root that resolves to ``.../sdd/state/.intake`` are ever deleted.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEFAULT_ROOT: Path = Path("sdd/state/.intake")
DEFAULT_MAX_AGE_DAYS: int = 10
DAILY_INTERVAL: timedelta = timedelta(hours=24)
STAMP_NAME: str = "sdd-intake-prune.stamp"


class StaleIntake(BaseModel):
    """One staged run selected for pruning."""

    path: Path
    age_days: float
    age_source: str  # "updated_at" | "mtime"


def _repo_root() -> Path | None:
    """Resolved top-level directory of the current git work tree, or None outside a repo."""
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _check_root(root: Path, repo_root: Path | None = None) -> Path:
    """Return the resolved root, or raise ValueError when it is not an intake staging root inside a repo.

    ``repo_root`` defaults to the current git work tree's top level (via ``_repo_root()``);
    callers may pass it explicitly (e.g. tests pinning a synthetic repo boundary).
    """
    resolved = root.resolve()
    if resolved.parts[-3:] != ("sdd", "state", ".intake"):
        raise ValueError(f"refusing to prune outside sdd/state/.intake: {root}")
    repo_root = repo_root.resolve() if repo_root is not None else _repo_root()
    if repo_root is None or not (resolved == repo_root or resolved.is_relative_to(repo_root)):
        raise ValueError(f"refusing to prune a root outside the repository: {root}")
    return resolved


def run_age(run_dir: Path, now: datetime) -> tuple[timedelta, str]:
    """Age from intake.json ``updated_at``; falls back to the dir mtime when missing/unparsable."""
    intake_json = run_dir / "intake.json"
    try:
        data = json.loads(intake_json.read_text(encoding="utf-8"))
        updated_at = data["updated_at"]
        ts_str = updated_at[:-1] + "+00:00" if updated_at.endswith("Z") else updated_at
        updated = datetime.fromisoformat(ts_str)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return now - updated, "updated_at"
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        mtime = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc)
        return now - mtime, "mtime"


def find_stale(
    root: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
    repo_root: Path | None = None,
) -> list[StaleIntake]:
    """Direct child dirs of ``root`` (no symlinks) older than ``max_age_days``. Missing root → []."""
    if not root.exists():
        return []
    resolved = _check_root(root, repo_root)
    now = now or datetime.now(timezone.utc)
    max_age = timedelta(days=max_age_days)
    stale: list[StaleIntake] = []
    for entry in sorted(resolved.iterdir()):
        if entry.is_symlink() or not entry.is_dir():
            continue
        age, source = run_age(entry, now)
        if age > max_age:
            stale.append(StaleIntake(path=entry, age_days=age.total_seconds() / 86400.0, age_source=source))
    return stale


def prune(
    root: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    *,
    apply: bool = False,
    now: datetime | None = None,
    repo_root: Path | None = None,
) -> list[StaleIntake]:
    """Return the stale runs; delete them only when ``apply``. Raises ValueError for an unsafe root."""
    stale = find_stale(root, max_age_days, now, repo_root)
    if apply and root.exists():
        resolved_root = _check_root(root, repo_root)
        for run in stale:
            if run.path.parent != resolved_root or run.path.is_symlink():
                continue
            shutil.rmtree(run.path)
            logger.info("pruned %s", run.path)
    return stale


def default_stamp() -> Path | None:
    """``$(git rev-parse --git-common-dir)/sdd-intake-prune.stamp`` (shared by all worktrees); None outside a repo."""
    result = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve() / STAMP_NAME


def claim_daily_slot(stamp: Path, now: datetime | None = None) -> bool:
    """True (and touch the stamp) when the last run was ≥ 24 h ago or never; False otherwise."""
    now = now or datetime.now(timezone.utc)
    if stamp.exists():
        mtime = datetime.fromtimestamp(stamp.stat().st_mtime, tz=timezone.utc)
        if now - mtime < DAILY_INTERVAL:
            return False
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    timestamp = now.timestamp()
    os.utime(stamp, (timestamp, timestamp))
    return True


def main(argv: list[str] | None = None) -> int:
    """CLI: --root, --older-than-days (default 10), --apply, --daily, --stamp. Exit 0; 2 on an unsafe root."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--older-than-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    parser.add_argument("--daily", action="store_true", help="run at most once per 24 h (git hook mode)")
    parser.add_argument(
        "--stamp", type=Path, default=None, help="daily stamp file (default: <git-common-dir>/" + STAMP_NAME + ")"
    )
    args = parser.parse_args(argv)
    if args.daily:
        stamp = args.stamp or default_stamp()
        if stamp is None or not claim_daily_slot(stamp):
            return 0
    try:
        stale = prune(args.root, args.older_than_days, apply=args.apply)
    except ValueError as exc:
        print(str(exc))  # noqa: T201 - CLI output
        return 2
    verb = "pruned" if args.apply else "would prune"
    for run in stale:
        print(f"{verb} {run.path.name} ({run.age_days:.1f}d, {run.age_source})")  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
