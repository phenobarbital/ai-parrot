"""Safely integrate base commits into a registered SDD linked worktree."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, Field

from parrot.sdd.scripts.native_claude_sandbox import BACKEND_ENV
from parrot.sdd.scripts.remove_worktree import _match, discover, live_processes_in
from parrot.sdd.scripts.sdd_meta import parse
from parrot.sdd.scripts.worktree_status import _read_worktree_index

# EXIT_TARGET (2) is the FEAT-806 spec value; argparse also exits 2 on a usage error. A usage error
# prints no --json body, which is how callers tell the two apart.
EXIT_OK, EXIT_TARGET, EXIT_DIRTY, EXIT_LIVE, EXIT_TRANSPORT, EXIT_CONFLICT = 0, 2, 3, 4, 5, 6
#: GitHub compare statuses meaning the head commit is an ancestor of, or equal to, the base tip.
_REACHABLE_COMPARE_STATUSES = frozenset({"behind", "identical"})
logger = logging.getLogger(__name__)

#: Environment knob (positive integer seconds) bounding network calls: ``git fetch`` and ``gh api``.
TIMEOUT_ENV = "PARROT_SDD_SYNC_TIMEOUT"
_DEFAULT_NETWORK_TIMEOUT = 120
#: Git state left behind by an integration that actually started (see ``git rev-parse --git-path``).
_IN_PROGRESS_PATHS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-apply", "rebase-merge")


def network_timeout() -> int:
    """Return the network-call timeout in seconds, honouring ``PARROT_SDD_SYNC_TIMEOUT``.

    Returns:
        The configured positive number of seconds, or the 120-second default when the variable is
        unset or not a positive integer.
    """
    raw = os.environ.get(TIMEOUT_ENV, "").strip()
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_NETWORK_TIMEOUT
    return value if value > 0 else _DEFAULT_NETWORK_TIMEOUT


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


def _git(wt: Path, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run Git for exactly one target worktree without shell interpolation or credential prompts.

    Args:
        wt: Target worktree.
        *args: Git arguments.
        timeout: Seconds before the call is killed. Pass it only for network operations; a local
            mutating command (merge, cherry-pick, am) killed mid-way would leave in-progress state.

    Raises:
        subprocess.TimeoutExpired: When ``timeout`` elapses.
    """
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", "-C", str(wt), *args], text=True, capture_output=True, env=environment, timeout=timeout
    )


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


def _slug_candidates(wt: Path) -> list[str]:
    """Return candidate SDD slugs for the registered branch, most specific first.

    ``feat-FEAT-<N>-<slug>`` has a fixed three-part prefix. ``hotfix-<KEY>-<slug>`` and
    ``fix-<KEY>-<slug>`` keys may themselves contain hyphens, so every suffix after the
    first part is a candidate and the caller keeps the one that names an existing file.
    """
    branch = _branch(wt)
    if not branch:
        return []
    parts = branch.split("-")
    if parts[0] == "feat" and len(parts) >= 4:
        return ["-".join(parts[3:])]
    if parts[0] in ("hotfix", "fix") and len(parts) >= 3:
        return ["-".join(parts[i:]) for i in range(2, len(parts))]
    return []


def resolve_base_branch(wt: Path, override: str | None) -> str:
    """Resolve override, selected per-spec index, brief frontmatter, then dev."""
    if override is not None:
        _validate_base(override)
        return override
    for slug in _slug_candidates(wt):
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
    branch = _branch(wt) or ""
    if branch.startswith(("hotfix-", "fix-")):
        raise SyncError(
            EXIT_TARGET, "cannot resolve the base branch of this hotfix/fix worktree; pass --base explicitly"
        )
    return "dev"


def check_guards(wt: Path) -> None:
    """Reject detached heads, dirty trees and foreign live processes using stable refusal codes.

    On the host any porcelain entry, untracked files included, makes the tree dirty. Inside the sandbox
    only tracked changes count: Claude Code's native sandbox runtime places mount placeholders for its
    protected paths (``.bashrc``, ``.claude/…``, ``.mcp.json``, ``.gitconfig``, …) in the working
    directory, so untracked entries there are not the operator's work. Ignoring them is safe because
    ``git am -3`` refuses to overwrite an untracked file, and that refusal is reported as ``refused``
    (exit 6) without any abort.
    """
    if _branch(wt) is None:
        raise SyncError(EXIT_TARGET, "target worktree has a detached HEAD; check out its feature branch first")
    if in_sandbox():
        tracked = _git(wt, "status", "--porcelain", "--untracked-files=no")
        if tracked.returncode != 0:
            raise SyncError(EXIT_TARGET, f"cannot inspect target worktree: {tracked.stderr.strip()}")
        dirty = [line for line in tracked.stdout.splitlines() if line]
    else:
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
    elif remote.startswith(("ssh://", "https://", "http://")):
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


