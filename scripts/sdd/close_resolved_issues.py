"""``close_resolved_issues.py`` — close the ledger issues a finished feature fixed.

The ``/sdd-fix`` SDD lane only *files* work (spec → tasks → worktree); the
tasks are implemented later, often by ``sdd-worker`` in another session. The
lane hands the issue's closure to ``/sdd-done``, which historically never ran
``wikitoolkit ledger close`` — so every issue fixed through the SDD lane stayed
``claimed`` (invisible to ``ledger plan-fix``) or ``open`` (re-offered as if
still broken) after its fix merged.

This script is the ``/sdd-done`` close step. An issue is linked to a feature by

* a task file line ``**Discovered-from**: `issue:<id>``` (or the legacy
  ``discovered_from: issue:<id>``) — linked to that task, or
* the spec's YAML frontmatter citing ``issue:<id>`` (e.g. ``source:``) —
  linked to every task of the feature. Issues mentioned only in the spec
  *body* are context (related, out of scope) and are ignored.

It closes a linked ``open``/``claimed`` issue only with the same two keys
``/sdd-fix`` uses, fail-closed:

1. every task linked to the issue is ``done`` with ``verification ==
   "verified"`` in the per-spec index (partial / forced / done-with-issues
   never count), and
2. at least one file named by the issue's ``about`` refs appears in
   ``git diff --name-only <base>...HEAD`` of the feature worktree.

Anything that fails a key is reported and left untouched.

Usage:
    python -m scripts.sdd.close_resolved_issues --worktree PATH \
        --index sdd/tasks/index/<slug>.json --base origin/<base_branch> \
        [--feature-id FEAT-<NNN>] [--actor agent:sdd-done] [--dry-run]

Prints a JSON report on stdout and exits 0 unless invoked wrongly; a ledger
write failure is reported per issue (``read-only`` when the shared ledger is
not writable), never raised — closing is bookkeeping and must not fail
``/sdd-done``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

#: A ledger issue id as written in task files and specs.
_ISSUE_RE = re.compile(r"issue:[0-9a-f]{12}\b")

#: A task file's link line: ``**Discovered-from**: ...`` or ``discovered_from: ...``.
_DISCOVERED_RE = re.compile(r"^\W*discovered[-_]from\W*:(.*)$", re.IGNORECASE | re.MULTILINE)

#: Ledger statuses an issue can be closed from.
_CLOSABLE = frozenset({"open", "claimed"})

#: stderr fragments meaning the shared ledger is not writable from this sandbox.
_READ_ONLY_MARKERS = ("read-only file system", "permission denied", "readonly database")

LedgerRunner = Callable[[list[str]], subprocess.CompletedProcess]


class IssueOutcome(BaseModel):
    """What happened to one linked ledger issue."""

    issue_id: str
    outcome: Literal["closed", "would-close", "skipped", "read-only", "error"]
    tasks: list[str] = Field(default_factory=list)
    resolved_by: str | None = None
    detail: str = ""


class CloseReport(BaseModel):
    """The JSON report printed for ``/sdd-done``."""

    feature_id: str | None
    base: str
    issues: list[IssueOutcome] = Field(default_factory=list)


def _frontmatter(text: str) -> str:
    """Return the YAML frontmatter block of a markdown document, or ``""``."""
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else ""


def _task_file(worktree: Path, task_id: str) -> Path | None:
    """Locate a task's markdown file in ``completed/`` (preferred) or ``active/``."""
    for folder in ("completed", "active"):
        matches = sorted((worktree / "sdd" / "tasks" / folder).glob(f"{task_id}-*.md"))
        if matches:
            return matches[0]
    return None


def collect_links(worktree: Path, index: dict) -> dict[str, set[str]]:
    """Map each linked ``issue:<id>`` to the task ids that resolve it.

    Args:
        worktree: Feature worktree root.
        index: Parsed per-spec index (header + ``tasks[]``).

    Returns:
        ``{issue_id: {task_id, ...}}``.
    """
    task_ids = [t["id"] for t in index.get("tasks", []) if t.get("id")]
    links: dict[str, set[str]] = {}
    for task_id in task_ids:
        path = _task_file(worktree, task_id)
        if path is None:
            continue
        for line in _DISCOVERED_RE.findall(path.read_text(encoding="utf-8")):
            for issue_id in _ISSUE_RE.findall(line):
                links.setdefault(issue_id, set()).add(task_id)
    spec = index.get("spec")
    if spec and (worktree / spec).is_file():
        for issue_id in _ISSUE_RE.findall(_frontmatter((worktree / spec).read_text(encoding="utf-8"))):
            links.setdefault(issue_id, set()).update(task_ids)
    return links


