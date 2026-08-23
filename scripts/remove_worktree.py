#!/usr/bin/env python
"""Inspect and safely remove ai-parrot git worktrees.

Two kinds of leftovers accumulate under ``.claude/worktrees/``:

* **registered** worktrees — present in ``git worktree list``, holding a real
  feature branch;
* **orphan directories** — a directory git no longer tracks (its admin data
  under ``.git/worktrees/`` was pruned, or the checkout was moved). These are
  invisible to ``git worktree list`` yet still occupy disk.

Removing either while a ``claude --agent sdd-worker`` process is live inside
is destructive: the worker commits as it goes, and a removal mid-task drops
whatever it has not pushed. Liveness is therefore checked by resolving every
process's real working directory via ``/proc/<pid>/cwd`` — a substring match
on the command line alone misses a worker that ``cd``-ed in, and flags an
unrelated process that merely mentions the path.

Usage::

    source .venv/bin/activate

    python scripts/remove_worktree.py list
    python scripts/remove_worktree.py remove feat-310-eventbus-v2 --dry-run
    python scripts/remove_worktree.py remove FEAT-417
    python scripts/remove_worktree.py remove --stale       # orphan dirs only
    python scripts/remove_worktree.py remove <target> --delete-branch

Safety gates (each overridable only with an explicit flag):

* never the primary worktree, never ``main`` / ``dev`` / ``staging``;
* a live process inside the worktree aborts the removal (no override —
  stop the worker first);
* uncommitted changes abort unless ``--force``;
* commits not present on the upstream branch abort unless ``--force``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKTREE_DIR = REPO_ROOT / ".claude" / "worktrees"
PROTECTED_BRANCHES = {"main", "dev", "staging", "master"}


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a command, capturing stdout/stderr as text."""
    return subprocess.run(
        cmd, cwd=str(cwd or REPO_ROOT), text=True, capture_output=True
    )


@dataclass
class Worktree:
    """A worktree candidate for removal.

    Attributes:
        path: Absolute checkout path.
        branch: Branch name, or None for a detached / orphan checkout.
        registered: True when git still tracks it in ``git worktree list``.
        primary: True for the main repository checkout.
    """

    path: Path
    branch: str | None
    registered: bool
    primary: bool = False
    live_processes: list[tuple[int, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    def dirty_files(self) -> list[str]:
        """Return porcelain status lines, empty when clean."""
        if not self.registered or not self.path.exists():
            return []
        proc = run(["git", "status", "--porcelain"], cwd=self.path)
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]

    def unpushed(self) -> list[str]:
        """Return commits on this branch that origin does not have.

        Falls back to comparing against ``origin/dev`` when the branch has no
        upstream configured — a worker branch that was never pushed has no
        ``@{u}``, and that is exactly the case worth warning about.
        """
        if not self.registered or not self.path.exists():
            return []
        upstream = run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=self.path,
        )
        rev = (
            f"{upstream.stdout.strip()}..HEAD"
            if upstream.returncode == 0
            else "origin/dev..HEAD"
        )
        proc = run(["git", "log", "--oneline", rev], cwd=self.path)
        if proc.returncode != 0:
            return []
        return [ln for ln in proc.stdout.splitlines() if ln.strip()]

    def pr_state(self) -> str | None:
        """Return the PR state for this branch via gh, or None if unknown."""
        if not self.branch:
            return None
        proc = run([
            "gh", "pr", "list", "--head", self.branch,
            "--state", "all", "--json", "state,number",
            "--jq", '.[0] | "\\(.state) #\\(.number)"',
        ])
        if proc.returncode != 0:
            return None
        out = proc.stdout.strip()
        return out or None


def _proc_cwd(pid: int) -> Path | None:
    """Resolve a process's working directory, or None if unreadable."""
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd"))
    except (OSError, PermissionError):
        return None


def _proc_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def live_processes_in(path: Path) -> list[tuple[int, str]]:
    """Return ``(pid, cmdline)`` for every process running inside ``path``.

    A process counts as "inside" when its resolved cwd is the worktree or a
    descendant of it. Own PID and this script's parents are skipped so a
    ``/remove-worktree`` run from inside the target does not flag itself
    without cause — it is still caught by the primary-worktree guard.
    """
    found: list[tuple[int, str]] = []
    try:
        resolved = path.resolve()
    except OSError:
        return found
    self_pid = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == self_pid:
            continue
        cwd = _proc_cwd(pid)
        if cwd is None:
            continue
        if cwd == resolved or resolved in cwd.parents:
            found.append((pid, _proc_cmdline(pid)[:160]))
    return found


