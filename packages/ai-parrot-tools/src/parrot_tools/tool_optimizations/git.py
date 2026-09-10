"""Deterministic local Git operations for Claude Code / Codex (FEAT-543).

:class:`LocalGitToolkit` replaces the predictable Git command sequences a
coding host would otherwise construct token by token. It performs **no LLM
calls** and returns bounded :class:`OperationResult` models carrying one
:class:`StepResult` per Git command actually executed, so a caller can always
see which step failed instead of inferring success from the last command.

Safety properties (spec §2 "Git Contract"):

* Every invocation is an argv list — never a shell string, never a
  caller-interpolated option. ``--end-of-options`` precedes refs and ``--``
  precedes paths.
* Output is drained concurrently with a memory cap, but reading continues to
  EOF so a child never blocks on a full pipe. Truncation never turns a
  failure into a success.
* Remote and branch names are validated against allow-lists; refspecs and
  revision expressions are rejected where a branch name is required.
* A fetch failure stops dependent history lookup, and freshness is verified
  against the actually fetched commit rather than assumed.

This module owns the read-only and fetch-only half of the toolkit;
``git_prepare_files`` / ``git_pull`` / ``git_push`` are added by TASK-3081.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from parrot.tools.decorators import tool_schema
from parrot.tools.repo.git_tools import LOG_FORMAT, InvalidRefError, parse_log, validate_ref
from pydantic import BaseModel, ConfigDict

from .base import OptimizationToolkitBase
from .models import (
    GitFetchArgs,
    GitPreflightArgs,
    GitRecentArgs,
    OperationResult,
    StepResult,
)

__all__ = ("GIT_ENV", "MIN_GIT_VERSION", "RepoLayout", "LocalGitToolkit")

#: Environment forced onto every Git invocation.
#:
#: ``GIT_CONFIG_NOSYSTEM`` is deliberately **not** set: user and system config
#: must still apply so remotes, credential helpers and transport settings work.
GIT_ENV: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_EDITOR": ":",
    "GIT_SEQUENCE_EDITOR": ":",
    "GIT_PAGER": "cat",
    "GIT_OPTIONAL_LOCKS": "0",
    "LC_ALL": "C",
    "LANG": "C",
    "GIT_LITERAL_PATHSPECS": "1",
}

#: ``--end-of-options`` and ``--absolute-git-dir`` both require git >= 2.24.
MIN_GIT_VERSION = (2, 24)

#: Remote names: no leading dash, no path or option characters.
_REMOTE_OK = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*$")

#: Branch names: conservative subset. Refspecs (':'), revision expressions
#: ('~', '^', '@{') and option-shaped values cannot match.
_BRANCH_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")

_GIT_VERSION_RE = re.compile(r"git version (\d+)\.(\d+)")


class RepoLayout(BaseModel):
    """The discovered layout of the repository this toolkit operates on.

    Attributes:
        toplevel: The work-tree root (equals the configured ``repo_root``).
        git_dir: The **per-worktree** git directory, absolute. For a linked
            worktree this is ``<main>/.git/worktrees/<name>``.
        common_dir: The shared git directory holding refs and objects.
        is_linked_worktree: True when ``git_dir`` differs from ``common_dir``.
        index_path: The per-worktree index file.
        lock_path: The toolkit's advisory lock, scoped to this worktree.
    """

    model_config = ConfigDict(extra="forbid")

    toplevel: Path
    git_dir: Path
    common_dir: Path
    is_linked_worktree: bool
    index_path: Path
    lock_path: Path


async def _drain(stream: asyncio.StreamReader, cap: int) -> tuple[bytes, bool]:
    """Read ``stream`` to EOF, retaining at most ``cap`` bytes.

    Reading continues past the cap and the excess is discarded, so the child
    process can never block writing into a full pipe (which would deadlock a
    naive capped reader).

    Args:
        stream: The subprocess stream to drain.
        cap: Maximum number of bytes to retain.

    Returns:
        A ``(retained_bytes, truncated)`` tuple.
    """
    buf = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(buf), truncated
        if len(buf) < cap:
            room = cap - len(buf)
            buf += chunk[:room]
            if len(chunk) > room:
                truncated = True
        else:
            truncated = True


class LocalGitToolkit(OptimizationToolkitBase):
    """Bounded, deterministic Git operations confined to one repository.

    All paths and refs are validated before any subprocess starts. No method
    here invokes an LLM.

    Example:
        >>> toolkit = LocalGitToolkit(repo_root="/path/to/repo")
        >>> result = await toolkit.git_preflight()
        >>> result.status
        'ok'
    """

    arg_models: dict[str, type[BaseModel]] = {
        "git_recent": GitRecentArgs,
        "git_fetch": GitFetchArgs,
        "git_preflight": GitPreflightArgs,
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the toolkit.

        Args:
            **kwargs: Forwarded to
                :class:`~parrot_tools.tool_optimizations.base.OptimizationToolkitBase`
                (``repo_root`` is required).
        """
        super().__init__(**kwargs)
        self._layout: Optional[RepoLayout] = None
        self._git_version: Optional[tuple[int, int]] = None

    # ----------------------------------------------------------------- #
    # Subprocess runner
    # ----------------------------------------------------------------- #
    async def _run_git(
        self,
        args: Sequence[str],
        *,
        timeout: Optional[float] = None,
        cwd: Optional[Path] = None,
        extra_env: Optional[dict[str, str]] = None,
        stdin_bytes: Optional[bytes] = None,
        max_capture: int = 1_048_576,
    ) -> tuple[StepResult, bytes]:
        """Run one Git command, bounded, non-interactive and kill-safe.

        Args:
            args: Git arguments (without the leading ``git``).
            timeout: Seconds; defaults to ``policy.command_timeout_seconds``.
            cwd: Working directory; defaults to the configured repo root.
            extra_env: Extra environment entries layered over :data:`GIT_ENV`.
            stdin_bytes: Bytes to write to the child's stdin, if any.
            max_capture: Maximum stdout bytes retained.

        Returns:
            A ``(StepResult, raw_stdout)`` tuple. The raw bytes let callers
            split NUL-delimited (``-z``) output without a decode round-trip.
            ``state_changed`` is always False here — only the caller knows
            whether a command mutated state.

        Raises:
            asyncio.CancelledError: Re-raised after killing the child, so a
                cancelled dispatch leaves no orphan process.
        """
        name = args[0] if args else "git"
        env = {**os.environ, **GIT_ENV, **(extra_env or {})}
        limit = timeout if timeout is not None else self.policy.command_timeout_seconds
        self.logger.debug("running git %s", " ".join(args))

        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd or self.policy.repo_root),
            env=env,
            stdin=asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(limit):
                if stdin_bytes is not None and proc.stdin is not None:
                    proc.stdin.write(stdin_bytes)
                    await proc.stdin.drain()
                    proc.stdin.close()
                (out, out_trunc), (err, err_trunc) = await asyncio.gather(
                    _drain(proc.stdout, max_capture),
                    _drain(proc.stderr, 65536),
                )
                code = await proc.wait()
        except (TimeoutError, asyncio.TimeoutError):
            self._kill(proc)
            await proc.wait()
            return (
                StepResult(name=name, exit_code=None, timed_out=True, state_changed=False, stderr="timeout"),
                b"",
            )
        except asyncio.CancelledError:
            self._kill(proc)
            raise

        return (
            StepResult(
                name=name,
                exit_code=code,
                timed_out=False,
                state_changed=False,
                stdout=out.decode("utf-8", "replace"),
                stderr=err.decode("utf-8", "replace")[:4096],
                truncated=out_trunc or err_trunc,
            ),
            out,
        )

    @staticmethod
    def _kill(proc: asyncio.subprocess.Process) -> None:
        """Best-effort terminate; an already-exited child is not an error."""
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    # ----------------------------------------------------------------- #
    # Discovery and validation
    # ----------------------------------------------------------------- #
    async def _check_git_version(self, operation: str, started: float) -> Optional[OperationResult]:
        """Verify the git binary is new enough for the flags this module uses.

        Args:
            operation: The calling operation name, for the error result.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            None when the version is acceptable, else an error result.
        """
        if self._git_version is not None:
            return None
        step, _ = await self._run_git(["--version"])
        match = _GIT_VERSION_RE.search(step.stdout or "")
        if step.exit_code != 0 or match is None:
            return self._error(
                operation, "git_unavailable", "could not determine the git version", steps=[step], started=started
            )
        version = (int(match.group(1)), int(match.group(2)))
        if version < MIN_GIT_VERSION:
            return self._error(
                operation,
                "git_too_old",
                f"git {version[0]}.{version[1]} is older than the required {MIN_GIT_VERSION[0]}.{MIN_GIT_VERSION[1]}",
                steps=[step],
                started=started,
            )
        self._git_version = version
        return None

    async def _discover(
        self, operation: str = "discover", started: Optional[float] = None
    ) -> RepoLayout | OperationResult:
        """Discover the repository layout, supporting linked worktrees.

        ``.git`` may be a *file* in a linked worktree, so the layout is
        obtained from Git itself rather than by probing the filesystem.

        Args:
            operation: The calling operation name, for any error result.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The cached :class:`RepoLayout`, or an :class:`OperationResult`
            describing why discovery failed.
        """
        if self._layout is not None:
            return self._layout
        started = started if started is not None else time.perf_counter()

        version_error = await self._check_git_version(operation, started)
        if version_error is not None:
            return version_error

        step, _ = await self._run_git(
            ["rev-parse", "--is-bare-repository", "--show-toplevel", "--absolute-git-dir", "--git-common-dir"]
        )
        lines = step.stdout.splitlines()
        # A bare repository answers "true" and then dies on --show-toplevel,
        # so the bare check must precede the exit-code check.
        if lines and lines[0].strip() == "true":
            return self._error(
                operation,
                "bare_repository",
                "worktree operations require a non-bare repository",
                steps=[step],
                started=started,
            )
        if step.exit_code != 0 or len(lines) < 4:
            return self._error(
                operation,
                "not_a_repository",
                f"{str(self.policy.repo_root)!r} is not inside a git work tree",
                steps=[step],
                started=started,
            )

        toplevel = Path(lines[1].strip()).resolve()
        git_dir = Path(lines[2].strip()).resolve()
        common_raw = lines[3].strip()
        common_dir = Path(common_raw)
        if not common_dir.is_absolute():
            common_dir = (self.policy.repo_root / common_raw).resolve()
        else:
            common_dir = common_dir.resolve()

        if toplevel != self.policy.repo_root:
            return self._error(
                operation,
                "root_mismatch",
                "repo_root is not the work-tree toplevel",
                details={"repo_root": str(self.policy.repo_root), "toplevel": str(toplevel)},
                steps=[step],
                started=started,
            )

        self._layout = RepoLayout(
            toplevel=toplevel,
            git_dir=git_dir,
            common_dir=common_dir,
            is_linked_worktree=git_dir != common_dir,
            index_path=git_dir / "index",
            lock_path=git_dir / "parrot-tool-optimizations.lock",
        )
        return self._layout

    async def _remote_names(self) -> tuple[list[str], StepResult]:
        """List the configured remote names.

        Returns:
            A ``(names, step)`` tuple.
        """
        step, _ = await self._run_git(["remote"])
        names = [line.strip() for line in step.stdout.splitlines() if line.strip()] if step.exit_code == 0 else []
        return names, step

    @staticmethod
    def _validate_remote(remote: str, remotes: Sequence[str]) -> str:
        """Validate a remote name against shape rules and the configured set.

        Args:
            remote: The caller-supplied remote name.
            remotes: The names Git reports as configured.

        Returns:
            The remote name, unchanged.

        Raises:
            ValueError: The name is option-shaped, malformed, or unknown.
        """
        if not _REMOTE_OK.match(remote):
            raise ValueError(f"malformed remote name: {remote!r}")
        if remote not in remotes:
            raise ValueError(f"unknown remote: {remote!r}")
        return remote

    async def _validate_branch(self, branch: str) -> str:
        """Validate that ``branch`` is a real branch name, not a revision.

        A refspec, a revision expression or an option-shaped value must never
        reach ``git fetch``/``pull``/``push``, where they change the meaning
        of the operation.

        Args:
            branch: The caller-supplied branch name.

        Returns:
            The branch name, unchanged.

        Raises:
            ValueError: The name is malformed or Git rejects its ref format.
        """
        if not _BRANCH_OK.match(branch):
            raise ValueError(f"malformed branch name: {branch!r}")
        if ".." in branch or "@{" in branch or branch.endswith((".lock", "/", ".")):
            raise ValueError(f"malformed branch name: {branch!r}")
        # The regex already forbids a leading '-', so this cannot be an option.
        step, _ = await self._run_git(["check-ref-format", "--branch", branch])
        if step.exit_code != 0:
            raise ValueError(f"git rejected the branch name: {branch!r}")
        return branch

    async def _resolve_commit(self, ref: str) -> tuple[Optional[str], StepResult]:
        """Resolve ``ref`` to a concrete commit sha.

        Args:
            ref: A caller-supplied ref.

        Returns:
            A ``(sha_or_None, step)`` tuple.

        Raises:
            InvalidRefError: The ref is option-shaped or malformed.
        """
        safe = validate_ref(ref)
        step, _ = await self._run_git(["rev-parse", "--verify", "--quiet", "--end-of-options", f"{safe}^{{commit}}"])
        sha = step.stdout.strip()
        if step.exit_code != 0 or len(sha) != 40:
            return None, step
        return sha, step

    async def _log_step(self, sha: str, limit: int) -> tuple[list[dict[str, str]], StepResult]:
        """Read bounded commit history starting at ``sha``.

        Args:
            sha: A resolved 40-hex commit sha.
            limit: Maximum number of commits.

        Returns:
            A ``(commits, step)`` tuple.
        """
        step, _ = await self._run_git(
            ["log", f"--max-count={int(limit)}", f"--format={LOG_FORMAT}", "--end-of-options", sha, "--"]
        )
        commits = parse_log(step.stdout) if step.exit_code == 0 else []
        return commits, step

    # ----------------------------------------------------------------- #
    # Public tools
    # ----------------------------------------------------------------- #
    @tool_schema(GitRecentArgs)
    async def git_recent(self, ref: str = "HEAD", limit: int = 3) -> OperationResult:
        """Show recent commits for a ref, as compact structured records.

        Args:
            ref: The ref to read history from. Defaults to ``HEAD``.
            limit: How many commits to return, between 1 and 50.

        Returns:
            An operation result whose ``data`` carries ``ref``, the resolved
            ``commit`` and a ``commits`` list of
            ``{sha, author, date, subject}`` records.
        """
        started = time.perf_counter()
        try:
            args = GitRecentArgs(ref=ref, limit=limit)
        except Exception as exc:  # pydantic ValidationError
            return self._error("git_recent", "invalid_arguments", str(exc), started=started)

        layout = await self._discover("git_recent", started)
        if isinstance(layout, OperationResult):
            return layout

        try:
            sha, resolve_step = await self._resolve_commit(args.ref)
        except InvalidRefError as exc:
            # Rejected before any git process is spawned.
            return self._error("git_recent", "invalid_ref", str(exc), started=started)
        if sha is None:
            return self._error(
                "git_recent",
                "unknown_ref",
                f"could not resolve {args.ref!r} to a commit",
                steps=[resolve_step],
                started=started,
            )

        commits, log_step = await self._log_step(sha, args.limit)
        steps = [resolve_step, log_step]
        if log_step.exit_code != 0:
            return self._error("git_recent", "log_failed", "git log failed", steps=steps, started=started)
        return self._ok("git_recent", {"ref": args.ref, "commit": sha, "commits": commits}, steps, started)

    @tool_schema(GitFetchArgs)
    async def git_fetch(self, remote: str = "origin", branch: str = "dev", recent: int = 3) -> OperationResult:
        """Fetch one branch from a configured remote and report what arrived.

        The explicit destination refspec is required: a bare
        ``git fetch <remote> <branch>`` only guarantees ``FETCH_HEAD``. No
        leading ``+`` is used, so a non-fast-forward remote-tracking update is
        reported as a rejection rather than silently forced.

        Args:
            remote: A configured remote name. Defaults to ``origin``.
            branch: The branch to fetch. Must be a branch name, not a refspec
                or revision expression.
            recent: How many recent commits to report, between 1 and 50.

        Returns:
            An operation result whose ``data`` carries ``remote``, ``branch``,
            ``fetched_commit``, ``tracking_ref``, ``tracking_commit``,
            ``fresh`` and ``commits``. Status is ``uncertain`` when the
            remote-tracking ref does not match the fetched commit.
        """
        started = time.perf_counter()
        try:
            args = GitFetchArgs(remote=remote, branch=branch, recent=recent)
        except Exception as exc:  # pydantic ValidationError
            return self._error("git_fetch", "invalid_arguments", str(exc), started=started)

        layout = await self._discover("git_fetch", started)
        if isinstance(layout, OperationResult):
            return layout

        remotes, remote_step = await self._remote_names()
        try:
            safe_remote = self._validate_remote(args.remote, remotes)
        except ValueError as exc:
            return self._error("git_fetch", "unknown_remote", str(exc), steps=[remote_step], started=started)
        try:
            safe_branch = await self._validate_branch(args.branch)
        except ValueError as exc:
            return self._error("git_fetch", "invalid_branch", str(exc), started=started)

        tracking_ref = f"refs/remotes/{safe_remote}/{safe_branch}"
        refspec = f"refs/heads/{safe_branch}:{tracking_ref}"
        fetch_step, _ = await self._run_git(
            ["fetch", "--no-tags", "--no-recurse-submodules", "--end-of-options", safe_remote, refspec],
            timeout=self.policy.network_timeout_seconds,
        )
        fetch_step.state_changed = fetch_step.exit_code == 0
        fetch_step.name = "fetch"

        if fetch_step.timed_out:
            return self._error(
                "git_fetch",
                "fetch_timeout",
                "the fetch timed out",
                steps=[fetch_step],
                started=started,
                status="uncertain",
            )
        if fetch_step.exit_code != 0:
            # A fetch failure must not fall through to a history lookup.
            rejected = "rejected" in fetch_step.stderr or "non-fast-forward" in fetch_step.stderr
            return self._error(
                "git_fetch",
                "fetch_rejected" if rejected else "fetch_failed",
                "the fetch did not complete",
                details={"remote": safe_remote, "branch": safe_branch},
                steps=[fetch_step],
                started=started,
            )

        fetched_step, _ = await self._run_git(
            ["rev-parse", "--verify", "--quiet", "--end-of-options", "FETCH_HEAD^{commit}"]
        )
        fetched = fetched_step.stdout.strip()
        tracking_step, _ = await self._run_git(
            ["rev-parse", "--verify", "--quiet", "--end-of-options", f"{tracking_ref}^{{commit}}"]
        )
        tracking = tracking_step.stdout.strip()
        steps = [remote_step, fetch_step, fetched_step, tracking_step]

        if len(fetched) != 40:
            return self._error(
                "git_fetch", "fetch_head_unresolved", "could not read the fetched commit", steps=steps, started=started
            )

        fresh = bool(tracking) and tracking == fetched
        commits, log_step = await self._log_step(fetched, args.recent)
        steps.append(log_step)

        data: dict[str, Any] = {
            "remote": safe_remote,
            "branch": safe_branch,
            "fetched_commit": fetched,
            "tracking_ref": tracking_ref,
            "tracking_commit": tracking or None,
            "fresh": fresh,
            "commits": commits,
        }
        if not fresh:
            # Report the identity we actually fetched; never assume the
            # remote-tracking ref moved.
            result = self._error(
                "git_fetch",
                "tracking_ref_stale",
                "the remote-tracking ref does not match the fetched commit",
                details={"fetched_commit": fetched, "tracking_commit": tracking or None},
                steps=steps,
                started=started,
                status="uncertain",
            )
            result.data = data
            return result
        return self._ok("git_fetch", data, steps, started)

    @tool_schema(GitPreflightArgs)
    async def git_preflight(self) -> OperationResult:
        """Report working-tree status, whitespace errors and staged files.

        Every check runs independently, even when an earlier one fails, so a
        single report describes the whole state of the tree.

        Returns:
            An operation result whose ``data`` carries ``checks`` (per-check
            ``{ok, exit_code, detail}``), the parsed ``status`` summary and
            the ``staged`` file list. Status is ``error`` with code
            ``preflight_failed`` when any check failed.
        """
        started = time.perf_counter()
        layout = await self._discover("git_preflight", started)
        if isinstance(layout, OperationResult):
            return layout

        status_step, status_raw = await self._run_git(
            ["status", "--porcelain=v2", "-z", "--branch", "--untracked-files=normal"]
        )
        diff_step, _ = await self._run_git(["diff", "--check"])
        cached_step, _ = await self._run_git(["diff", "--cached", "--check"])
        staged_step, staged_raw = await self._run_git(["diff", "--cached", "--name-only", "-z"])

        status_step.name = "status"
        diff_step.name = "diff_check"
        cached_step.name = "cached_check"
        staged_step.name = "staged_names"

        summary = _parse_status_v2(status_raw) if status_step.exit_code == 0 else {}
        staged_names = _split_nul(staged_raw) if staged_step.exit_code == 0 else []

        checks = {
            "status": {
                "ok": status_step.exit_code == 0,
                "exit_code": status_step.exit_code,
                "detail": "" if status_step.exit_code == 0 else status_step.stderr[:512],
            },
            "diff_check": {
                "ok": diff_step.exit_code == 0,
                "exit_code": diff_step.exit_code,
                "detail": _bounded_lines(diff_step.stdout, 50),
            },
            "cached_check": {
                "ok": cached_step.exit_code == 0,
                "exit_code": cached_step.exit_code,
                "detail": _bounded_lines(cached_step.stdout, 50),
            },
            "staged_names": {
                "ok": staged_step.exit_code == 0,
                "exit_code": staged_step.exit_code,
                "detail": "" if staged_step.exit_code == 0 else staged_step.stderr[:512],
            },
        }

        steps = [status_step, diff_step, cached_step, staged_step]
        data: dict[str, Any] = {"checks": checks, "staged": staged_names[:50], **summary}
        failed = [name for name, check in checks.items() if not check["ok"]]
        if failed:
            result = self._error(
                "git_preflight",
                "preflight_failed",
                "one or more preflight checks failed",
                details={"failed": failed},
                steps=steps,
                started=started,
            )
            result.data = data
            return result
        return self._ok("git_preflight", data, steps, started)