def _about_files(about: list[str]) -> set[str]:
    """Reduce ledger ``about`` refs (``sym:<path>#<symbol>``, ``file:<path>``) to repo paths."""
    files = set()
    for ref in about:
        _, _, rest = ref.partition(":")
        path = (rest or ref).split("#", 1)[0].strip()
        if path:
            files.add(path)
    return files


def _parse_json(stdout: str) -> dict:
    """Parse CLI JSON that may be preceded by a configuration banner on stdout."""
    start = stdout.find("{")
    if start == -1:
        raise ValueError("no JSON object in output")
    return json.loads(stdout[start:])


def _default_runner(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["wikitoolkit", "ledger", *args], capture_output=True, text=True, check=False)


def close_resolved_issues(
    *,
    worktree: Path,
    index_path: Path,
    base: str,
    feature_id: str | None = None,
    actor: str = "agent:sdd-done",
    dry_run: bool = False,
    changed_files: set[str] | None = None,
    ledger: LedgerRunner = _default_runner,
) -> CloseReport:
    """Close every linked issue that passes both keys; report the rest.

    Args:
        worktree: Feature worktree root.
        index_path: Per-spec index, absolute or relative to ``worktree``.
        base: Diff base ref (``origin/<base_branch>``).
        feature_id: Used in the close reason; defaults to the index header.
        actor: Ledger actor for ``ledger close``.
        dry_run: Evaluate and report without writing the ledger.
        changed_files: Override for ``git diff --name-only base...HEAD`` (tests).
        ledger: Runs ``wikitoolkit ledger <args>``; injectable for tests.

    Returns:
        The per-issue report.
    """
    index_file = index_path if index_path.is_absolute() else worktree / index_path
    index = json.loads(index_file.read_text(encoding="utf-8"))
    feature_id = feature_id or index.get("feature_id")
    report = CloseReport(feature_id=feature_id, base=base)

    links = collect_links(worktree, index)
    if not links:
        return report

    verified = {
        t["id"] for t in index.get("tasks", []) if t.get("status") == "done" and t.get("verification") == "verified"
    }
    if changed_files is None:
        diff = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = {line.strip() for line in diff.stdout.splitlines() if line.strip()}

    for issue_id in sorted(links):
        tasks = sorted(links[issue_id], key=lambda t: int(re.sub(r"\D", "", t) or 0))
        outcome = IssueOutcome(issue_id=issue_id, outcome="skipped", tasks=tasks)
        report.issues.append(outcome)

        shown = ledger(["show", issue_id, "--json"])
        try:
            issue = _parse_json(shown.stdout)["issue"]
        except (ValueError, KeyError) as exc:
            outcome.outcome = "error"
            outcome.detail = f"ledger show failed: {(shown.stderr or str(exc)).strip()[:200]}"
            continue
        if issue.get("status") not in _CLOSABLE:
            outcome.detail = f"already {issue.get('status')}"
            continue

        unverified = [t for t in tasks if t not in verified]
        if unverified:
            outcome.detail = f"linked task(s) not verified: {', '.join(unverified)}"
            continue
        touched = sorted(_about_files(issue.get("about") or []) & changed_files)
        if not touched:
            outcome.detail = f"none of the issue's files changed in {base}...HEAD"
            continue

        outcome.resolved_by = f"task:{tasks[0]}"
        reason = (
            f"Resolved by {feature_id or 'feature'} ({', '.join(tasks)}), verified by /sdd-done; "
            f"changed {', '.join(touched)}"
        )
        if dry_run:
            outcome.outcome = "would-close"
            outcome.detail = reason
            continue
        closed = ledger(["close", issue_id, "--reason", reason, "--actor", actor, "--resolved-by", outcome.resolved_by])
        if closed.returncode == 0:
            outcome.outcome = "closed"
            outcome.detail = reason
            continue
        err = (closed.stderr or closed.stdout or "").strip()
        outcome.outcome = "read-only" if any(m in err.lower() for m in _READ_ONLY_MARKERS) else "error"
        outcome.detail = err[:200]
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; prints the JSON report."""
    parser = argparse.ArgumentParser(description="Close the ledger issues a verified SDD feature resolved.")
    parser.add_argument("--worktree", type=Path, required=True, help="Feature worktree root.")
    parser.add_argument("--index", type=Path, required=True, help="Per-spec index (relative to the worktree).")
    parser.add_argument("--base", required=True, help="Diff base ref, e.g. origin/dev.")
    parser.add_argument("--feature-id", default=None)
    parser.add_argument("--actor", default="agent:sdd-done")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = close_resolved_issues(
        worktree=args.worktree.resolve(),
        index_path=args.index,
        base=args.base,
        feature_id=args.feature_id,
        actor=args.actor,
        dry_run=args.dry_run,
    )
    print(report.model_dump_json(indent=2))  # noqa: T201 — CLI output contract
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
