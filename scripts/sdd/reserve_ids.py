"""``reserve_ids.py`` — the git-native compare-and-swap TASK/FEAT ID allocator.

Replaces the "scan existing files, take the max, +1" numbering used by
``/sdd-task``/``/sdd-spec`` with an optimistic-concurrency-with-retry
allocator (FEAT-387): read ``sdd/tasks/.id_ledger.json`` (TASK-1963),
compute the requested reservation, commit a *ledger-only* update, and push
to ``origin/<base_branch>``. A non-fast-forward push rejection means
another allocation landed first — fetch, re-read the now-current ledger,
recompute, and retry (bounded, with jittered backoff), instead of silently
succeeding with a stale, already-claimed number.

Usage:
    python -m scripts.sdd.reserve_ids --kind task --count 8 --base-branch dev --label sandbox-hardening
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from scripts.sdd.id_ledger import LEDGER_PATH, load_ledger, save_ledger

#: Timeout (seconds) for every individual git subprocess call. This script
#: is meant to serve concurrent, automated dev-loop dispatches — an
#: indefinite hang (stalled network, interactive credential prompt) in one
#: allocator instance must not block forever.
_GIT_TIMEOUT_SECONDS = 30.0


class IdReservationError(RuntimeError):
    """Raised when reserve_ids() exhausts its retry budget, or when a
    non-retryable precondition (dirty working tree, wrong branch, invalid
    push failure) is violated.
    """


class IdReservation(BaseModel):
    """Result handed back to the calling SDD command."""

    kind: str
    first_id: int
    count: int = Field(..., ge=1, description="Number of IDs reserved; must be at least 1.")
    ids: list[str]


def _run_git(
    args: list[str],
    repo_root: Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand rooted at ``repo_root``.

    Args:
        args: Arguments following ``git`` (e.g. ``["status", "--porcelain"]``).
        repo_root: Working directory to run the command in.
        check: When ``True`` (default), raise ``CalledProcessError`` on a
            non-zero exit code. Set to ``False`` for calls (like ``push``)
            whose failure is expected and handled explicitly by the caller.

    Returns:
        The completed subprocess result.

    Raises:
        subprocess.TimeoutExpired: If the git command does not complete
            within ``_GIT_TIMEOUT_SECONDS`` (e.g. a stalled network or an
            interactive credential prompt) — bounded so a single allocator
            instance can never hang forever.
    """
    env = dict(os.environ)
    # Never let git block on an interactive credential prompt — fail fast
    # instead of hanging indefinitely.
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
        env=env,
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _porcelain_path(line: str) -> str:
    """Extract the file path from one `git status --porcelain` line.

    Porcelain v1 (non-verbose) format is a fixed 2-character status code
    followed by a single space, then the path — parsing the field
    positionally is more robust than a substring/``in`` check, which would
    false-negative on any unrelated path that merely CONTAINS the ledger
    path as a substring.
    """
    return line[3:] if len(line) > 3 else line


def _assert_safe_to_reserve(root: Path, base_branch: str) -> None:
    """Verify it is safe to run the destructive retry sequence in ``root``.

    ``reserve_ids()``'s retry path runs ``git reset --hard
    origin/<base_branch>`` after a rejected push — that is only safe when
    (a) the working tree has no changes besides the ledger file, and (b)
    the current branch actually IS ``base_branch``. Enforced here (not just
    in the CLI) so any caller of the library function — including a future
    dev-loop subagent invoking ``reserve_ids()`` directly — inherits the
    same guard rather than a footgun.

    Args:
        root: Repository working directory to check.
        base_branch: The branch this reservation is expected to push to.

    Raises:
        IdReservationError: If the working tree has uncommitted changes
            besides the ledger file, or the current branch is not
            ``base_branch``.
    """
    status = _run_git(["status", "--porcelain"], root)
    dirty = [
        line
        for line in status.stdout.splitlines()
        if line.strip()
        and not line.startswith("?? ")
        and _porcelain_path(line) != str(LEDGER_PATH)
    ]
    if dirty:
        raise IdReservationError(
            "refusing to run — working tree has uncommitted changes besides "
            f"{LEDGER_PATH}:\n" + "\n".join(dirty)
        )

    branch_result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    current_branch = branch_result.stdout.strip()
    if current_branch != base_branch:
        raise IdReservationError(
            f"refusing to run — current branch {current_branch!r} does not "
            f"match --base-branch {base_branch!r}. reserve_ids() must run "
            "with the target branch checked out, never from inside a "
            "feature worktree."
        )


def _is_non_fast_forward_rejection(stderr: str) -> bool:
    """Return whether ``stderr`` looks like a non-fast-forward push rejection.

    Git's ref-status line (``! [rejected] ... (fetch first)`` /
    ``(non-fast-forward)``) is emitted in English regardless of the
    process locale — verified empirically against the installed git
    version — so this check is stable across environments, unlike the
    surrounding, locale-translated advice text.
    """
    return "[rejected]" in stderr and (
        "(fetch first)" in stderr or "(non-fast-forward)" in stderr
    )


