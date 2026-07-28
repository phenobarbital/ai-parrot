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
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from scripts.sdd.id_ledger import LEDGER_PATH, load_ledger, save_ledger


class IdReservationError(RuntimeError):
    """Raised when reserve_ids() exhausts its retry budget."""


class IdReservation(BaseModel):
    """Result handed back to the calling SDD command."""

    kind: str
    first_id: int
    count: int
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
    """
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=check,
        capture_output=True,
        text=True,
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
    discard ANY other local, unpushed commits or uncommitted changes. The
    CLI entrypoint below refuses to run when the working tree is dirty
    with anything besides the ledger file, precisely to guard this
    invariant; callers using this function as a library must uphold it
    themselves.

    Args:
        kind: ``"task"`` or ``"feature"``.
        count: Number of sequential IDs to reserve.
        base_branch: The branch to push the ledger-only commit to (e.g.
            ``"dev"``).
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
        IdReservationError: When every attempt is rejected up to
            ``max_retries``, or when a push fails for a non-retryable
            reason.
    """
    root = repo_root if repo_root is not None else Path.cwd()
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
    error to stderr and exits 1 on failure, including a refusal to run at
    all if the working tree has uncommitted changes besides the ledger
    file (see ``reserve_ids()``'s docstring precondition).
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

    root = Path.cwd()
    status = _run_git(["status", "--porcelain"], root)
    dirty = [
        line
        for line in status.stdout.splitlines()
        if line.strip() and str(LEDGER_PATH) not in line
    ]
    if dirty:
        print(
            "reserve_ids: refusing to run — working tree has uncommitted "
            f"changes besides {LEDGER_PATH}:\n" + "\n".join(dirty),
            file=sys.stderr,
        )
        return 1

    try:
        reservation = reserve_ids(
            args.kind,
            args.count,
            args.base_branch,
            args.label,
            max_retries=args.max_retries,
        )
    except IdReservationError as exc:
        print(f"reserve_ids: {exc}", file=sys.stderr)
        return 1

    for reserved_id in reservation.ids:
        print(reserved_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