# --------------------------------------------------------------------------- #
# Output parsing helpers (module level so _generate_tools never sees them)
# --------------------------------------------------------------------------- #
def _split_nul(raw: bytes) -> list[str]:
    """Split a NUL-delimited git ``-z`` stream into records.

    Args:
        raw: The raw stdout bytes.

    Returns:
        The non-empty records, decoded permissively.
    """
    return [item.decode("utf-8", "replace") for item in raw.split(b"\x00") if item]


def _bounded_lines(text: str, limit: int) -> str:
    """Return at most ``limit`` lines of ``text``.

    Args:
        text: The text to bound.
        limit: Maximum number of lines to keep.

    Returns:
        The retained lines joined by newlines.
    """
    lines = text.splitlines()
    return "\n".join(lines[:limit])


def _parse_status_v2(raw: bytes) -> dict[str, Any]:
    """Parse ``git status --porcelain=v2 -z --branch`` output.

    Args:
        raw: The raw NUL-delimited stdout bytes.

    Returns:
        A summary with branch identity, ahead/behind counts, per-category
        counts and up to 50 paths per category.
    """
    records = raw.split(b"\x00")
    branch: Optional[str] = None
    oid: Optional[str] = None
    upstream: Optional[str] = None
    ahead = behind = 0
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    unmerged: list[str] = []
    ignored: list[str] = []

    index = 0
    while index < len(records):
        record = records[index].decode("utf-8", "replace")
        index += 1
        if not record:
            continue
        if record.startswith("# "):
            key, _, value = record[2:].partition(" ")
            if key == "branch.oid":
                oid = value
            elif key == "branch.head":
                branch = value
            elif key == "branch.upstream":
                upstream = value
            elif key == "branch.ab":
                for token in value.split():
                    if token.startswith("+"):
                        ahead = int(token[1:] or 0)
                    elif token.startswith("-"):
                        behind = int(token[1:] or 0)
            continue

        kind = record[0]
        if kind in ("1", "2"):
            fields = record.split(" ", 8) if kind == "1" else record.split(" ", 9)
            xy = fields[1]
            path = fields[-1]
            if kind == "2" and index < len(records):
                # A rename entry is followed by its original path record.
                index += 1
            if xy[0] != ".":
                staged.append(path)
            if len(xy) > 1 and xy[1] != ".":
                unstaged.append(path)
        elif kind == "u":
            unmerged.append(record.split(" ", 10)[-1])
        elif kind == "?":
            untracked.append(record[2:])
        elif kind == "!":
            ignored.append(record[2:])

    return {
        "branch": None if branch in (None, "(detached)") else branch,
        "detached": branch == "(detached)",
        "unborn": oid == "(initial)",
        "head_commit": None if oid in (None, "(initial)") else oid,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "counts": {
            "staged": len(staged),
            "unstaged": len(unstaged),
            "untracked": len(untracked),
            "unmerged": len(unmerged),
            "ignored": len(ignored),
        },
        "paths": {
            "staged": staged[:50],
            "unstaged": unstaged[:50],
            "untracked": untracked[:50],
            "unmerged": unmerged[:50],
        },
    }