def discover() -> list[Worktree]:
    """Enumerate registered worktrees plus orphan directories."""
    proc = run(["git", "worktree", "list", "--porcelain"])
    if proc.returncode != 0:
        sys.exit(f"error: not a git repository?\n{proc.stderr}")

    worktrees: list[Worktree] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines() + [""]:
        if not line.strip():
            if current.get("worktree"):
                path = Path(current["worktree"])
                branch = current.get("branch")
                if branch:
                    branch = branch.replace("refs/heads/", "")
                worktrees.append(Worktree(
                    path=path,
                    branch=branch,
                    registered=True,
                    primary=path.resolve() == REPO_ROOT.resolve(),
                ))
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value

    registered_paths = {w.path.resolve() for w in worktrees}
    if WORKTREE_DIR.is_dir():
        for child in sorted(WORKTREE_DIR.iterdir()):
            if not child.is_dir():
                continue
            if child.resolve() in registered_paths:
                continue
            worktrees.append(Worktree(path=child, branch=None, registered=False))

    for wt in worktrees:
        if not wt.primary:
            wt.live_processes = live_processes_in(wt.path)
    return worktrees


def cmd_list(args: argparse.Namespace) -> int:
    """Print every worktree with its safety-relevant state."""
    worktrees = discover()
    print(f"{'WORKTREE':<44} {'BRANCH':<38} STATE")
    print("-" * 110)
    for wt in worktrees:
        if wt.primary:
            print(f"{'(primary) ' + wt.name:<44} {wt.branch or '-':<38} protected")
            continue
        flags = []
        if not wt.registered:
            flags.append("ORPHAN-DIR")
        if wt.live_processes:
            flags.append(f"LIVE({len(wt.live_processes)})")
        dirty = wt.dirty_files()
        if dirty:
            flags.append(f"dirty:{len(dirty)}")
        unpushed = wt.unpushed()
        if unpushed:
            flags.append(f"unpushed:{len(unpushed)}")
        if args.check_pr:
            state = wt.pr_state()
            if state:
                flags.append(f"PR:{state}")
        if not flags:
            flags.append("clean")
        print(f"{wt.name:<44} {wt.branch or '-':<38} {', '.join(flags)}")
        for pid, cmdline in wt.live_processes:
            print(f"{'':<44} {'':<38}   pid {pid}: {cmdline}")
    print("\nORPHAN-DIR = directory present but not in `git worktree list`.")
    print("LIVE(n)    = n process(es) have their cwd inside — do NOT remove.")
    return 0


def _match(worktrees: list[Worktree], target: str) -> list[Worktree]:
    """Resolve a user target to worktrees (exact, then substring).

    Exact matching considers the primary checkout too, so ``remove dev``
    resolves to the protected primary and is refused by name — rather than
    falling through to a substring hit on an unrelated worktree such as
    ``feat-FEAT-378-devloop-enhancement``.
    """
    needle = target.lower()
    exact = [
        w for w in worktrees
        if w.name.lower() == needle or (w.branch or "").lower() == needle
    ]
    if exact:
        return exact
    candidates = [w for w in worktrees if not w.primary]
    try:
        resolved = Path(target).resolve()
        by_path = [w for w in candidates if w.path.resolve() == resolved]
        if by_path:
            return by_path
    except OSError:
        pass
    return [
        w for w in candidates
        if needle in w.name.lower() or needle in (w.branch or "").lower()
    ]


