"""Safely integrate base commits into a registered SDD linked worktree."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from parrot.sdd.scripts.native_claude_sandbox import BACKEND_ENV
from parrot.sdd.scripts.remove_worktree import _match, discover, live_processes_in
from parrot.sdd.scripts.sdd_meta import parse
from parrot.sdd.scripts.worktree_status import _read_worktree_index

EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6
logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Operator-facing refusal with a stable exit code."""

    def __init__(self, exit_code: int, message: str) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class SyncResult(BaseModel):
    """Machine-readable synchronization outcome."""

    worktree: str
    branch: str | None
    base_branch: str
    transport: Literal["host-git", "sandbox-gh"]
    mode: Literal["merge", "ff-only", "cherry-pick"]
    dry_run: bool
    before: str
    after: str
    commits: list[str]
    status: Literal["synced", "up-to-date", "refused", "conflict", "error"]
    exit_code: int
    message: str
    conflicts: list[str] = Field(default_factory=list)


def _git(wt: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run Git for exactly one target worktree without shell interpolation."""
    return subprocess.run(["git", "-C", str(wt), *args], text=True, capture_output=True)


def _head(wt: Path) -> str:
    """Return the target HEAD, or an empty value when Git cannot read it."""
    proc = _git(wt, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _branch(wt: Path) -> str | None:
    """Return the checked-out branch, retaining None for detached heads."""
    proc = _git(wt, "symbolic-ref", "--quiet", "--short", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _status(wt: Path) -> list[str]:
    """Return porcelain lines or raise an operational transport refusal."""
    proc = _git(wt, "status", "--porcelain")
    if proc.returncode != 0:
        raise SyncError(EXIT_TARGET, f"cannot inspect target worktree: {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line]


def _validate_base(base: str) -> None:
    """Require a branch-shaped base name before giving it to Git."""
    if not base or base.startswith("-"):
        raise SyncError(EXIT_TARGET, f"invalid base branch: {base!r}")
    proc = subprocess.run(["git", "check-ref-format", "--branch", base], text=True, capture_output=True)
    if proc.returncode != 0:
        raise SyncError(EXIT_TARGET, f"invalid base branch: {base!r}")


def _validate_commit(commit: str) -> None:
    """Require a hexadecimal commit identifier, not arbitrary Git syntax."""
    if not 7 <= len(commit) <= 64 or any(char not in "0123456789abcdefABCDEF" for char in commit):
        raise SyncError(EXIT_TARGET, f"invalid commit SHA: {commit!r}")


def in_sandbox() -> bool:
    """Return whether BACKEND_ENV selects a sandbox."""
    return bool(os.environ.get(BACKEND_ENV))


def own_ancestry() -> set[int]:
    """Return this process and ancestors by walking Linux proc stat parent fields."""
    found: set[int] = set()
    pid = os.getpid()
    while pid > 0 and pid not in found:
        found.add(pid)
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            closing = stat.rfind(")")
            fields = stat[closing + 2 :].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            break
    return found


def resolve_target(target: str) -> Path:
    """Require one registered non-primary linked worktree with matching Git top-level."""
    matches = _match(discover(), target)
    if len(matches) != 1:
        names = ", ".join(str(match.path) for match in matches) or "none"
        raise SyncError(EXIT_TARGET, f"target must resolve to one worktree (matches: {names})")
    worktree = matches[0]
    if worktree.primary or not worktree.registered:
        raise SyncError(EXIT_TARGET, "target must be a registered non-primary linked worktree")
    proc = _git(worktree.path, "rev-parse", "--show-toplevel")
    try:
        git_root = Path(proc.stdout.strip()).resolve()
        requested = worktree.path.resolve()
    except OSError as exc:
        raise SyncError(EXIT_TARGET, f"cannot resolve target worktree: {exc}") from exc
    if proc.returncode != 0 or git_root != requested:
        raise SyncError(EXIT_TARGET, "target Git top-level does not match the registered worktree")
    return requested


def _slug_for(wt: Path) -> str | None:
    """Derive the selected SDD worktree slug from its registered branch."""
    branch = _branch(wt)
    if not branch:
        return None
    parts = branch.split("-", 3)
    if len(parts) == 4 and parts[0] == "feat":
        return parts[3]
    if len(parts) == 3 and parts[0] == "hotfix":
        return parts[2]
    if len(parts) == 3 and parts[0] == "fix":
        return parts[2]
    return None


def resolve_base_branch(wt: Path, override: str | None) -> str:
    """Resolve override, selected per-spec index, brief frontmatter, then dev."""
    if override is not None:
        _validate_base(override)
        return override
    slug = _slug_for(wt)
    if slug:
        index = wt / "sdd" / "tasks" / "index" / f"{slug}.json"
        if index.is_file():
            _, base = _read_worktree_index(wt, slug)
            if isinstance(base, str) and base.strip():
                _validate_base(base.strip())
                return base.strip()
        brief = wt / "sdd" / "briefs" / f"{slug}.brief.md"
        if brief.is_file():
            try:
                base = parse(brief).base_branch
            except Exception as exc:
                logger.warning("Cannot parse selected brief %s: %s", brief, exc)
            else:
                _validate_base(base)
                return base
    return "dev"


def check_guards(wt: Path) -> None:
    """Reject dirty trees and foreign live processes using stable refusal codes."""
    dirty = _status(wt)
    if dirty:
        raise SyncError(EXIT_DIRTY, "target worktree is dirty:\n" + "\n".join(dirty))
    live = live_processes_in(wt, exclude_pids=own_ancestry())
    if live:
        details = "\n".join(f"pid {pid}: {cmdline}" for pid, cmdline in live)
        raise SyncError(EXIT_LIVE, f"live process(es) inside target worktree:\n{details}")


def owner_repo(wt: Path) -> str:
    """Parse owner/repo from SSH or HTTPS origin URLs."""
    proc = _git(wt, "remote", "get-url", "origin")
    remote = proc.stdout.strip()
    if proc.returncode != 0 or not remote:
        raise SyncError(EXIT_TRANSPORT, "origin remote is unavailable")
    if remote.startswith("git@") and ":" in remote:
        path = remote.split(":", 1)[1]
    elif remote.startswith("ssh://") or remote.startswith("https://") or remote.startswith("http://"):
        path = remote.split("://", 1)[1].split("/", 1)[1] if "/" in remote.split("://", 1)[1] else ""
    else:
        raise SyncError(EXIT_TRANSPORT, f"unsupported origin URL: {remote}")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        raise SyncError(EXIT_TRANSPORT, f"unsupported origin URL: {remote}")
    return path


def _commits(wt: Path, revision: str) -> list[str]:
    """Return compact commit descriptions for a previously validated revision."""
    proc = _git(wt, "log", "--format=%H %s", revision)
    if proc.returncode != 0:
        raise SyncError(EXIT_TRANSPORT, proc.stderr.strip() or f"cannot inspect {revision}")
    return [line for line in proc.stdout.splitlines() if line]


def _result(
    wt: Path,
    base: str,
    mode: Literal["merge", "ff-only", "cherry-pick"],
    dry_run: bool,
    before: str,
    commits: list[str],
    status: Literal["synced", "up-to-date", "refused", "conflict", "error"],
    code: int,
    message: str,
    conflicts: list[str] | None = None,
) -> SyncResult:
    """Build a result from the target's actual post-operation state."""
    return SyncResult(
        worktree=str(wt),
        branch=_branch(wt),
        base_branch=base,
        transport="sandbox-gh" if in_sandbox() else "host-git",
        mode=mode,
        dry_run=dry_run,
        before=before,
        after=_head(wt),
        commits=commits,
        status=status,
        exit_code=code,
        message=message,
        conflicts=conflicts or [],
    )


def _rollback(wt: Path, before: str, command: str) -> tuple[bool, list[str], str]:
    """Abort an integration and prove that HEAD and the worktree were restored."""
    conflicts = [line for line in _git(wt, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if line]
    aborted = _git(wt, command, "--abort")
    restored = aborted.returncode == 0 and _head(wt) == before and not _status(wt)
    detail = aborted.stderr.strip() or aborted.stdout.strip()
    return restored, conflicts, detail


def sync(
    wt: Path,
    base: str,
    *,
    cherry_picks: Sequence[str] = (),
    ff_only: bool = False,
    dry_run: bool = False,
) -> SyncResult:
    """Integrate safely; only report conflict after verified rollback."""
    _validate_base(base)
    if ff_only and cherry_picks:
        raise SyncError(EXIT_TARGET, "--ff-only cannot be combined with --cherry-pick")
    for commit in cherry_picks:
        _validate_commit(commit)
    mode: Literal["merge", "ff-only", "cherry-pick"] = "cherry-pick" if cherry_picks else "ff-only" if ff_only else "merge"
    before = _head(wt)
    if not before:
        raise SyncError(EXIT_TARGET, "target has no readable HEAD")
    if in_sandbox():
        raise SyncError(
            EXIT_TRANSPORT,
            "full base sync needs git objects — run 'parrot sdd worktree sync-base <target>' from the host",
        )
    if not dry_run:
        check_guards(wt)
    fetched = _git(wt, "fetch", "origin", base)
    if fetched.returncode != 0:
        raise SyncError(EXIT_TRANSPORT, fetched.stderr.strip() or f"cannot fetch origin/{base}")
    remote = f"origin/{base}"
    if _git(wt, "rev-parse", "--verify", f"{remote}^{{commit}}").returncode != 0:
        raise SyncError(EXIT_TRANSPORT, f"fetched base is not a commit: {remote}")
    if cherry_picks:
        for commit in cherry_picks:
            if _git(wt, "merge-base", "--is-ancestor", commit, remote).returncode != 0:
                raise SyncError(EXIT_TRANSPORT, f"cherry-pick {commit} is not reachable from {remote}")
        commits: list[str] = []
        for commit in cherry_picks:
            commits.extend(_commits(wt, commit))
    else:
        commits = _commits(wt, f"HEAD..{remote}")
    if dry_run:
        status = "up-to-date" if not commits else "synced"
        message = "up to date" if not commits else f"{len(commits)} commit(s) would be integrated"
        return _result(wt, base, mode, True, before, commits, status, EXIT_OK, message)
    if not commits:
        return _result(wt, base, mode, False, before, commits, "up-to-date", EXIT_OK, "up to date")
    check_guards(wt)
    if cherry_picks:
        proc = _git(wt, "cherry-pick", "-x", *cherry_picks)
        abort = "cherry-pick"
    else:
        proc = _git(wt, "merge", "--ff-only" if ff_only else "--no-edit", remote)
        abort = "merge"
    if proc.returncode == 0:
        return _result(wt, base, mode, False, before, commits, "synced", EXIT_OK, "synchronized")
    restored, conflicts, detail = _rollback(wt, before, abort)
    if restored:
        return _result(
            wt, base, mode, False, before, commits, "conflict", EXIT_CONFLICT,
            "integration conflicted and was aborted", conflicts,
        )
    recovery = "integration failed; automatic rollback was not verified. Inspect the worktree and run Git recovery manually."
    if detail:
        recovery = f"{recovery} {detail}"
    return _result(wt, base, mode, False, before, commits, "error", EXIT_CONFLICT, recovery, conflicts)


def stale_base_summary(wt: Path, base: str | None = None) -> str:
    """Return an advisory host dry-run summary or a skipped reason; never raise."""
    try:
        selected = resolve_base_branch(wt, base)
        result = sync(wt, selected, dry_run=True)
    except (SyncError, OSError, subprocess.SubprocessError) as exc:
        return f"stale-base check skipped: {exc}"
    if result.commits:
        return (
            f"base {result.base_branch}: {len(result.commits)} commit(s) ahead of this worktree — "
            "run `parrot sdd worktree sync-base <name>` from the host"
        )
    return f"base {result.base_branch}: up to date"


def _refusal(target: str, base: str, exc: SyncError, dry_run: bool) -> SyncResult:
    """Build JSON-safe CLI refusal output without assuming a valid target path."""
    path = Path(target)
    return SyncResult(
        worktree=str(path), branch=None, base_branch=base, transport="sandbox-gh" if in_sandbox() else "host-git",
        mode="merge", dry_run=dry_run, before="", after="", commits=[], status="refused", exit_code=exc.exit_code,
        message=str(exc),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse target and sync flags, emit human/JSON output and return the result code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("--base")
    parser.add_argument("--cherry-pick", action="append", default=[])
    parser.add_argument("--ff-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        wt = resolve_target(args.target)
        base = resolve_base_branch(wt, args.base)
        result = sync(wt, base, cherry_picks=args.cherry_pick, ff_only=args.ff_only, dry_run=args.dry_run)
    except SyncError as exc:
        result = _refusal(args.target, args.base or "dev", exc, args.dry_run)
    if args.json:
        print(result.model_dump_json())
    else:
        print(result.message)
        for commit in result.commits:
            print(commit)
        for conflict in result.conflicts:
            print(f"conflict: {conflict}", file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