def reserve_ids(
    kind: Literal["task", "feature"],
    count: int,
    base_branch: str,
    label: str,
    *,
    max_retries: int = 5,
    repo_root: Path | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> IdReservation:
    """Atomically reserve ``count`` sequential TASK or FEAT numbers.

    Reads ``sdd/tasks/.id_ledger.json``, computes the next ``count``
    numbers of the given ``kind``, commits the incremented ledger, and
    pushes to ``origin/<base_branch>``. On a non-fast-forward push
    rejection, fetches the current remote state, re-reads the ledger,
    recomputes the reservation, and retries up to ``max_retries`` times
    (with jittered backoff). Raises ``IdReservationError`` if retries are
    exhausted, or if the push fails for a reason OTHER than a
    non-fast-forward rejection (e.g. auth/network failure), since those
    are not safe to retry the same way.

    This function's own commit touches ONLY ``sdd/tasks/.id_ledger.json``
    — it never bundles in the task/spec files themselves, so the
    reservation race is decided by a single-line JSON diff, not by
    whatever else the calling command is about to commit.

    **Precondition**: at the moment this function is called, this
    function's own ledger-only commit must be the ONLY local commit ahead
    of ``origin/<base_branch>`` — the retry path runs `git reset --hard
    origin/<base_branch>` after a rejected push, which would silently
    discard ANY other local, unpushed commits or uncommitted changes. This
    is now enforced by ``reserve_ids()`` itself (not just the CLI): it
    refuses to run if the working tree is dirty with anything besides the
    ledger file, OR if the current branch does not match ``base_branch``
    (guards against being invoked from the wrong context, e.g. accidentally
    inside a feature worktree).

    Args:
        kind: ``"task"`` or ``"feature"``.
        count: Number of sequential IDs to reserve. Must be ``>= 1`` — a
            non-positive count would silently rewind the ledger's counter
            below IDs already issued, reopening the exact collision this
            allocator exists to close.
        base_branch: The branch to push the ledger-only commit to (e.g.
            ``"dev"``). ``reserve_ids()`` refuses to run unless this is
            also the currently checked-out branch in ``repo_root``.
        label: Free-text origin of this reservation (feature slug or
            session id) — diagnostic only, stored in the ledger's
            ``updated_by`` field.
        max_retries: Maximum number of read-commit-push attempts before
            raising ``IdReservationError``.
        repo_root: Directory to run all git operations in. Defaults to the
            current working directory. Tests pass a throwaway clone here
            so the retry loop never touches the real repository.
        sleep_fn: Callable used for the jittered backoff between retries.
            Defaults to ``time.sleep``; tests inject a no-op to avoid
            waiting in real time.

    Returns:
        The ``IdReservation`` describing the IDs that were successfully
        reserved.

    Raises:
        ValueError: If ``count < 1``.
        IdReservationError: When every attempt is rejected up to
            ``max_retries``, when a push fails for a non-retryable reason,
            or when the safety precondition (clean tree, correct branch)
            is violated.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count!r}")

    root = repo_root if repo_root is not None else Path.cwd()
    _assert_safe_to_reserve(root, base_branch)
    ledger_path = root / LEDGER_PATH
    prefix = "TASK" if kind == "task" else "FEAT"

    for attempt in range(max_retries):
        ledger = load_ledger(ledger_path)
        first = ledger.next_task_id if kind == "task" else ledger.next_feature_id
        ids = [f"{prefix}-{first + i}" for i in range(count)]

        if kind == "task":
            ledger.next_task_id = first + count
        else:
            ledger.next_feature_id = first + count
        ledger.updated_by = label
        ledger.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        save_ledger(ledger_path, ledger)

        _run_git(["add", str(LEDGER_PATH)], root)
        _run_git(
            ["commit", "-m", f"sdd: reserve {count} {kind} id(s) for {label}"],
            root,
        )

        push_result = _run_git(
            ["push", "origin", f"HEAD:{base_branch}"], root, check=False
        )
        if push_result.returncode == 0:
            return IdReservation(kind=kind, first_id=first, count=count, ids=ids)

        if not _is_non_fast_forward_rejection(push_result.stderr):
            # Not a rejection we know how to retry (auth/network failure,
            # etc.) — undo this attempt's local commit and fail loudly
            # instead of retrying the same way as a lost race.
            _run_git(["reset", "--hard", "HEAD~1"], root)
            raise IdReservationError(
                "git push failed for a reason other than a non-fast-forward "
                f"rejection: {push_result.stderr}"
            )

        # Rejected — someone else advanced the ledger first. Undo this
        # attempt's local commit, sync to the new remote state, and retry.
        _run_git(["reset", "--hard", "HEAD~1"], root)
        _run_git(["fetch", "origin", base_branch], root)
        _run_git(["reset", "--hard", f"origin/{base_branch}"], root)
        sleep_fn(random.uniform(0.1, 0.5) * (attempt + 1))

    raise IdReservationError(
        f"Failed to reserve {count} {kind} id(s) after {max_retries} attempts"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Prints the reserved IDs one per line on success (exit 0); prints an
    error to stderr and exits 1 on failure. ``reserve_ids()`` itself
    refuses to run (see its docstring precondition) if the working tree
    has uncommitted changes besides the ledger file, if the current branch
    does not match ``--base-branch``, or if ``--count`` is not positive —
    this CLI surfaces all three as a clean error message rather than a
    traceback.
    """
    parser = argparse.ArgumentParser(
        description="Reserve sequential TASK/FEAT IDs via a git-native compare-and-swap ledger (FEAT-387).",
    )
    parser.add_argument("--kind", choices=["task", "feature"], required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--base-branch", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-retries", type=int, default=5)
    args = parser.parse_args(argv)

    try:
        reservation = reserve_ids(
            args.kind,
            args.count,
            args.base_branch,
            args.label,
            max_retries=args.max_retries,
        )
    except (IdReservationError, ValueError) as exc:
        print(f"reserve_ids: {exc}", file=sys.stderr)
        return 1

    for reserved_id in reservation.ids:
        print(reserved_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
