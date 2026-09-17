"""Tier entry point for the test-scope kernel (FEAT-563)."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath
from typing import Sequence

from .context import pending_escalations
from .contract import is_broad_pytest
from .datatypes import CoreHit, ScopePlan, TestTarget
from .impact import ImportIndex, detect_core, impacted_tests
from .mirror import distribution_of, pytest_targets
from .planner import build_plan
from .policy import TIERS, ScopePolicy

_FLAG_WITH_VALUE = frozenset({"-m", "-k", "-o", "-p", "-c", "-n", "--rootdir", "--confcutdir", "--tb", "--ignore"})
_PYTEST_MODULE_FORMS = (("python", "-m", "pytest"), ("python3", "-m", "pytest"))


def changed_files(worktree: Path, base_ref: str) -> list[str]:
    """`git diff --name-only --diff-filter=d <base>...HEAD` ∪ uncommitted/untracked paths; [] on git failure."""
    files: list[str] = []
    seen: set[str] = set()
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", f"{base_ref}...HEAD"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        diff = None
    if diff is not None and diff.returncode == 0:
        for line in diff.stdout.splitlines():
            path = line.strip()
            if path and path not in seen:
                seen.add(path)
                files.append(path)
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        status = None
    if status is not None and status.returncode == 0:
        for line in status.stdout.splitlines():
            if len(line) < 4:
                continue
            code, path = line[:2], line[3:].strip()
            if "D" in code:
                continue  # deleted — consistent with the diff's --diff-filter=d
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _suite_for(distribution: str, worktree: Path) -> str | None:
    """Package-suite path of a distribution (`tests` for root), or None when it does not exist."""
    rel = "tests" if distribution == "root" else f"packages/{distribution}/tests"
    return rel if (worktree / rel).is_dir() else None


def _operands(argv: Sequence[str]) -> list[str]:
    """Non-flag operands of a (already known non-broad) pytest argv, `::node` suffix kept."""
    if not argv:
        return []
    head = PurePosixPath(argv[0]).name
    if head == "pytest":
        rest = list(argv[1:])
    elif len(argv) >= 3 and (head, argv[1], argv[2]) in _PYTEST_MODULE_FORMS:
        rest = list(argv[3:])
    else:
        return []
    operands: list[str] = []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("-"):
            if token in _FLAG_WITH_VALUE and "=" not in token:
                i += 2
                continue
            i += 1
            continue
        operands.append(token)
        i += 1
    return operands


def _declared_targets(declared: Sequence[Sequence[str]], notes: list[str], *, worktree: Path) -> list[str]:
    """Path operands of declared pytest argvs; broad ones (or unmappable ones) are dropped with a note."""
    targets: list[str] = []
    for argv in declared:
        if not argv:
            continue
        if is_broad_pytest(argv, worktree=worktree):
            notes.append(f"declared command is over-broad, dropped: {' '.join(argv)}")
            continue
        for operand in _operands(argv):
            try:
                distribution_of(operand.split("::", 1)[0])
            except ValueError:
                notes.append(f"declared path does not map to a distribution, dropped: {operand}")
                continue
            targets.append(operand)
    return targets


def _dist(path: str) -> str:
    """`distribution_of`, stripping a `::node` suffix first."""
    return distribution_of(path.split("::", 1)[0])


def plan_tests(
    *,
    worktree: Path,
    changed_files: Sequence[str],
    tier: str,
    declared: Sequence[Sequence[str]] = (),
    policy: ScopePolicy | None = None,
) -> ScopePlan:
    """Tier entry point: task=declared∪mirror (no escalation); merge=mirror∪impact∪core (cap→escalate);
    feature=declared∪mirror∪core; core escalations deduped by the ledger."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    policy = policy or ScopePolicy()
    notes: list[str] = []
    targets = [
        TestTarget(path=p, distribution=_dist(p), reason="declared")
        for p in _declared_targets(declared, notes, worktree=worktree)
    ]
    targets += [
        TestTarget(path=p, distribution=_dist(p), reason="mirror")
        for p in pytest_targets(list(changed_files), str(worktree))
    ]
    escalated: list[str] = []
    hits: list[CoreHit] = []
    skipped: list[str] = []
    if tier != "task":
        try:
            is_git = (
                subprocess.run(
                    ["git", "rev-parse", "--is-inside-work-tree"],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=False,
                ).returncode
                == 0
            )
        except OSError:
            is_git = False

        index: ImportIndex | None = None
        if not is_git:
            notes.append("worktree is not a git repository; skipping the import index (no impact/core detection)")
        else:
            try:
                index = ImportIndex.load_or_build(worktree)
            except OSError:
                notes.append("could not build the import index; skipping impact/core detection")

        if index is not None and tier == "merge":
            impacted = impacted_tests(index, list(changed_files), worktree=worktree, depth=policy.impact_depth)
            by_dist: dict[str, list[str]] = {}
            for path in impacted:
                by_dist.setdefault(_dist(path), []).append(path)
            for dist, paths in by_dist.items():
                if len(paths) > policy.impact_cap:
                    escalated.append(dist)
                    suite = _suite_for(dist, worktree)
                    if suite:
                        targets.append(TestTarget(path=suite, distribution=dist, reason="escalated"))
                    notes.append(
                        f"{dist}: {len(paths)} impacted tests exceed cap {policy.impact_cap}, escalated to suite"
                    )
                else:
                    targets += [TestTarget(path=path, distribution=dist, reason="import") for path in paths]

        if index is not None and tier in ("merge", "feature"):
            hits = detect_core(index, list(changed_files), policy=policy)
            if hits:
                to_run, ledger_skipped = pending_escalations(worktree, hits)
                skipped = ledger_skipped
                for dist in to_run:
                    suite = _suite_for(dist, worktree)
                    if suite:
                        targets.append(TestTarget(path=suite, distribution=dist, reason="core"))
                        # FEAT-563 review (I1): `escalated` used to be impact-cap-only, so a
                        # core-only escalation was invisible to the plain-text CLI ("# escalated:
                        # <dist>") and to the spec's own datatypes.py contract ("distributions
                        # escalated (core or cap)"). Both escalation kinds are visible here now;
                        # `core_hits`/`reason=="core"` targets remain the authoritative source
                        # every real consumer (the ledger, QANode) already reads.
                        escalated.append(dist)
                    else:
                        notes.append(f"{dist}: core escalation target suite does not exist, skipped")

    return build_plan(
        targets,
        tier=tier,
        worktree=worktree,
        policy=policy,
        escalated=escalated,
        core_hits=hits,
        skipped_escalations=skipped,
        notes=notes,
    )
