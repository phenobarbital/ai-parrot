"""Operation policy, result budget, path checks and worktree lock (FEAT-543).

This module owns the *deterministic* safety layer shared by the three
tool-optimizations toolkits:

* :class:`OptimizationPolicy` — the configured limits (line/byte thresholds,
  serialized result budget, subprocess timeouts).
* Byte-budget helpers — :func:`compact_json`, :func:`measure_json_bytes` and
  :func:`fit_to_budget`, which shrink *content* and re-serialize rather than
  slicing JSON text into something unparseable.
* Path policy — :func:`resolve_operand` composes the existing confinement
  helpers (containment + secret deny-list) with a new symlink-component
  rejection pass.
* :class:`WorktreeLock` — a cross-process advisory ``fcntl.flock`` used to
  serialize cooperating mutations per worktree.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Optional

from parrot.tools.repo.confinement import (
    PathOutsideRootError,
    resolve_readable_path,
    resolve_within_root,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import OperationError, OperationResult

__all__ = (
    "MIN_RESULT_BYTES",
    "PolicyError",
    "SymlinkRejectedError",
    "LockTimeoutError",
    "BudgetError",
    "OptimizationPolicy",
    "compact_json",
    "measure_json_bytes",
    "fit_to_budget",
    "relative_posix",
    "check_no_symlink_components",
    "resolve_operand",
    "WorktreeLock",
)

#: The smallest configurable serialized result budget, so errors stay useful.
MIN_RESULT_BYTES = 4096


class PolicyError(ValueError):
    """Base class for every policy violation raised by this module."""


class SymlinkRejectedError(PolicyError):
    """Raised when a path traverses a symlinked component below the root."""


class LockTimeoutError(PolicyError):
    """Raised when a :class:`WorktreeLock` could not be acquired in time."""


class BudgetError(PolicyError):
    """Raised when a configured byte budget is unusable."""


class OptimizationPolicy(BaseModel):
    """Configured limits shared by every tool-optimizations toolkit.

    Attributes:
        repo_root: The repository checkout every operand is confined to.
            Resolved at construction; must be an existing directory.
        max_lines: Line threshold above which a read requires explicit ranges.
        large_file_bytes: Byte threshold above which a read requires ranges.
        max_result_bytes: Budget applied to the serialized domain result.
        command_timeout_seconds: Timeout for a local subprocess.
        network_timeout_seconds: Timeout for a network-bound subprocess.
        deny_secret_files: When True, the existing secret deny-list applies.
    """

    model_config = ConfigDict(extra="forbid")

    repo_root: Path
    max_lines: int = Field(default=350, ge=1)
    large_file_bytes: int = Field(default=64_000, ge=1)
    max_result_bytes: int = Field(default=64_000, ge=MIN_RESULT_BYTES)
    command_timeout_seconds: float = Field(default=30.0, gt=0)
    network_timeout_seconds: float = Field(default=120.0, gt=0)
    deny_secret_files: bool = True

    @field_validator("repo_root")
    @classmethod
    def _resolve_root(cls, value: Path) -> Path:
        """Resolve the root and require an existing directory."""
        resolved = Path(value).resolve()
        if not resolved.is_dir():
            raise ValueError(f"repo_root {str(value)!r} is not an existing directory")
        return resolved


# --------------------------------------------------------------------------- #
# Byte budget
# --------------------------------------------------------------------------- #
def compact_json(obj: Any) -> str:
    """Serialize ``obj`` with the canonical compact encoding.

    This exact encoding defines what ``max_result_bytes`` measures: the UTF-8
    encoding of the compact JSON domain result, including metadata and
    escaped content, before any MCP transport wrapping.

    Args:
        obj: Any JSON-compatible object.

    Returns:
        The compact JSON text.
    """
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def measure_json_bytes(obj: Any) -> int:
    """Return the UTF-8 byte length of :func:`compact_json` for ``obj``.

    Args:
        obj: Any JSON-compatible object.

    Returns:
        The measured byte count.
    """
    return len(compact_json(obj).encode("utf-8"))


def _drop_trailing_lines(text: str) -> str:
    """Drop roughly the last half of ``text``'s lines, keeping whole lines.

    Args:
        text: The text to shrink.

    Returns:
        The retained prefix; ``""`` when nothing can be kept.
    """
    if not text:
        return ""
    lines = text.splitlines()
    keep = len(lines) // 2
    if keep <= 0:
        return ""
    return "\n".join(lines[:keep])


def _fits(result: OperationResult, budget: int) -> bool:
    """True when ``result`` serializes within ``budget`` bytes."""
    return measure_json_bytes(result.model_dump(mode="json")) <= budget


def fit_to_budget(result: OperationResult, budget: int) -> OperationResult:
    """Shrink ``result`` until its serialized form fits ``budget`` bytes.

    Content is reduced and re-serialized; JSON text is never sliced, so the
    returned object always parses. The reduction order is deliberate — step
    diagnostics first, then payload records, then the payload as a whole, so
    that status/error identity survives to the very last stage.

    Args:
        result: The domain result to bound.
        budget: The serialized byte budget (at least :data:`MIN_RESULT_BYTES`).

    Returns:
        A result whose ``model_dump(mode="json")`` measures at most ``budget``
        bytes. ``truncated`` is set whenever anything was dropped.

    Raises:
        BudgetError: ``budget`` is below :data:`MIN_RESULT_BYTES`.
    """
    if budget < MIN_RESULT_BYTES:
        raise BudgetError(f"result budget {budget} is below the minimum {MIN_RESULT_BYTES}")
    if _fits(result, budget):
        return result

    working = result.model_copy(deep=True)
    working.truncated = True

    # Stage 1 — clip step diagnostics, largest stream first, whole lines only.
    while not _fits(working, budget):
        candidates = [(len(step.stdout), "stdout", step) for step in working.steps if step.stdout]
        candidates += [(len(step.stderr), "stderr", step) for step in working.steps if step.stderr]
        if not candidates:
            break
        _, attr, step = max(candidates, key=lambda item: item[0])
        setattr(step, attr, _drop_trailing_lines(getattr(step, attr)))
        step.truncated = True

    # Stage 2 — drop payload list records from the end, longest list first.
    while not _fits(working, budget):
        lists = [(len(v), k) for k, v in working.data.items() if isinstance(v, list) and v]
        if not lists:
            break
        _, key = max(lists, key=lambda item: item[0])
        working.data[key] = working.data[key][:-1]

    # Stage 3 — drop the payload entirely.
    if not _fits(working, budget):
        working.data = {"omitted": True}

    # Stage 4 — drop step records entirely.
    if not _fits(working, budget):
        working.steps = []

    # Stage 5 — last resort: a minimal, still-truthful result.
    if not _fits(working, budget):
        working = OperationResult(
            status=result.status,
            operation=result.operation[:128],
            data={"omitted": True},
            error=OperationError(
                code=result.error.code if result.error else "result_truncated",
                message="result omitted: exceeded the configured byte budget",
            ),
            steps=[],
            truncated=True,
            elapsed_ms=result.elapsed_ms,
        )
    return working


# --------------------------------------------------------------------------- #
# Path policy
# --------------------------------------------------------------------------- #
def relative_posix(root: Path, target: Path) -> str:
    """Return ``target`` as a repo-relative POSIX path.

    Args:
        root: The repository root.
        target: An absolute path inside ``root``.

    Returns:
        The repo-relative POSIX path (``"."`` for the root itself).

    Raises:
        PathOutsideRootError: ``target`` is not inside ``root``.
    """
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise PathOutsideRootError(f"{str(target)!r} is not inside {str(root)!r}") from exc


def check_no_symlink_components(root: Path, candidate: str) -> Path:
    """Reject a path any of whose components below ``root`` is a symlink.

    The candidate is *normalized*, not resolved, so the returned path keeps
    the caller's spelling; each existing component below the root is then
    ``lstat``-ed. This closes the gap left by containment checks, which
    legitimately follow symlinks and therefore accept a link that happens to
    point back inside the root.

    Args:
        root: The (already resolved) repository root.
        candidate: A caller-supplied relative or absolute path.

    Returns:
        The normalized absolute path, with no symlinked component.

    Raises:
        PathOutsideRootError: The normalized path escapes ``root``.
        SymlinkRejectedError: A component below ``root`` is a symlink.
    """
    normalized = Path(os.path.normpath(os.path.join(str(root), candidate)))
    if normalized != root and not normalized.is_relative_to(root):
        raise PathOutsideRootError(f"{candidate!r} normalizes outside the repository root")

    current = root
    for part in normalized.relative_to(root).parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            # Nothing below an absent component can be a symlink.
            break
        if stat.S_ISLNK(mode):
            raise SymlinkRejectedError(f"{relative_posix(root, current)!r} is a symlink; symlinks are not followed")
    return normalized


def resolve_operand(policy: OptimizationPolicy, candidate: str, *, must_exist: bool) -> Path:
    """Resolve one caller-supplied path under the configured policy.

    Checks run in a deliberate order: containment first (and the secret
    deny-list when enabled), then symlink-component rejection, then existence.
    Running containment first means an escaping path is reported as such even
    when it also happens to be a symlink.

    Args:
        policy: The active policy supplying the root and secret setting.
        candidate: A caller-supplied relative or absolute path.
        must_exist: When True, a missing path is an error.

    Returns:
        The normalized absolute path, guaranteed inside the root and free of
        symlinked components.

    Raises:
        PathOutsideRootError: The path escapes the repository root.
        SecretFileError: The path matches the secret deny-list.
        SymlinkRejectedError: A component below the root is a symlink.
        PolicyError: ``must_exist`` is True and the path does not exist.
    """
    root = policy.repo_root
    if policy.deny_secret_files:
        resolve_readable_path(root, candidate)
    else:
        resolve_within_root(root, candidate)

    target = check_no_symlink_components(root, candidate)
    if must_exist and not target.exists():
        raise PolicyError(f"{candidate!r} does not exist")
    return target


# --------------------------------------------------------------------------- #
# Cross-process advisory lock
# --------------------------------------------------------------------------- #
class WorktreeLock:
    """A cross-process advisory lock serializing mutations per worktree.

    Built on ``fcntl.flock(LOCK_EX)``. flock is advisory and is released by
    the kernel when the owning process dies, so a stale lock file is never
    possible and the lock file is therefore **never** unlinked — deleting it
    would break the mutual exclusion of processes already holding it.

    External Git processes do not honor this lock, so Git's own index lock
    and the toolkit's revision checks remain necessary.

    Example:
        >>> async with WorktreeLock(git_dir / "parrot-tool-optimizations.lock", 30.0):
        ...     ...  # serialized section
    """

    def __init__(self, lock_path: Path, timeout_seconds: float) -> None:
        """Initialize the lock.

        Args:
            lock_path: The lock file path. Created if absent, never removed.
            timeout_seconds: How long to wait for the lock before failing.
        """
        self._path = Path(lock_path)
        self._timeout = float(timeout_seconds)
        self._fd: Optional[int] = None

    async def __aenter__(self) -> "WorktreeLock":
        """Acquire the exclusive lock, polling until the timeout expires.

        Returns:
            This lock instance.

        Raises:
            LockTimeoutError: The lock was still held when the timeout expired.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise LockTimeoutError(f"timed out acquiring {str(self._path)!r}") from None
                await asyncio.sleep(0.05)
            except BaseException:
                os.close(fd)
                raise

    async def __aexit__(self, *exc_info: Any) -> None:
        """Release the lock, leaving the lock file in place."""
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None
