"""Git-measured "what changed" for a dev-loop run (the PR-style file list).

``DevelopmentOutput.files_changed`` names the files a coding agent *says*
it touched; :func:`compute_changeset` asks git instead and adds the
numbers a reviewer actually looks at — per-file ``+/-`` line counts, the
change status, commit count — so the closing summary can render the same
list a pull request shows.

Pure git plumbing, best-effort by contract: every helper returns ``None``
/ empty on a non-git directory or a failing ``git`` binary, and never
raises into a node. The base-ref ladder mirrors
``DevelopmentNode._git_changed_files`` (``origin/<base>`` → ``origin/dev``
→ ``origin/main``, selected on whether the ref RESOLVES, not on whether
its diff is empty — an empty diff against the true base is a valid
answer, and falling through would attribute the base's own commits to
this run).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from parrot.flows.dev_loop.models import ChangedFile, ChangeSet

logger = logging.getLogger(__name__)


async def _git(worktree_path: str, *args: str) -> Optional[str]:
    """Run ``git <args>`` in *worktree_path*; ``None`` on any failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except Exception:  # noqa: BLE001 - best-effort plumbing
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode(errors="replace")


async def resolve_base_ref(worktree_path: str, base_branch: str = "") -> Optional[str]:
    """Pick the first upstream ref that resolves in *worktree_path*.

    Args:
        worktree_path: The worktree to inspect.
        base_branch: The run's resolved base branch; ``""`` to rely on the
            ``origin/dev`` → ``origin/main`` ladder alone.

    Returns:
        The ref name (``"origin/dev"``), or ``None`` when none resolves —
        which is also what a non-git directory yields.
    """
    candidates: List[str] = []
    if base_branch:
        candidates.append(base_branch if "/" in base_branch else f"origin/{base_branch}")
    candidates += ["origin/dev", "origin/main"]
    for ref in candidates:
        if await _git(worktree_path, "rev-parse", "--verify", "--quiet", ref) is not None:
            return ref
    return None


def _parse_numstat(text: str) -> Dict[str, Tuple[int, int, bool]]:
    """``git diff --numstat`` → ``{path: (additions, deletions, binary)}``.

    Renames render as ``old => new`` (or ``dir/{old => new}/file``); only
    the new path is kept, matching ``--name-status``'s second column.
    """
    out: Dict[str, Tuple[int, int, bool]] = {}
    for line in text.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        add_s, del_s, path = parts[0], parts[1], "\t".join(parts[2:])
        binary = add_s == "-" or del_s == "-"
        additions = 0 if binary else int(add_s or 0)
        deletions = 0 if binary else int(del_s or 0)
        out[_rename_target(path)] = (additions, deletions, binary)
    return out


def _rename_target(path: str) -> str:
    """Reduce a numstat rename spelling to the destination path."""
    if "{" in path and " => " in path and "}" in path:
        prefix, rest = path.split("{", 1)
        inner, suffix = rest.split("}", 1)
        _old, new = inner.split(" => ", 1)
        return f"{prefix}{new}{suffix}".replace("//", "/")
    if " => " in path:
        return path.split(" => ", 1)[1]
    return path