def _operation_in_progress(wt: Path) -> bool:
    """Return whether Git holds merge, cherry-pick, revert, am or rebase state for ``wt``.

    An unreadable Git path counts as in progress, so a caller never mistakes it for a clean refusal.
    """
    for name in _IN_PROGRESS_PATHS:
        proc = _git(wt, "rev-parse", "--path-format=absolute", "--git-path", name)
        if proc.returncode != 0 or Path(proc.stdout.strip()).exists():
            return True
    return False


def _unchanged(wt: Path, before: str) -> bool:
    """Return whether a failed integration never started: same HEAD, no tracked change, no Git operation state.

    The guards required a clean tree before integrating, so the pre-state is ``before`` with no tracked
    change. Untracked files are ignored here: Git refuses a merge precisely because an untracked file is
    in the way, and that file is not something the integration wrote.
    """
    tracked = _git(wt, "status", "--porcelain", "--untracked-files=no")
    if tracked.returncode != 0 or tracked.stdout.strip():
        return False
    return _head(wt) == before and not _operation_in_progress(wt)


def _rollback(wt: Path, before: str, command: str) -> tuple[bool, list[str], str]:
    """Abort an integration and prove that HEAD and the worktree were restored; never raise."""
    conflicts = [line for line in _git(wt, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if line]
    aborted = _git(wt, command, "--abort")
    detail = aborted.stderr.strip() or aborted.stdout.strip()
    try:
        clean = not _status(wt)
    except SyncError as exc:
        return False, conflicts, f"{detail} {exc}".strip()
    restored = aborted.returncode == 0 and _head(wt) == before and clean
    return restored, conflicts, detail


def _integration_failure(
    wt: Path,
    base: str,
    mode: Literal["merge", "ff-only", "cherry-pick"],
    before: str,
    commits: list[str],
    abort_command: str,
    git_error: str = "",
) -> SyncResult:
    """Classify a failed integration by its real state: refused, verified conflict, or unrecovered error.

    Args:
        wt: Target worktree.
        base: Base branch name for the result.
        mode: Integration mode for the result.
        before: HEAD before the integration started.
        commits: Commit summaries that were being integrated.
        abort_command: Git command whose ``--abort`` undoes the integration (``am``, ``merge``, ``cherry-pick``).
        git_error: Stderr of the failed integration command, quoted in a refusal message.

    Returns:
        ``refused`` when Git rejected the integration before changing anything (no abort is attempted),
        ``conflict`` when HEAD and the worktree were restored after an abort, otherwise ``error`` with
        recovery guidance. All three use exit code 6.
    """
    if _unchanged(wt, before):
        if mode == "ff-only":
            message = "fast-forward not possible; worktree unchanged"
        else:
            reason = next((line.strip() for line in git_error.splitlines() if line.strip()), "")
            message = "integration refused before starting; worktree unchanged"
            if reason:
                message = f"{message}: {reason}"
        return _result(wt, base, mode, False, before, commits, "refused", EXIT_CONFLICT, message)
    restored, conflicts, detail = _rollback(wt, before, abort_command)
    if restored:
        return _result(
            wt,
            base,
            mode,
            False,
            before,
            commits,
            "conflict",
            EXIT_CONFLICT,
            "integration conflicted and was aborted",
            conflicts,
        )
    recovery = (
        "integration failed; automatic rollback was not verified. Inspect the worktree and run Git recovery manually."
    )
    if detail:
        recovery = f"{recovery} {detail}"
    return _result(wt, base, mode, False, before, commits, "error", EXIT_CONFLICT, recovery, conflicts)


def _sandbox_hint(detail: str) -> str:
    """Return a transport refusal with the required host recovery guidance."""
    return f"{detail} — run 'parrot sdd worktree sync-base <target>' from the host"


def push_protection_ok(wt: Path) -> bool:
    """Return whether worktree config is enabled and ``no_push`` is the sole effective push URL."""
    extension = _git(wt, "config", "--bool", "extensions.worktreeConfig")
    push_urls = _git(wt, "config", "--get-all", "remote.origin.pushurl")
    urls = [line for line in push_urls.stdout.splitlines() if line]
    return extension.returncode == 0 and extension.stdout.strip().lower() == "true" and urls == ["no_push"]


def _check_sandbox_push_protection(wt: Path) -> None:
    """Require host-provisioned worktree config and the sole no-push URL without writing configuration."""
    if not push_protection_ok(wt):
        raise SyncError(
            EXIT_TRANSPORT,
            _sandbox_hint(
                "sandbox patch sync requires host-provisioned extensions.worktreeConfig=true and exactly "
                "one effective remote.origin.pushurl=no_push (host: parrot sdd worktree push-protection enable <target>)"
            ),
        )


def _gh(wt: Path, endpoint: str, *, patch: bool = False) -> str:
    """Download one GitHub API response through gh, the sandbox's only remote transport."""
    command = ["gh", "api", endpoint]
    if patch:
        command.extend(["-H", "Accept: application/vnd.github.patch"])
    environment = {**os.environ, "GH_PROMPT_DISABLED": "1"}
    seconds = network_timeout()
    try:
        proc = subprocess.run(command, text=True, capture_output=True, cwd=wt, env=environment, timeout=seconds)
    except subprocess.TimeoutExpired as exc:
        raise SyncError(EXIT_TRANSPORT, _sandbox_hint(f"gh api timed out after {seconds}s")) from exc
    if proc.returncode != 0:
        raise SyncError(EXIT_TRANSPORT, _sandbox_hint(proc.stderr.strip() or "gh patch download failed"))
    return proc.stdout


def _is_patch_break(line: str) -> bool:
    """Return whether ``git mailinfo`` ends the commit message at ``line`` (its ``patchbreak()`` rules).

    A break is a line starting with ``diff -`` or ``Index: ``, a ``---`` followed by a space and a
    non-space character (``--- a/file``), or a ``---`` followed only by whitespace. Scissors lines are
    not considered, because ``git am`` is run without ``--scissors``.
    """
    text = line.rstrip("\r\n")
    if text.startswith(("diff -", "Index: ")):
        return True
    if not text.startswith("---"):
        return False
    rest = text[3:]
    if rest.startswith(" ") and len(rest) > 1 and not rest[1].isspace():
        return True
    return not rest.strip()


def _patch_with_trailer(patch: str, source_sha: str) -> str:
    """Insert a cherry-pick provenance trailer before git-mailinfo's first patch break in the body."""
    lines = patch.splitlines(keepends=True)
    subject_index = next((index for index, line in enumerate(lines) if line.startswith("Subject:")), None)
    if subject_index is None or not patch.startswith("From "):
        raise SyncError(EXIT_TRANSPORT, "downloaded gh patch is not a usable mailbox patch")
    # The body starts after the first blank line that ends the header block (Subject may be folded).
    body_start = next(
        (index + 1 for index in range(subject_index + 1, len(lines)) if not lines[index].strip()),
        None,
    )
    separator_index = (
        next((index for index in range(body_start, len(lines)) if _is_patch_break(lines[index])), None)
        if body_start is not None
        else None
    )
    if separator_index is None:
        raise SyncError(EXIT_TRANSPORT, "downloaded gh patch is not a usable mailbox patch")
    trailer = f"\n(cherry picked from commit {source_sha})\n"
    return "".join([*lines[:separator_index], trailer, *lines[separator_index:]])


def _require_reachable(wt: Path, repository: str, base: str, requested: str, source_sha: str) -> None:
    """Refuse a commit that GitHub does not report as an ancestor of, or equal to, ``base``.

    This is the sandbox counterpart of the host path's ``merge-base --is-ancestor`` check. Any
    unexpected response fails closed.
    """
    refusal = SyncError(EXIT_TRANSPORT, _sandbox_hint(f"cherry-pick {requested} is not reachable from origin/{base}"))
    try:
        comparison = json.loads(_gh(wt, f"repos/{repository}/compare/{base}...{source_sha}"))
    except json.JSONDecodeError as exc:
        raise refusal from exc
    if not isinstance(comparison, dict) or comparison.get("status") not in _REACHABLE_COMPARE_STATUSES:
        raise refusal


def _sandbox_patches(wt: Path, cherry_picks: Sequence[str], base: str) -> list[tuple[str, str]]:
    """Download and validate all requested non-merge commits before any worktree mutation.

    Each commit must be canonical, single-parent and reachable from ``base`` on GitHub.
    """
    repository = owner_repo(wt)
    patches: list[tuple[str, str]] = []
    for requested in cherry_picks:
        endpoint = f"repos/{repository}/commits/{requested}"
        try:
            metadata = json.loads(_gh(wt, endpoint))
        except json.JSONDecodeError as exc:
            raise SyncError(EXIT_TRANSPORT, _sandbox_hint("gh commit metadata was invalid JSON")) from exc
        source_sha = metadata.get("sha")
        parents = metadata.get("parents")
        message = metadata.get("commit", {}).get("message")
        canonical_sha = (
            isinstance(source_sha, str)
            and len(source_sha) == 40
            and all(character in "0123456789abcdefABCDEF" for character in source_sha)
        )
        if not canonical_sha or not source_sha.lower().startswith(requested.lower()) or len(parents or []) != 1:
            raise SyncError(EXIT_TRANSPORT, _sandbox_hint("merge commits need the host transport"))
        if not isinstance(message, str) or not message:
            raise SyncError(EXIT_TRANSPORT, _sandbox_hint("gh commit metadata is incomplete"))
        _require_reachable(wt, repository, base, requested, source_sha)
        patch = _patch_with_trailer(_gh(wt, endpoint, patch=True), source_sha)
        patches.append((f"{source_sha} {message.splitlines()[0]}", patch))
    return patches


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
    mode: Literal["merge", "ff-only", "cherry-pick"] = (
        "cherry-pick" if cherry_picks else "ff-only" if ff_only else "merge"
    )
    before = _head(wt)
    if not before:
        raise SyncError(EXIT_TARGET, "target has no readable HEAD")
    if in_sandbox():
        if not cherry_picks:
            raise SyncError(
                EXIT_TRANSPORT,
                "full base sync needs git objects — run 'parrot sdd worktree sync-base <target>' from the host",
            )
        _check_sandbox_push_protection(wt)
        if not dry_run:
            check_guards(wt)
        patches = _sandbox_patches(wt, cherry_picks, base)
        commits = [summary for summary, _patch in patches]
        if dry_run:
            return _result(
                wt,
                base,
                mode,
                True,
                before,
                commits,
                "up-to-date" if not commits else "synced",
                EXIT_OK,
                "up to date" if not commits else f"{len(commits)} commit(s) would be integrated",
            )
        with tempfile.TemporaryDirectory(prefix="parrot-sdd-patches-") as directory:
            patch_paths: list[str] = []
            for index, (_summary, patch) in enumerate(patches):
                path = Path(directory) / f"{index:04d}.patch"
                path.write_text(patch, encoding="utf-8")
                patch_paths.append(str(path))
            proc = _git(wt, "am", "-3", *patch_paths)
        if proc.returncode == 0:
            return _result(wt, base, mode, False, before, commits, "synced", EXIT_OK, "synchronized")
        return _integration_failure(wt, base, mode, before, commits, "am", proc.stderr)
    if not dry_run:
        check_guards(wt)
    seconds = network_timeout()
    try:
        fetched = _git(wt, "fetch", "origin", base, timeout=seconds)
    except subprocess.TimeoutExpired as exc:
        raise SyncError(EXIT_TRANSPORT, f"git fetch origin {base} timed out after {seconds}s") from exc
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
    return _integration_failure(wt, base, mode, before, commits, abort, proc.stderr)


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
        worktree=str(path),
        branch=None,
        base_branch=base,
        transport="sandbox-gh" if in_sandbox() else "host-git",
        mode="merge",
        dry_run=dry_run,
        before="",
        after="",
        commits=[],
        status="refused",
        exit_code=exc.exit_code,
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
    except (OSError, subprocess.SubprocessError) as exc:
        unavailable = SyncError(EXIT_TRANSPORT, f"required tool unavailable: {exc}")
        result = _refusal(args.target, args.base or "dev", unavailable, args.dry_run)
    if args.json:
        print(result.model_dump_json())
    else:
        print(result.message, file=sys.stdout if result.exit_code == EXIT_OK else sys.stderr)
        for commit in result.commits:
            print(commit)
        for conflict in result.conflicts:
            print(f"conflict: {conflict}", file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
