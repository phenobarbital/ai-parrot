"""Fail CI when a commit removes an open or claimed issue from the ledger snapshot.

``sdd/ledger/issues.jsonl`` is the committed snapshot of the work ledger. It has
silently lost rows twice — ``ccbfef606`` (2026-09-21, 26 rows) and ``769ca8516``
(2026-10-17, +5/-142 including open issues, among them a vulnerability). Nothing
caught either event and 25 issues stayed lost until a human restored them.

``LedgerService.export_snapshot`` reconciles against the committed file since
FEAT-671, so the exporter is no longer the defect; the missing piece is a gate.
This guard is that gate, and it is deliberately independent of the code it
checks: it imports nothing from ``parrot`` so it still catches an export run by
an older or ``--no-reconcile`` build.

A status transition (``open`` -> ``closed``) is normal traffic and passes. Only
the *disappearance* of a row whose base status is ``open`` or ``claimed`` is
fatal; dropping a ``closed`` row is legal compaction. Intentional removals carry
a ``Ledger-Removal: issue:<id>`` trailer on a commit in ``base..HEAD``.

The comparison is made against the **merge base** of the base ref and ``HEAD``,
never the base ref's tip. The tip moves: a row appended to ``dev`` after a branch
forked is absent from that branch's snapshot without the branch ever having
removed it, and comparing against the tip reported it as a removal (CI run
39696105212 failed PR #1756 that way, over ``issue:bc57e4a79adb``, which
``a915bd971`` had added to ``dev`` three minutes after the run started). The
merge base is the only ref that answers the question the guard actually asks:
what did *this branch* drop?
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROTECTED_STATUSES: frozenset[str] = frozenset({"open", "claimed"})
OVERRIDE_TRAILER: str = "Ledger-Removal"
DEFAULT_SNAPSHOT = Path("sdd/ledger/issues.jsonl")


@dataclass(frozen=True)
class SnapshotRow:
    """One parsed row of the ledger snapshot."""

    issue_id: str
    status: str
    title: str


def load_snapshot(text: str) -> dict[str, SnapshotRow]:
    """Parse snapshot JSONL into ``{issue_id: SnapshotRow}``, skipping blank lines.

    Args:
        text: Raw contents of a ``issues.jsonl`` snapshot.

    Returns:
        One ``SnapshotRow`` per issue, keyed by ``issue_id``.

    Raises:
        ValueError: If a non-blank line is not a JSON object carrying an ``issue_id``.
            Reported with the 1-based line number so the offending row can be found.
    """
    rows: dict[str, SnapshotRow] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {number}: not valid JSON ({error.msg})") from error
        if not isinstance(payload, dict):
            raise ValueError(f"line {number}: expected a JSON object, got {type(payload).__name__}")
        issue_id = payload.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            raise ValueError(f"line {number}: missing or non-string 'issue_id'")
        rows[issue_id] = SnapshotRow(
            issue_id=issue_id,
            status=str(payload.get("status", "")),
            title=str(payload.get("title", "")),
        )
    return rows


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a git command from an argument list with captured text output."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def resolve_comparison_base(base_ref: str) -> str:
    """Return the merge-base commit of ``base_ref`` and ``HEAD``.

    Args:
        base_ref: Ref the branch is measured against, e.g. ``origin/dev``.

    Returns:
        The full sha of the fork point, which is what the snapshot is compared at.

    Raises:
        RuntimeError: If ``base_ref`` cannot be resolved, or if it shares no history
            with ``HEAD``. The usual cause of the latter is a clone too shallow for
            the two histories to meet; that must fail the gate rather than pass it,
            for the same reason an unresolvable base ref does.
    """
    resolved = _git(["rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError(
            f"cannot resolve base ref {base_ref!r}. In CI, fetch it first " f"(git fetch origin <branch>)."
        )
    merge_base = _git(["merge-base", base_ref, "HEAD"])
    commit = merge_base.stdout.strip()
    if merge_base.returncode != 0 or not commit:
        raise RuntimeError(
            f"no merge base between {base_ref!r} and HEAD. The clone is probably too "
            f"shallow for the two histories to meet — check out with 'fetch-depth: 0' "
            f"and fetch the base ref without --depth."
        )
    return commit


def read_base_snapshot(base_ref: str, path: Path) -> str | None:
    """Return the snapshot text at ``base_ref``, or ``None`` when absent there.

    Args:
        base_ref: Ref or commit to read the snapshot from — in practice the merge
            base returned by :func:`resolve_comparison_base`.
        path: Repo-relative path of the snapshot.

    Returns:
        The file's contents at ``base_ref``, or ``None`` when the file does not
        exist at that ref (a newly added snapshot has nothing to remove).

    Raises:
        RuntimeError: If ``base_ref`` itself cannot be resolved. A shallow clone
            that never fetched the base must fail the gate, never silently pass
            it — that would reintroduce exactly the blind spot this guard closes.
    """
    resolved = _git(["rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"])
    if resolved.returncode != 0:
        raise RuntimeError(
            f"cannot resolve base ref {base_ref!r}. In CI, fetch it first " f"(git fetch origin <branch>)."
        )
    shown = _git(["show", f"{base_ref}:{path.as_posix()}"])
    if shown.returncode != 0:
        return None
    return shown.stdout


def allowed_removals(base_ref: str) -> set[str]:
    """Collect issue ids from ``Ledger-Removal:`` trailers in ``base_ref..HEAD``.

    Only commits introduced on top of ``base_ref`` are read, so an override from
    an unrelated older commit cannot authorize a removal made today.
    """
    result = _git(["log", f"{base_ref}..HEAD", "--format=%B"])
    if result.returncode != 0:
        return set()
    allowed: set[str] = set()
    prefix = f"{OVERRIDE_TRAILER.lower()}:"
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith(prefix):
            continue
        value = stripped.split(":", 1)[1]
        for token in value.replace(",", " ").split():
            if token:
                allowed.add(token)
    return allowed


def find_violations(
    base: dict[str, SnapshotRow],
    head: dict[str, SnapshotRow],
    allowed: set[str],
) -> list[SnapshotRow]:
    """Return base rows that are protected, absent from ``head``, and not overridden.

    Sorted by ``issue_id`` so the report is deterministic.
    """
    return [
        row
        for issue_id, row in sorted(base.items())
        if row.status in PROTECTED_STATUSES and issue_id not in head and issue_id not in allowed
    ]


def main(argv: list[str] | None = None) -> int:
    """Check the snapshot against a base ref.

    Returns:
        ``0`` when no protected row was removed, ``1`` on any violation or when
        the head snapshot is missing, unreadable or malformed (fail closed).
    """
    parser = argparse.ArgumentParser(description="Reject removals of open/claimed ledger issues.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--base-ref", default="origin/dev")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="ISSUE_ID",
        help="Permit removal of this issue id (repeatable).",
    )
    args = parser.parse_args(argv)

    try:
        head_text = args.snapshot.read_text()
    except OSError as error:
        print(f"error: cannot read {args.snapshot}: {error}", file=sys.stderr)
        return 1

    try:
        head = load_snapshot(head_text)
    except ValueError as error:
        print(f"error: malformed snapshot {args.snapshot}: {error}", file=sys.stderr)
        return 1

    try:
        base_commit = resolve_comparison_base(args.base_ref)
        base_text = read_base_snapshot(base_commit, args.snapshot)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if base_text is None:
        print(f"ok: {args.snapshot} does not exist at {args.base_ref}; nothing to compare.")
        return 0

    try:
        base = load_snapshot(base_text)
    except ValueError as error:
        print(f"error: malformed snapshot at {args.base_ref}: {error}", file=sys.stderr)
        return 1

    allowed = set(args.allow) | allowed_removals(base_commit)
    violations = find_violations(base, head, allowed)

    if not violations:
        print(
            f"ok: {len(base)} rows at the {args.base_ref} merge base {base_commit[:9]}, "
            f"{len(head)} at HEAD; no open/claimed issue removed."
        )
        return 0

    print(
        f"error: {len(violations)} issue(s) that are open or claimed at the {args.base_ref} "
        f"merge base {base_commit[:9]} were removed from {args.snapshot}:",
        file=sys.stderr,
    )
    for row in violations:
        print(f"  {row.issue_id}  [{row.status}]  {row.title}", file=sys.stderr)
    print(
        f"\nIf a removal is intentional, add a '{OVERRIDE_TRAILER}: <issue-id>' trailer to the "
        f"commit that removes it, or re-run with --allow <issue-id>.\n"
        f"Otherwise the snapshot was exported from a stale ledger: re-run the export with "
        f"reconciliation enabled (never --no-reconcile) and commit the result.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