def _parse_name_status(text: str) -> Dict[str, str]:
    """``git diff --name-status`` → ``{path: status_letter}`` (new path for R/C)."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            continue
        letter = parts[0][:1] or "M"
        path = parts[-1]
        out[path] = letter if letter in "AMDRCT" else "M"
    return out


def _parse_porcelain(text: str) -> Dict[str, str]:
    """``git status --porcelain --untracked-files=all`` → ``{path: status}``.

    Untracked entries become ``"?"``; staged/unstaged edits map to their
    index/worktree letter, deletions to ``"D"``.
    """
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip('"')
        if not path:
            continue
        if code == "??":
            out[path] = "?"
        elif "D" in code:
            out[path] = "D"
        elif "A" in code:
            out[path] = "A"
        elif "R" in code:
            out[path] = "R"
        else:
            out[path] = "M"
    return out


async def compute_changeset(
    worktree_path: str,
    base_branch: str = "",
    *,
    branch: str = "",
) -> Optional[ChangeSet]:
    """Measure what *worktree_path* changed relative to its base branch.

    Committed work is the three-dot diff against the merge base with the
    resolved upstream (``--numstat`` for counts, ``--name-status`` for the
    letter, ``rev-list --count`` for the commit count). Uncommitted work —
    including untracked files, which is how a just-written test module
    looks before the worker commits — is folded in from ``git diff
    --numstat HEAD`` and ``git status --porcelain``; an untracked file has
    no diff to count, so it lands with ``status="?"`` and zero lines.

    Args:
        worktree_path: The worktree to inspect.
        base_branch: The run's resolved base branch (``"dev"``); ``""``
            walks the fallback ladder alone.
        branch: The feature branch name, recorded for display only.

    Returns:
        The :class:`ChangeSet`, or ``None`` when the directory is not a git
        worktree / no upstream ref resolves / git fails. Never raises.
    """
    try:
        base_ref = await resolve_base_ref(worktree_path, base_branch)
        if base_ref is None:
            return None

        numstat = await _git(worktree_path, "diff", "--numstat", f"{base_ref}...HEAD")
        name_status = await _git(worktree_path, "diff", "--name-status", f"{base_ref}...HEAD")
        if numstat is None or name_status is None:
            return None
        counts = _parse_numstat(numstat)
        statuses = _parse_name_status(name_status)

        # Uncommitted edits to tracked files (staged or not) — counted
        # against HEAD so they ADD to the committed numbers rather than
        # re-counting them.
        working = await _git(worktree_path, "diff", "--numstat", "HEAD")
        working_counts = _parse_numstat(working) if working else {}
        porcelain = await _git(worktree_path, "status", "--porcelain", "--untracked-files=all")
        working_status = _parse_porcelain(porcelain) if porcelain else {}

        files: Dict[str, ChangedFile] = {}
        for path, (add, dele, binary) in counts.items():
            files[path] = ChangedFile(
                path=path, additions=add, deletions=dele, status=statuses.get(path, "M"), binary=binary
            )
        for path, letter in statuses.items():
            files.setdefault(path, ChangedFile(path=path, status=letter))
        for path, (add, dele, binary) in working_counts.items():
            prior = files.get(path)
            if prior is None:
                files[path] = ChangedFile(
                    path=path, additions=add, deletions=dele, status=working_status.get(path, "M"), binary=binary
                )
            else:
                files[path] = prior.model_copy(
                    update={
                        "additions": prior.additions + add,
                        "deletions": prior.deletions + dele,
                        "binary": prior.binary or binary,
                    }
                )
        for path, letter in working_status.items():
            if path not in files:
                files[path] = ChangedFile(path=path, status=letter)

        rev_count = await _git(worktree_path, "rev-list", "--count", f"{base_ref}..HEAD")
        try:
            commits = int((rev_count or "0").strip() or 0)
        except ValueError:
            commits = 0

        ordered = [files[p] for p in sorted(files)]
        return ChangeSet(
            base_ref=base_ref,
            branch=branch,
            worktree_path=worktree_path,
            files=ordered,
            total_additions=sum(f.additions for f in ordered),
            total_deletions=sum(f.deletions for f in ordered),
            commits=commits,
            uncommitted=len(working_status),
        )
    except Exception:  # noqa: BLE001 - never break a node over a summary
        logger.debug("compute_changeset failed for %s", worktree_path, exc_info=True)
        return None


async def record_changeset(
    shared: Dict[str, Any],
    worktree_path: str,
    base_branch: str = "",
    *,
    branch: str = "",
) -> Optional[ChangeSet]:
    """Compute the changeset, publish it to ``shared`` and to session state.

    The session-state route (``run/changesetRecorded`` via
    ``shared["session_host"]``) is what makes the file list visible to the
    console live, replayable, and part of the run bundle; ``shared`` is
    what the handoff node reads when it writes the PR body. Both are
    best-effort — a missing host, a non-git worktree or a refusing host
    leaves ``shared`` untouched and returns ``None``.

    Args:
        shared: The flow's shared state.
        worktree_path: Worktree to measure.
        base_branch: Resolved base branch, or ``""``.
        branch: Feature branch name for display.

    Returns:
        The recorded :class:`ChangeSet`, or ``None``.
    """
    changeset = await compute_changeset(worktree_path, base_branch, branch=branch)
    if changeset is None:
        return None
    shared["changeset"] = changeset
    host = shared.get("session_host")
    if host is not None:
        try:
            from parrot.flows.dev_loop.session_state import ChangesetRecorded

            host.apply(ChangesetRecorded(changeset=changeset))
        except Exception:  # noqa: BLE001 - summary must never break a run
            logger.debug("run/changesetRecorded dropped", exc_info=True)
    return changeset


def files_changed_markdown(files_changed: List[str], changeset: Optional[ChangeSet]) -> str:
    """The ``## Files changed`` body of a handoff PR.

    With a git-measured :class:`ChangeSet` this is the same table a reviewer
    sees on the PR (status, path, ``+``/``−`` per file, and a totals line);
    without one it degrades to the agent's self-reported names — the
    pre-changeset rendering, byte-identical (first ten names, comma-joined).

    Args:
        files_changed: ``DevelopmentOutput.files_changed`` (the fallback).
        changeset: The recorded changeset, or ``None``.

    Returns:
        Markdown for the section body.
    """
    if changeset is None or not changeset.files:
        return ", ".join(files_changed[:10]) if files_changed else "(none)"
    rows = ["| Status | File | + | − |", "|---|---|---|---|"]
    for f in changeset.files:
        plus = "bin" if f.binary else str(f.additions)
        minus = "bin" if f.binary else str(f.deletions)
        rows.append(f"| {f.status} | `{f.path}` | {plus} | {minus} |")
    totals = (
        f"{len(changeset.files)} file(s), **+{changeset.total_additions} −{changeset.total_deletions}**, "
        f"{changeset.commits} commit(s) vs `{changeset.base_ref}`"
    )
    return totals + "\n\n" + "\n".join(rows)


__all__ = ["compute_changeset", "files_changed_markdown", "record_changeset", "resolve_base_ref"]