def _remove_one(wt: Worktree, args: argparse.Namespace) -> int:
    """Apply the safety gates and remove one worktree. Returns an exit code."""
    print(f"\n=== {wt.name}")
    print(f"  path:   {wt.path}")
    print(f"  branch: {wt.branch or '(orphan directory, no git record)'}")
    sys.stdout.flush()  # keep the header ahead of any stderr refusal below

    if wt.primary:
        print("  REFUSED: this is the primary repository checkout.",
              file=sys.stderr)
        return 1
    if wt.branch in PROTECTED_BRANCHES:
        print(f"  REFUSED: {wt.branch} is a protected branch.", file=sys.stderr)
        return 1

    if wt.live_processes:
        print("  REFUSED: a live process is running inside this worktree.",
              file=sys.stderr)
        for pid, cmdline in wt.live_processes:
            print(f"    pid {pid}: {cmdline}", file=sys.stderr)
        print("  Stop it first (the worker commits as it goes; removing now "
              "drops anything unpushed).", file=sys.stderr)
        print(f"    kill {wt.live_processes[0][0]}    # or detach the tmux "
              "session running it", file=sys.stderr)
        return 1

    dirty = wt.dirty_files()
    if dirty and not args.force:
        print(f"  REFUSED: {len(dirty)} uncommitted change(s).", file=sys.stderr)
        for line in dirty[:10]:
            print(f"    {line}", file=sys.stderr)
        if len(dirty) > 10:
            print(f"    ... and {len(dirty) - 10} more", file=sys.stderr)
        print("  Commit and push them, or re-run with --force to discard.",
              file=sys.stderr)
        return 1

    unpushed = wt.unpushed()
    if unpushed and not args.force:
        print(f"  REFUSED: {len(unpushed)} commit(s) not on origin.",
              file=sys.stderr)
        for line in unpushed[:10]:
            print(f"    {line}", file=sys.stderr)
        print(f"  Push them first:  git -C {wt.path} push -u origin "
              f"{wt.branch}", file=sys.stderr)
        print("  Or re-run with --force to discard them.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("  [dry-run] would remove this worktree"
              + (" and delete its branch" if args.delete_branch else ""))
        return 0

    if wt.registered:
        cmd = ["git", "worktree", "remove", str(wt.path)]
        if args.force:
            cmd.append("--force")
        result = run(cmd)
        if result.returncode != 0:
            print(f"  git worktree remove failed: {result.stderr.strip()}",
                  file=sys.stderr)
            return 1
        print("  removed (git worktree remove)")
    else:
        import shutil
        shutil.rmtree(wt.path)
        print("  removed (orphan directory)")

    run(["git", "worktree", "prune"])

    if args.delete_branch and wt.branch:
        flag = "-D" if args.force else "-d"
        deleted = run(["git", "branch", flag, wt.branch])
        if deleted.returncode == 0:
            print(f"  branch {wt.branch} deleted")
        else:
            print(f"  branch {wt.branch} NOT deleted: "
                  f"{deleted.stderr.strip()}")
            print("  (unmerged — pass --force to force-delete)")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove one or more worktrees after the safety gates pass."""
    worktrees = discover()

    if args.stale:
        targets = [w for w in worktrees if not w.registered]
        if not targets:
            print("No orphan directories under .claude/worktrees/.")
            return 0
        print(f"Orphan directories to remove: {len(targets)}")
    elif args.target:
        if args.target.lower() in PROTECTED_BRANCHES:
            print(f"error: {args.target} is a protected branch — refusing to "
                  "resolve it to any worktree.", file=sys.stderr)
            return 1
        targets = _match(worktrees, args.target)
        if not targets:
            print(f"error: no worktree matches {args.target!r}.\n",
                  file=sys.stderr)
            return cmd_list(argparse.Namespace(check_pr=False)) or 1
        if len(targets) > 1:
            print(f"error: {args.target!r} is ambiguous — matches: "
                  + ", ".join(t.name for t in targets), file=sys.stderr)
            return 1
    else:
        print("error: pass a target, or --stale for orphan directories.",
              file=sys.stderr)
        return 1

    failures = 0
    for wt in targets:
        failures += _remove_one(wt, args)

    print("\nRemaining worktrees:")
    run(["git", "worktree", "prune"])
    print(run(["git", "worktree", "list"]).stdout, end="")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Show worktrees and their state.")
    p_list.add_argument("--check-pr", action="store_true",
                        help="Also query PR state via gh (slower).")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="Remove a worktree safely.")
    p_rm.add_argument("target", nargs="?",
                      help="Branch name, directory name, FEAT id, or path.")
    p_rm.add_argument("--stale", action="store_true",
                      help="Remove every orphan directory (no git record).")
    p_rm.add_argument("--delete-branch", action="store_true",
                      help="Also delete the local branch.")
    p_rm.add_argument("--force", action="store_true",
                      help="Discard uncommitted/unpushed work. Never "
                           "overrides the live-process gate.")
    p_rm.add_argument("--dry-run", action="store_true")
    p_rm.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
