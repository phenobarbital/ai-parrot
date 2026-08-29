"""``reserve_ids.py`` — the git-native compare-and-swap TASK/FEAT ID allocator.

Replaces the "scan existing files, take the max, +1" numbering used by
``/sdd-task``/``/sdd-spec`` with an optimistic-concurrency-with-retry
allocator (FEAT-387): read ``sdd/tasks/.id_ledger.json`` (TASK-1963),
compute the requested reservation, build a *ledger-only* commit on top of
``origin/<base_branch>``, and push it. A non-fast-forward push rejection
means another allocation landed first — fetch, re-read the now-current
ledger, recompute, and retry (bounded, with jittered backoff), instead of
silently succeeding with a stale, already-claimed number.

The reservation is a compare-and-swap against ``origin/<base_branch>``
**alone**. The candidate commit is assembled with git plumbing
(``hash-object`` / ``read-tree`` / ``write-tree`` / ``commit-tree``) in a
throwaway index, so the local branch, the local index and the working tree
are never mutated by an attempt — a lost race costs one dangling commit
object and nothing else. In particular this allocator never runs ``git
reset --hard`` and never pushes ``HEAD``, so it can neither destroy nor
publish local-only commits on the base branch.

Usage:
    python -m scripts.sdd.reserve_ids --kind task --count 8 --base-branch dev --label sandbox-hardening
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger

#: Timeout (seconds) for every individual git subprocess call. This script
#: is meant to serve concurrent, automated dev-loop dispatches — an
#: indefinite hang (stalled network, interactive credential prompt) in one
#: allocator instance must not block forever.
_GIT_TIMEOUT_SECONDS = 30.0

#: The ledger's path as git spells it (forward slashes on every platform).
_LEDGER_GIT_PATH = LEDGER_PATH.as_posix()


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
    env_extra: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a git subcommand rooted at ``repo_root``.

    Args:
        args: Arguments following ``git`` (e.g. ``["status", "--porcelain"]``).
        repo_root: Working directory to run the command in.
        check: When ``True`` (default), raise ``CalledProcessError`` on a
            non-zero exit code. Set to ``False`` for calls (like ``push``)
            whose failure is expected and handled explicitly by the caller.
        env_extra: Extra environment variables for this call — used to
            point ``GIT_INDEX_FILE`` at a throwaway index so the plumbing
            that builds the ledger commit never touches the real one.
        stdin: Text piped to the command's standard input (used by
            ``git hash-object --stdin``).

    Returns:
        The completed subprocess result.

    Raises:
        IdReservationError: If the git command does not complete within
            ``_GIT_TIMEOUT_SECONDS`` (e.g. a stalled network or an
            interactive credential prompt). Bounded so a single allocator
            instance can never hang forever — and surfaced as this
            module's own error type so ``reserve_ids()`` keeps its
            contract that every failure mode is an ``IdReservationError``.
        subprocess.CalledProcessError: If ``check`` is ``True`` and git
            exits non-zero; callers translate this into an
            ``IdReservationError`` with context.
    """
    env = dict(os.environ)
    # Never let git block on an interactive credential prompt — fail fast
    # instead of hanging indefinitely.
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Two of this module's decisions read git's output (the porcelain
    # status codes and the push ref-status line). Neither is translated by
    # the git version in use — verified empirically under a fully
    # installed es_ES.UTF-8 with LANGUAGE=es, where the surrounding advice
    # text IS translated ("ayuda:") but `! [rejected] ... (fetch first)`
    # stays English. Pinning the locale anyway costs nothing and removes
    # the dependency on that observation holding in future git releases.
    env["LC_ALL"] = "C"
    if env_extra:
        env.update(env_extra)
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=check,
            capture_output=True,
            text=True,
            env=env,
            input=stdin,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise IdReservationError(
            f"git {' '.join(args[:2])} timed out after "
            f"{_GIT_TIMEOUT_SECONDS:.0f}s"
        ) from exc


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
    """Verify ``root`` is in the state this allocator is contracted to run in.

    Neither check is load-bearing for *safety* any more — the reservation
    is built with plumbing against ``origin/<base_branch>`` and never
    rewrites local history (see the module docstring). They are kept as a
    contract check: ``/sdd-task`` and ``/sdd-spec`` are documented to run
    on the base branch with a clean tree, and the post-reservation
    fast-forward of the local branch only lands cleanly under those
    conditions. Failing loudly here beats silently leaving the caller's
    branch behind ``origin/<base_branch>``.

    Untracked files are ignored: nothing in this module can clobber them.

    Args:
        root: Repository working directory to check.
        base_branch: The branch this reservation is expected to push to.

    Raises:
        IdReservationError: If tracked files have uncommitted changes
            besides the ledger file, or the current branch is not
            ``base_branch``.
    """
    status = _run_git(["status", "--porcelain"], root)
    dirty = [
        line
        for line in status.stdout.splitlines()
        if line.strip()
        and not line.startswith("?? ")
        and _porcelain_path(line) != _LEDGER_GIT_PATH
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


def _resolve_base_sha(root: Path, base_branch: str, *, fetch: bool) -> str:
    """Return the commit sha the next reservation attempt must build on.

    Args:
        root: Repository working directory.
        base_branch: Branch being reserved against.
        fetch: When ``True``, refresh from the remote first and use the
            fetched tip. Retries always fetch — a retry only happens
            because the remote moved. The first attempt reads the existing
            ``origin/<base_branch>`` remote-tracking ref (falling back to a
            fetch if it does not exist yet): if that ref is stale, the
            attempt simply loses the race and the retry corrects it.

    Returns:
        The 40-character sha of the base commit.

    Raises:
        IdReservationError: If the base tip cannot be resolved.
    """
    if not fetch:
        probe = _run_git(
            ["rev-parse", "--verify", "--quiet", f"origin/{base_branch}^{{commit}}"],
            root,
            check=False,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return probe.stdout.strip()

    # Fetch into the remote-tracking ref explicitly rather than reading
    # FETCH_HEAD: FETCH_HEAD is a single per-worktree file, so a concurrent
    # `git fetch` for a DIFFERENT branch in the same working directory (two
    # SDD commands on one checkout is a documented hazard in this repo)
    # could hand us an unrelated tip — which we would then push onto
    # <base_branch>. The tracking ref is per-branch and cannot be confused.
    tracking_ref = f"refs/remotes/origin/{base_branch}"
    try:
        _run_git(
            ["fetch", "origin", f"+refs/heads/{base_branch}:{tracking_ref}"], root
        )
        result = _run_git(["rev-parse", "--verify", f"{tracking_ref}^{{commit}}"], root)
    except subprocess.CalledProcessError as exc:
        raise IdReservationError(
            f"could not resolve origin/{base_branch}: {exc.stderr or exc}"
        ) from exc
    return result.stdout.strip()


def _read_ledger_at(root: Path, base_sha: str) -> IdLedger:
    """Read the ledger exactly as it exists in commit ``base_sha``.

    The remote's copy — not the working tree's — is the compare-and-swap's
    input: a local edit or a stale checkout must never be able to hand out
    a number the remote already issued.

    Args:
        root: Repository working directory.
        base_sha: Commit to read ``sdd/tasks/.id_ledger.json`` out of.

    Returns:
        The parsed ``IdLedger``.

    Raises:
        IdReservationError: If the ledger is missing from that commit.
    """
    try:
        result = _run_git(["show", f"{base_sha}:{_LEDGER_GIT_PATH}"], root)
    except subprocess.CalledProcessError as exc:
        raise IdReservationError(
            f"{LEDGER_PATH} not found in {base_sha}: {exc.stderr or exc}"
        ) from exc

    try:
        return IdLedger.model_validate_json(result.stdout)
    except ValidationError as exc:
        raise IdReservationError(
            f"{LEDGER_PATH} in {base_sha} is not a valid ledger: {exc}"
        ) from exc


def _build_ledger_commit(
    root: Path, base_sha: str, ledger: IdLedger, message: str
) -> str:
    """Create a commit on top of ``base_sha`` changing only the ledger.

    Built entirely with plumbing against a throwaway index
    (``GIT_INDEX_FILE``), so the caller's branch, index and working tree
    are untouched. The commit is a loose object until the push succeeds; a
    lost race leaves it dangling, to be reclaimed by ``git gc``.

    Args:
        root: Repository working directory.
        base_sha: Parent commit for the new commit.
        ledger: The updated ledger to serialize into the commit.
        message: Commit message.

    Returns:
        The sha of the newly created commit object.

    Raises:
        IdReservationError: If any plumbing step fails.
    """
    with tempfile.TemporaryDirectory(prefix="reserve-ids-") as tmpdir:
        index_env = {"GIT_INDEX_FILE": str(Path(tmpdir) / "index")}
        ledger_json = Path(tmpdir) / "ledger.json"
        save_ledger(ledger_json, ledger)

        try:
            blob = _run_git(
                ["hash-object", "-w", "--stdin"],
                root,
                stdin=ledger_json.read_text(encoding="utf-8"),
            ).stdout.strip()
            _run_git(["read-tree", base_sha], root, env_extra=index_env)
            _run_git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{_LEDGER_GIT_PATH}",
                ],
                root,
                env_extra=index_env,
            )
            tree = _run_git(["write-tree"], root, env_extra=index_env).stdout.strip()
            commit = _run_git(
                ["commit-tree", tree, "-p", base_sha, "-m", message], root
            ).stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise IdReservationError(
                f"could not build the ledger commit: {exc.stderr or exc}"
            ) from exc

    return commit


def _sync_local_branch(root: Path, base_branch: str, commit_sha: str) -> None:
    """Fast-forward the checked-out base branch onto the reserved commit.

    Best-effort and strictly non-destructive: ``--ff-only`` refuses rather
    than rewrites, so a base branch carrying unpushed local commits (or a
    locally modified ledger) is left exactly as it was, with a warning
    telling the caller how to reconcile. The reservation has already
    landed on the remote at this point — failing the call over a local
    bookkeeping step would strand IDs that are now permanently issued.

    Args:
        root: Repository working directory.
        base_branch: Branch expected to be checked out.
        commit_sha: The ledger commit that was just pushed.
    """
    merge = _run_git(["merge", "--ff-only", commit_sha], root, check=False)
    if merge.returncode == 0:
        return

    print(
        f"reserve_ids: WARNING — the reservation is pushed to origin/{base_branch}, "
        f"but the local {base_branch} could not be fast-forwarded onto it "
        f"({merge.stderr.strip() or 'not a fast-forward'}).\n"
        f"reserve_ids: your local commits are intact and were NOT pushed. "
        f"Reconcile before pushing, e.g. `git pull --no-rebase origin {base_branch}`.",
        file=sys.stderr,
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

    Reads ``sdd/tasks/.id_ledger.json`` **as of ``origin/<base_branch>``**,
    computes the next ``count`` numbers of the given ``kind``, builds a
    ledger-only commit on that tip with git plumbing, and pushes it to
    ``refs/heads/<base_branch>``. The push IS the compare-and-swap: on a
    non-fast-forward rejection the remote moved first, so the allocator
    fetches, re-reads the now-current ledger, recomputes, and retries up
    to ``max_retries`` times (with jittered backoff). It raises
    ``IdReservationError`` if retries are exhausted, or if the push fails
    for a reason OTHER than a non-fast-forward rejection (e.g.
    auth/network failure), since those are not safe to retry the same way.

    The pushed commit touches ONLY ``sdd/tasks/.id_ledger.json`` and has
    ``origin/<base_branch>`` as its parent, so the reservation race is
    decided by a single-line JSON diff — never by whatever else the caller
    happens to have committed locally.

    **Local commits on the base branch are never published and never
    destroyed.** Attempts run entirely in the object database plus a
    throwaway index; no attempt mutates the local branch, the index or the
    working tree, and no code path here runs ``git reset``. After a
    successful push the local branch is fast-forwarded onto the
    reservation as a convenience; if it cannot be (because it carries
    unpushed commits), it is left untouched and a warning explains how to
    reconcile.

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
        max_retries: Maximum number of read-build-push attempts before
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
            or when the contract check (clean tree, correct branch) fails.
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count!r}")

    root = repo_root if repo_root is not None else Path.cwd()
    _assert_safe_to_reserve(root, base_branch)
    prefix = "TASK" if kind == "task" else "FEAT"

    for attempt in range(max_retries):
        base_sha = _resolve_base_sha(root, base_branch, fetch=attempt > 0)
        ledger = _read_ledger_at(root, base_sha)
        first = ledger.next_task_id if kind == "task" else ledger.next_feature_id
        ids = [f"{prefix}-{first + i}" for i in range(count)]

        if kind == "task":
            ledger.next_task_id = first + count
        else:
            ledger.next_feature_id = first + count
        ledger.updated_by = label
        ledger.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        commit_sha = _build_ledger_commit(
            root,
            base_sha,
            ledger,
            f"sdd: reserve {count} {kind} id(s) for {label}",
        )

        push_result = _run_git(
            ["push", "origin", f"{commit_sha}:refs/heads/{base_branch}"],
            root,
            check=False,
        )
        if push_result.returncode == 0:
            _sync_local_branch(root, base_branch, commit_sha)
            return IdReservation(kind=kind, first_id=first, count=count, ids=ids)

        if not _is_non_fast_forward_rejection(push_result.stderr):
            # Not a rejection we know how to retry (auth/network failure,
            # etc.) — fail loudly instead of retrying as a lost race.
            # Nothing to undo: the attempt never left the object database.
            raise IdReservationError(
                "git push failed for a reason other than a non-fast-forward "
                f"rejection: {push_result.stderr}"
            )

        # Rejected — someone else advanced the ledger first. Retry against
        # the new remote tip; the candidate commit just built is abandoned
        # as an unreferenced object.
        sleep_fn(random.uniform(0.1, 0.5) * (attempt + 1))

    raise IdReservationError(
        f"Failed to reserve {count} {kind} id(s) after {max_retries} attempts"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Prints the reserved IDs one per line on success (exit 0); prints an
    error to stderr and exits 1 on failure. ``reserve_ids()`` itself
    refuses to run (see its docstring) if tracked files have uncommitted
    changes besides the ledger file, if the current branch does not match
    ``--base-branch``, or if ``--count`` is not positive — this CLI
    surfaces all three as a clean error message rather than a traceback.
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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"reserve_ids: git command failed: {exc}", file=sys.stderr)
        return 1

    for reserved_id in reservation.ids:
        print(reserved_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
