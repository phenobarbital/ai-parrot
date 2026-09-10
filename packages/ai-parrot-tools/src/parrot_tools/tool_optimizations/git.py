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
import contextlib
import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from parrot.tools.decorators import tool_schema
from parrot.tools.repo.confinement import PathOutsideRootError, SecretFileError
from parrot.tools.repo.git_tools import LOG_FORMAT, InvalidRefError, parse_log, validate_ref
from pydantic import BaseModel, ConfigDict

from .base import OptimizationToolkitBase
from .models import (
    GitFetchArgs,
    GitPrepareFilesArgs,
    GitPreflightArgs,
    GitPullArgs,
    GitPushArgs,
    GitRecentArgs,
    OperationResult,
    StepResult,
)
from .policy import LockTimeoutError, SymlinkRejectedError, WorktreeLock, resolve_operand

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
        "git_prepare_files": GitPrepareFilesArgs,
        "git_pull": GitPullArgs,
        "git_push": GitPushArgs,
    }

    #: Mutating tools. The MCP adapter injects a required ``confirm`` boolean
    #: for these and rejects the call unless it is true. ``confirm`` is the
    #: host-side record that a human approved the operation — it is never
    #: authorization a model can grant itself (spec Git Contract 12).
    confirming_tools: frozenset = frozenset({"git_prepare_files", "git_pull", "git_push"})

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

    # ----------------------------------------------------------------- #
    # Staging helpers
    # ----------------------------------------------------------------- #
    def _normalise_literal_paths(
        self, paths: Sequence[str]
    ) -> tuple[list[str], Optional[tuple[str, str, dict[str, Any]]]]:
        """Validate caller paths as literal, in-root, non-magic file paths.

        Pathspec magic, globs, directories, symlinks and traversal are all
        rejected here — before any Git process runs — so a refusal can never
        have touched the repository.

        Args:
            paths: The caller-supplied paths.

        Returns:
            A ``(relative_paths, error)`` tuple, where ``error`` is
            ``(code, message, details)`` or None.
        """
        seen: list[str] = []
        for raw in paths:
            candidate = raw
            if not candidate or candidate != candidate.strip():
                return [], ("invalid_path", f"{raw!r} is empty or padded with whitespace", {"path": raw})
            if candidate.startswith(":"):
                return [], ("pathspec_magic", f"{raw!r} uses git pathspec magic", {"path": raw})
            if any(char in candidate for char in "*?[]"):
                return [], ("glob_rejected", f"{raw!r} looks like a glob; pass literal paths", {"path": raw})
            if "\\" in candidate:
                return [], ("invalid_path", f"{raw!r} contains a backslash", {"path": raw})
            if candidate.endswith("/"):
                return [], ("invalid_path", f"{raw!r} has a trailing slash", {"path": raw})
            if Path(candidate).is_absolute():
                return [], ("invalid_path", f"{raw!r} must be repository-relative", {"path": raw})
            segments = candidate.split("/")
            if any(segment in ("", ".", "..") for segment in segments):
                return [], ("invalid_path", f"{raw!r} contains an empty or traversal segment", {"path": raw})

            try:
                target = resolve_operand(self.policy, candidate, must_exist=False)
            except SymlinkRejectedError as exc:
                return [], ("symlink_rejected", str(exc), {"path": raw})
            except SecretFileError as exc:
                return [], ("secret_file", str(exc), {"path": raw})
            except PathOutsideRootError as exc:
                return [], ("path_outside_root", str(exc), {"path": raw})
            except ValueError as exc:
                return [], ("invalid_path", str(exc), {"path": raw})

            if target.is_dir():
                return [], ("directory_rejected", f"{raw!r} is a directory; pass individual files", {"path": raw})
            if target.is_symlink():
                return [], ("symlink_rejected", f"{raw!r} is a symlink", {"path": raw})

            relative = target.relative_to(self.policy.repo_root).as_posix()
            if relative in seen:
                return [], ("duplicate_path", f"{relative!r} was supplied more than once", {"path": relative})
            seen.append(relative)
        return seen, None

    @staticmethod
    def _fingerprint(index_path: Path) -> Optional[tuple[int, int, str]]:
        """Fingerprint the index file so a concurrent change is detectable.

        Args:
            index_path: The per-worktree index path.

        Returns:
            A ``(size, mtime_ns, sha256)`` tuple, or None when the index does
            not exist yet (a repository with an unborn HEAD).
        """
        try:
            stat_result = index_path.stat()
        except FileNotFoundError:
            return None
        digest = hashlib.sha256()
        with open(index_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return (stat_result.st_size, stat_result.st_mtime_ns, digest.hexdigest())

    async def _index_features_supported(self) -> tuple[bool, list[StepResult]]:
        """Check that the index is a plain, fully readable index file.

        A split or sparse index cannot be safely copied and republished as a
        whole file, so those configurations are refused rather than corrupted.

        Returns:
            A ``(supported, steps)`` tuple.
        """
        steps: list[StepResult] = []
        for key in ("core.splitIndex", "index.sparse"):
            step, _ = await self._run_git(["config", "--get", key])
            step.name = f"config {key}"
            steps.append(step)
            if step.exit_code == 0 and step.stdout.strip().lower() == "true":
                return False, steps
        return True, steps

    # ----------------------------------------------------------------- #
    # Mutating tools
    # ----------------------------------------------------------------- #
    @tool_schema(GitPrepareFilesArgs)
    async def git_prepare_files(self, paths: list[str]) -> OperationResult:
        """Stage exactly the listed files, refusing to disturb unrelated staging.

        Staging happens in a private copy of the index; the copy is published
        only after every check passes, the real index is byte-identical to
        what it was at the start, and Git's own ``index.lock`` was acquired.
        A refusal or a failed check therefore leaves the index and the working
        files untouched. Unrelated already-staged paths cause a refusal — this
        operation never unstages anything.

        The ``confirm`` argument added over MCP records that a human approved
        this mutation; it is not authorization a model can grant itself.

        Args:
            paths: Literal, repository-relative file paths. Tracked files that
                have been deleted on disk are staged as removals.

        Returns:
            An operation result whose ``data`` carries the exact ``staged``
            names, any ``deleted`` ones, ``whitespace_ok`` and
            ``index_published``.
        """
        started = time.perf_counter()
        operation = "git_prepare_files"
        try:
            args = GitPrepareFilesArgs(paths=paths)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        layout = await self._discover(operation, started)
        if isinstance(layout, OperationResult):
            return layout

        selected, path_error = self._normalise_literal_paths(args.paths)
        if path_error is not None:
            code, message, details = path_error
            return self._error(operation, code, message, details=details, started=started)

        try:
            async with WorktreeLock(layout.lock_path, self.policy.command_timeout_seconds):
                return await self._prepare_locked(layout, selected, started)
        except LockTimeoutError as exc:
            return self._error(operation, "worktree_busy", str(exc), started=started)

    async def _prepare_locked(self, layout: RepoLayout, selected: list[str], started: float) -> OperationResult:
        """Run the staging transaction while holding the worktree lock.

        Args:
            layout: The discovered repository layout.
            selected: Validated repo-relative paths.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded operation result.
        """
        operation = "git_prepare_files"
        steps: list[StepResult] = []

        # --- Per-path git-level checks (submodule / tracked-deletion) ------
        ls_step, ls_raw = await self._run_git(["ls-files", "-s", "-z", "--", *selected])
        ls_step.name = "ls-files"
        steps.append(ls_step)
        if ls_step.exit_code != 0:
            return self._error(
                operation, "ls_files_failed", "could not read index entries", steps=steps, started=started
            )
        for record in _split_nul(ls_raw):
            mode, _, remainder = record.partition(" ")
            if mode == "160000":
                path = remainder.split("\t", 1)[-1]
                return self._error(
                    operation,
                    "submodule_rejected",
                    f"{path!r} is a submodule",
                    details={"path": path},
                    steps=steps,
                    started=started,
                )

        deleted: list[str] = []
        for relative in selected:
            absolute = self.policy.repo_root / relative
            if absolute.exists():
                continue
            tracked_step, _ = await self._run_git(["ls-files", "--error-unmatch", "-z", "--", relative])
            tracked_step.name = "ls-files --error-unmatch"
            steps.append(tracked_step)
            if tracked_step.exit_code != 0:
                return self._error(
                    operation,
                    "path_not_found",
                    f"{relative!r} does not exist and is not tracked",
                    details={"path": relative},
                    steps=steps,
                    started=started,
                )
            deleted.append(relative)

        # --- Index-state pre-checks ---------------------------------------
        unmerged_step, unmerged_raw = await self._run_git(["ls-files", "-u", "-z"])
        unmerged_step.name = "ls-files -u"
        steps.append(unmerged_step)
        if unmerged_step.exit_code != 0 or _split_nul(unmerged_raw):
            return self._error(
                operation,
                "unmerged_index",
                "the index has unmerged entries; resolve the conflict first",
                steps=steps,
                started=started,
            )

        staged_step, staged_raw = await self._run_git(["diff", "--cached", "--name-only", "-z"])
        staged_step.name = "diff --cached --name-only"
        steps.append(staged_step)
        unstaged_step, unstaged_raw = await self._run_git(["diff", "--name-only", "-z"])
        unstaged_step.name = "diff --name-only"
        steps.append(unstaged_step)
        if staged_step.exit_code != 0 or unstaged_step.exit_code != 0:
            return self._error(
                operation, "status_failed", "could not read the current staging state", steps=steps, started=started
            )

        staged_now = set(_split_nul(staged_raw))
        unstaged_now = set(_split_nul(unstaged_raw))
        chosen = set(selected)

        unrelated = sorted(staged_now - chosen)
        if unrelated:
            return self._error(
                operation,
                "unrelated_staged",
                "unrelated paths are already staged; this operation never unstages",
                details={"unrelated": unrelated[:50]},
                steps=steps,
                started=started,
            )
        partial = sorted(chosen & staged_now & unstaged_now)
        if partial:
            return self._error(
                operation,
                "partially_staged",
                "selected paths have partially staged content that whole-file staging would replace",
                details={"partial": partial[:50]},
                steps=steps,
                started=started,
            )

        supported, config_steps = await self._index_features_supported()
        steps.extend(config_steps)
        if not supported:
            return self._error(
                operation,
                "index_unsupported",
                "split or sparse index is not supported by this operation",
                steps=steps,
                started=started,
            )

        # --- Transaction ---------------------------------------------------
        fingerprint_before = self._fingerprint(layout.index_path)
        handle = tempfile.NamedTemporaryFile(dir=layout.git_dir, prefix="parrot-index-", delete=False)
        handle.close()
        temp_index = Path(handle.name)
        try:
            if layout.index_path.exists():
                # copy2, NOT copyfile: git decides an index entry is "racily
                # clean" by comparing the entry's mtime against the *index
                # file's* mtime, and re-hashes the file when it is. A copy
                # with a fresh mtime silently turns those entries into
                # trusted-clean ones, so a same-size edit made within the
                # same clock tick as the last `git add` would not be staged
                # (measured: ~3% of same-size edits). Preserving the index's
                # mtime makes the private copy behave exactly like the real
                # index.
                shutil.copy2(layout.index_path, temp_index)
            env = {"GIT_INDEX_FILE": str(temp_index.resolve())}

            # NOTE: `--end-of-options` must NOT be combined with `--` here —
            # git would then read `--` as a literal pathspec and fail. The
            # `--` separator alone already protects an option-shaped path.
            add_step, _ = await self._run_git(["add", "--", *selected], extra_env=env)
            add_step.name = "add"
            steps.append(add_step)
            if add_step.exit_code != 0:
                return self._error(
                    operation, "add_failed", "git add rejected the selection", steps=steps, started=started
                )

            verify_step, verify_raw = await self._run_git(["diff", "--cached", "--name-only", "-z"], extra_env=env)
            verify_step.name = "verify staged names"
            steps.append(verify_step)
            staged_after = sorted(_split_nul(verify_raw))
            if verify_step.exit_code != 0 or staged_after != sorted(chosen):
                return self._error(
                    operation,
                    "staged_mismatch",
                    "the prepared index does not contain exactly the selected paths",
                    details={"expected": sorted(chosen)[:50], "actual": staged_after[:50]},
                    steps=steps,
                    started=started,
                )

            check_step, _ = await self._run_git(["diff", "--cached", "--check"], extra_env=env)
            check_step.name = "verify whitespace"
            steps.append(check_step)
            if check_step.exit_code != 0:
                return self._error(
                    operation,
                    "whitespace_errors",
                    "the selection introduces whitespace errors",
                    details={"lines": _bounded_lines(check_step.stdout, 50)},
                    steps=steps,
                    started=started,
                )

            if self._fingerprint(layout.index_path) != fingerprint_before:
                return self._error(
                    operation,
                    "index_changed",
                    "the index changed while it was being prepared",
                    steps=steps,
                    started=started,
                )

            publish_step = self._publish_index(layout, temp_index)
            steps.append(publish_step)
            if publish_step.exit_code != 0:
                code = "index_locked" if publish_step.stderr.startswith("index_locked") else "publish_failed"
                return self._error(
                    operation, code, publish_step.stderr or "could not publish the index", steps=steps, started=started
                )
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_index)

        data = {
            "staged": sorted(chosen),
            "deleted": sorted(deleted),
            "whitespace_ok": True,
            "index_published": True,
        }
        return self._ok(operation, data, steps, started)

    def _publish_index(self, layout: RepoLayout, temp_index: Path) -> StepResult:
        """Publish the prepared index through Git's own ``index.lock``.

        This is exactly how Git itself commits an index: write the new
        content into ``index.lock`` and atomically rename it over ``index``.
        A pre-existing lock belongs to another Git process and is never
        removed.

        Args:
            layout: The discovered repository layout.
            temp_index: The prepared private index file.

        Returns:
            A step describing the publish attempt. ``exit_code`` 0 means the
            index was replaced.
        """
        lock_path = layout.index_path.with_name("index.lock")
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return StepResult(
                name="publish index",
                exit_code=1,
                timed_out=False,
                state_changed=False,
                stderr="index_locked: another git process holds the index lock",
            )
        try:
            with os.fdopen(fd, "wb") as destination, open(temp_index, "rb") as source:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(lock_path, layout.index_path)
        except BaseException as exc:  # noqa: BLE001 — cleanup then report
            with contextlib.suppress(FileNotFoundError):
                os.unlink(lock_path)
            return StepResult(
                name="publish index",
                exit_code=1,
                timed_out=False,
                state_changed=False,
                stderr=f"publish failed: {exc}"[:4096],
            )
        return StepResult(name="publish index", exit_code=0, timed_out=False, state_changed=True)

    # ----------------------------------------------------------------- #
    # Publication
    # ----------------------------------------------------------------- #
    async def _status_summary(self) -> tuple[dict[str, Any], StepResult]:
        """Read and parse the porcelain-v2 status with branch headers.

        Returns:
            A ``(summary, step)`` tuple; ``summary`` is empty when the
            command failed.
        """
        step, raw = await self._run_git(["status", "--porcelain=v2", "-z", "--branch", "--untracked-files=normal"])
        step.name = "status"
        return (_parse_status_v2(raw) if step.exit_code == 0 else {}), step

    async def _resolve_publication_branch(
        self,
        operation: str,
        summary: dict[str, Any],
        remote: str,
        branch: Optional[str],
        steps: list[StepResult],
        started: float,
    ) -> tuple[Optional[str], Optional[OperationResult]]:
        """Resolve which branch a pull/push acts on, refusing unsafe states.

        Args:
            operation: The calling operation name.
            summary: The parsed status summary.
            remote: The validated remote name.
            branch: The caller-supplied branch, or None to use the upstream.
            steps: Steps recorded so far, for the error result.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            A ``(branch, error_result)`` tuple; exactly one is not None.
        """
        if summary.get("detached"):
            return None, self._error(operation, "detached_head", "HEAD is detached", steps=steps, started=started)
        if summary.get("unborn"):
            return None, self._error(
                operation, "unborn_head", "the current branch has no commits yet", steps=steps, started=started
            )

        current = summary.get("branch")
        if not current:
            return None, self._error(
                operation, "unknown_branch", "could not determine the current branch", steps=steps, started=started
            )

        if branch is None:
            upstream = summary.get("upstream")
            if not upstream:
                return None, self._error(
                    operation,
                    "missing_upstream",
                    f"branch {current!r} has no upstream; pass an explicit branch",
                    steps=steps,
                    started=started,
                )
            upstream_remote, _, upstream_branch = upstream.partition("/")
            if upstream_remote != remote:
                return None, self._error(
                    operation,
                    "upstream_remote_mismatch",
                    f"upstream {upstream!r} does not belong to remote {remote!r}",
                    details={"upstream": upstream, "remote": remote},
                    steps=steps,
                    started=started,
                )
            return upstream_branch or current, None

        if branch != current:
            return None, self._error(
                operation,
                "branch_mismatch",
                f"requested branch {branch!r} is not the current branch {current!r}",
                details={"requested": branch, "current": current},
                steps=steps,
                started=started,
            )
        return branch, None

    async def _fetch_branch(self, remote: str, branch: str) -> tuple[Optional[str], StepResult]:
        """Fetch one branch with an explicit, non-forced destination refspec.

        Args:
            remote: A validated remote name.
            branch: A validated branch name.

        Returns:
            A ``(fetched_sha_or_None, step)`` tuple.
        """
        refspec = f"refs/heads/{branch}:refs/remotes/{remote}/{branch}"
        step, _ = await self._run_git(
            ["fetch", "--no-tags", "--no-recurse-submodules", "--end-of-options", remote, refspec],
            timeout=self.policy.network_timeout_seconds,
        )
        step.name = "fetch"
        step.state_changed = step.exit_code == 0
        if step.exit_code != 0:
            return None, step
        head_step, _ = await self._run_git(
            ["rev-parse", "--verify", "--quiet", "--end-of-options", "FETCH_HEAD^{commit}"]
        )
        sha = head_step.stdout.strip()
        return (sha if len(sha) == 40 else None), step

    @tool_schema(GitPullArgs)
    async def git_pull(self, remote: str = "origin", branch: Optional[str] = None) -> OperationResult:
        """Fast-forward the current branch from its remote, or refuse.

        Only a fast-forward is ever performed: there is no stash, no rebase
        and no merge commit. A dirty or partially staged tree, a detached or
        unborn HEAD, or a diverged history all cause a refusal that changes
        nothing. Untracked files are preserved — Git itself refuses a
        fast-forward that would overwrite one.

        The ``confirm`` argument added over MCP records that a human approved
        this mutation; it is not authorization a model can grant itself.

        Args:
            remote: A configured remote name. Defaults to ``origin``.
            branch: The branch to pull. Defaults to the current branch's
                upstream, and must equal the current branch when supplied.

        Returns:
            An operation result whose ``data`` carries ``branch``, ``remote``,
            ``before``, ``after`` and ``updated``.
        """
        started = time.perf_counter()
        operation = "git_pull"
        try:
            args = GitPullArgs(remote=remote, branch=branch)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        layout = await self._discover(operation, started)
        if isinstance(layout, OperationResult):
            return layout

        try:
            async with WorktreeLock(layout.lock_path, self.policy.command_timeout_seconds):
                return await self._pull_locked(operation, args, started)
        except LockTimeoutError as exc:
            return self._error(operation, "worktree_busy", str(exc), started=started)

    async def _pull_locked(self, operation: str, args: GitPullArgs, started: float) -> OperationResult:
        """Perform the fast-forward-only pull while holding the worktree lock.

        Args:
            operation: The operation name.
            args: The validated arguments.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded operation result.
        """
        remotes, remote_step = await self._remote_names()
        steps: list[StepResult] = [remote_step]
        try:
            safe_remote = self._validate_remote(args.remote, remotes)
        except ValueError as exc:
            return self._error(operation, "unknown_remote", str(exc), steps=steps, started=started)

        summary, status_step = await self._status_summary()
        steps.append(status_step)
        if status_step.exit_code != 0:
            return self._error(
                operation, "status_failed", "could not read the working tree state", steps=steps, started=started
            )

        counts = summary.get("counts", {})
        if counts.get("unmerged"):
            return self._error(
                operation, "unmerged_index", "the index has unmerged entries", steps=steps, started=started
            )
        if counts.get("staged"):
            return self._error(
                operation,
                "staged_changes",
                "the index has staged changes; publish or reset them yourself",
                steps=steps,
                started=started,
            )
        if counts.get("unstaged"):
            return self._error(
                operation,
                "dirty_worktree",
                "tracked files have uncommitted modifications",
                steps=steps,
                started=started,
            )

        branch, error = await self._resolve_publication_branch(
            operation, summary, safe_remote, args.branch, steps, started
        )
        if error is not None:
            return error
        try:
            safe_branch = await self._validate_branch(branch or "")
        except ValueError as exc:
            return self._error(operation, "invalid_branch", str(exc), steps=steps, started=started)

        before = summary.get("head_commit")
        fetched, fetch_step = await self._fetch_branch(safe_remote, safe_branch)
        steps.append(fetch_step)
        if fetch_step.timed_out:
            return self._error(
                operation, "fetch_timeout", "the fetch timed out", steps=steps, started=started, status="uncertain"
            )
        if fetch_step.exit_code != 0:
            rejected = "rejected" in fetch_step.stderr or "non-fast-forward" in fetch_step.stderr
            return self._error(
                operation,
                "fetch_rejected" if rejected else "fetch_failed",
                "the fetch did not complete",
                steps=steps,
                started=started,
            )
        if fetched is None:
            return self._error(
                operation, "fetch_head_unresolved", "could not read the fetched commit", steps=steps, started=started
            )

        up_to_date_step, _ = await self._run_git(["merge-base", "--is-ancestor", "--end-of-options", fetched, "HEAD"])
        up_to_date_step.name = "merge-base"
        steps.append(up_to_date_step)
        if up_to_date_step.exit_code == 0:
            data = {"branch": safe_branch, "remote": safe_remote, "before": before, "after": before, "updated": False}
            return self._ok(operation, data, steps, started)

        ancestor_step, _ = await self._run_git(["merge-base", "--is-ancestor", "--end-of-options", "HEAD", fetched])
        ancestor_step.name = "merge-base"
        steps.append(ancestor_step)
        if ancestor_step.exit_code != 0:
            count_step, _ = await self._run_git(
                ["rev-list", "--left-right", "--count", "--end-of-options", f"HEAD...{fetched}"]
            )
            count_step.name = "rev-list"
            steps.append(count_step)
            ahead_behind = count_step.stdout.split()
            return self._error(
                operation,
                "diverged",
                "the local branch and the remote branch have diverged",
                details={
                    "local": before,
                    "remote": fetched,
                    "ahead": int(ahead_behind[0]) if len(ahead_behind) == 2 else None,
                    "behind": int(ahead_behind[1]) if len(ahead_behind) == 2 else None,
                },
                steps=steps,
                started=started,
            )

        merge_step, _ = await self._run_git(
            ["-c", "merge.autoStash=false", "merge", "--ff-only", "--no-autostash", "--end-of-options", fetched]
        )
        merge_step.name = "merge --ff-only"
        steps.append(merge_step)
        if merge_step.exit_code != 0:
            untracked = (
                "untracked working tree files" in merge_step.stderr or "would be overwritten" in merge_step.stderr
            )
            return self._error(
                operation,
                "untracked_conflict" if untracked else "fast_forward_failed",
                "the fast-forward did not complete; nothing was changed",
                details={"stderr": merge_step.stderr[:1024]},
                steps=steps,
                started=started,
            )
        merge_step.state_changed = True
        data = {"branch": safe_branch, "remote": safe_remote, "before": before, "after": fetched, "updated": True}
        return self._ok(operation, data, steps, started)

    @tool_schema(GitPushArgs)
    async def git_push(self, remote: str = "origin", branch: Optional[str] = None) -> OperationResult:
        """Push the current branch to the same branch name on a remote.

        The push is never forced, never pushes all refs and never creates a
        commit. A rejection is reported with the remote's reason. If the push
        times out after transmission its outcome is genuinely unknown, so the
        result is ``uncertain`` and a single read-only ``ls-remote`` is used
        to resolve it — the push is never blindly retried.

        The ``confirm`` argument added over MCP records that a human approved
        this mutation; it is not authorization a model can grant itself.

        Args:
            remote: A configured remote name. Defaults to ``origin``.
            branch: The branch to push. Defaults to the current branch, and
                must equal it when supplied.

        Returns:
            An operation result whose ``data`` carries ``branch``, ``remote``,
            ``local_commit``, ``remote_commit_before``, ``remote_commit_after``
            and ``summary``.
        """
        started = time.perf_counter()
        operation = "git_push"
        try:
            args = GitPushArgs(remote=remote, branch=branch)
        except Exception as exc:  # pydantic ValidationError
            return self._error(operation, "invalid_arguments", str(exc), started=started)

        layout = await self._discover(operation, started)
        if isinstance(layout, OperationResult):
            return layout

        try:
            async with WorktreeLock(layout.lock_path, self.policy.command_timeout_seconds):
                return await self._push_locked(operation, args, started)
        except LockTimeoutError as exc:
            return self._error(operation, "worktree_busy", str(exc), started=started)

    async def _push_locked(self, operation: str, args: GitPushArgs, started: float) -> OperationResult:
        """Perform the non-forced push while holding the worktree lock.

        Args:
            operation: The operation name.
            args: The validated arguments.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            The bounded operation result.
        """
        remotes, remote_step = await self._remote_names()
        steps: list[StepResult] = [remote_step]
        try:
            safe_remote = self._validate_remote(args.remote, remotes)
        except ValueError as exc:
            return self._error(operation, "unknown_remote", str(exc), steps=steps, started=started)

        summary, status_step = await self._status_summary()
        steps.append(status_step)
        if status_step.exit_code != 0:
            return self._error(
                operation, "status_failed", "could not read the working tree state", steps=steps, started=started
            )

        branch, error = await self._resolve_publication_branch(
            operation, summary, safe_remote, args.branch, steps, started
        )
        if error is not None:
            return error
        try:
            safe_branch = await self._validate_branch(branch or "")
        except ValueError as exc:
            return self._error(operation, "invalid_branch", str(exc), steps=steps, started=started)

        local_commit = summary.get("head_commit")
        refspec = f"refs/heads/{safe_branch}:refs/heads/{safe_branch}"
        push_step, _ = await self._run_git(
            ["push", "--porcelain", "--no-force-with-lease", "--end-of-options", safe_remote, refspec],
            timeout=self.policy.network_timeout_seconds,
        )
        push_step.name = "push"
        steps.append(push_step)

        data: dict[str, Any] = {
            "branch": safe_branch,
            "remote": safe_remote,
            "local_commit": local_commit,
            "remote_commit_before": None,
            "remote_commit_after": None,
            "summary": "",
        }

        if push_step.timed_out:
            return await self._resolve_push_timeout(
                operation, safe_remote, safe_branch, local_commit, data, steps, started
            )

        flag, refs, message = _parse_push_porcelain(push_step.stdout)
        data["summary"] = message
        before, _abbreviated_after = _parse_push_range(message)
        # Git reports abbreviated shas in the porcelain range. On a successful
        # non-forced push of <b>:<b> the remote ref is exactly our local
        # commit, so report that full identity rather than the abbreviation.
        data["remote_commit_before"] = before
        if push_step.exit_code == 0 and flag in (" ", "*", "="):
            data["remote_commit_after"] = local_commit

        if push_step.exit_code != 0 or flag == "!":
            return self._error(
                operation,
                "push_rejected",
                "the remote rejected the push",
                details={"summary": message, "refs": refs, "stderr": push_step.stderr[:1024]},
                steps=steps,
                started=started,
            )
        if flag in ("-", "+"):
            # A deletion or a forced update must never come out of this tool.
            return self._error(
                operation,
                "unexpected_push_effect",
                f"the push reported an unexpected effect ({flag!r})",
                details={"summary": message},
                steps=steps,
                started=started,
            )
        push_step.state_changed = flag != "="
        return self._ok(operation, data, steps, started)

    async def _resolve_push_timeout(
        self,
        operation: str,
        remote: str,
        branch: str,
        local_commit: Optional[str],
        data: dict[str, Any],
        steps: list[StepResult],
        started: float,
    ) -> OperationResult:
        """Resolve a push whose outcome is unknown, without retrying it.

        A timeout after transmission may or may not have updated the remote.
        Exactly one read-only ``ls-remote`` is used to find out; anything
        else leaves the result ``uncertain``.

        Args:
            operation: The operation name.
            remote: The validated remote name.
            branch: The validated branch name.
            local_commit: The local HEAD commit.
            data: The partially built result payload.
            steps: Steps recorded so far.
            started: A ``perf_counter()`` reading taken at operation start.

        Returns:
            An ``ok`` result when the remote demonstrably matches the local
            commit, otherwise an ``uncertain`` one.
        """
        probe_step, _ = await self._run_git(
            ["ls-remote", "--heads", "--end-of-options", remote, f"refs/heads/{branch}"],
            timeout=self.policy.network_timeout_seconds,
        )
        probe_step.name = "ls-remote"
        steps.append(probe_step)
        remote_sha = probe_step.stdout.split("\t")[0].strip() if probe_step.exit_code == 0 else ""

        if remote_sha and local_commit and remote_sha == local_commit:
            data["remote_commit_after"] = remote_sha
            data["summary"] = "resolved after timeout"
            data["resolved_after_timeout"] = True
            return self._ok(operation, data, steps, started)

        result = self._error(
            operation,
            "push_timeout",
            "the push timed out; the remote state could not be confirmed",
            details={"remote_commit": remote_sha or None, "local_commit": local_commit},
            steps=steps,
            started=started,
            status="uncertain",
        )
        data["remote_commit_after"] = remote_sha or None
        data["resolved_after_timeout"] = False
        result.data = data
        return result


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


def _parse_push_porcelain(stdout: str) -> tuple[str, str, str]:
    """Parse ``git push --porcelain`` output into flag, refs and summary.

    Args:
        stdout: The raw porcelain stdout.

    Returns:
        A ``(flag, refs, summary)`` tuple; empty strings when no ref line was
        emitted.
    """
    for line in stdout.splitlines():
        if not line or line.startswith("To ") or line.startswith("Done"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        flag = parts[0][:1] or " "
        refs = parts[1]
        summary = parts[2] if len(parts) > 2 else ""
        return flag, refs, summary
    return "", "", ""


def _parse_push_range(summary: str) -> tuple[Optional[str], Optional[str]]:
    """Extract ``<old>..<new>`` commit identities from a push summary.

    Args:
        summary: The porcelain summary field.

    Returns:
        An ``(old, new)`` tuple; ``(None, None)`` when the summary is not a
        commit range (e.g. ``[new branch]`` or ``[rejected]``).
    """
    match = re.match(r"^([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})$", summary.strip())
    if match is None:
        return None, None
    return match.group(1), match.group(2)
