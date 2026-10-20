"""Tier entry point for the test-scope kernel (FEAT-563)."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath
from typing import Sequence

from .datatypes import CoreHit, ScopePlan, TestContract, TestTarget
from .impact import ImportIndex, detect_core, impacted_tests, module_name_for
from .mirror import distribution_of
from .planner import build_plan
from .policy import TIERS, ScopePolicy
from .runners.registry import RunnerRegistry, load_registry

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


def _declared_targets(
    declared: Sequence[Sequence[str]],
    notes: list[str],
    *,
    worktree: Path,
    registry: RunnerRegistry | None = None,
    tier: str = "task",
) -> list[TestTarget]:
    """Return bounded declared targets classified by their registered runner."""
    registry = registry or load_registry(worktree)
    targets: list[TestTarget] = []
    for argv in declared:
        if not argv:
            continue
        adapter = registry.adapter_for_argv(argv)
        if adapter is None:
            continue
        if tier not in registry.tiers_for(adapter.kind):
            notes.append(f"{adapter.kind}: not eligible for tier {tier}")
            continue
        if adapter.is_broad(argv, worktree=worktree):
            notes.append(f"declared command is over-broad, dropped: {' '.join(argv)}")
            continue
        for operand in adapter.operands(argv) or ():
            try:
                distribution = adapter.distribution_of(operand.split("::", 1)[0], settings=registry.settings_for(adapter.kind))
            except ValueError:
                notes.append(f"declared path does not map to a distribution, dropped: {operand}")
                continue
            targets.append(TestTarget(operand, distribution, "declared", runner=adapter.kind))
    return targets


def _dist(path: str) -> str:
    """`distribution_of`, stripping a `::node` suffix first."""
    return distribution_of(path.split("::", 1)[0])


def _dist_or_none(path: str) -> str | None:
    """`_dist`, or None for a path under neither `tests/` nor `packages/<dist>/`."""
    try:
        return _dist(path)
    except ValueError:
        return None


def plan_tests(
    *,
    worktree: Path,
    changed_files: Sequence[str],
    tier: str,
    declared: Sequence[Sequence[str]] = (),
    contract: TestContract | None = None,
    policy: ScopePolicy | None = None,
    registry: RunnerRegistry | None = None,
) -> ScopePlan:
    """Plan bounded tests using either a declared contract or direct-import fallback."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    policy = policy or ScopePolicy()
    registry = registry or load_registry(worktree)
    mode = "contract" if contract is not None else "fallback"
    notes: list[str] = []
    targets = _declared_targets(declared, notes, worktree=worktree, registry=registry, tier=tier)
    if contract is None:
        runner_blocks = (("pytest", registry.settings_for("pytest"), registry.tiers_for("pytest")),)
    else:
        runner_blocks = tuple((block.kind, block.settings, block.tiers) for block in contract.runners)
    for kind, settings, contract_tiers in runner_blocks:
        if tier not in contract_tiers or tier not in registry.tiers_for(kind):
            notes.append(f"{kind}: not eligible for tier {tier}")
            continue
        adapter = registry.adapter_for_kind(kind)
        targets += [
            TestTarget(
                path=path,
                distribution=adapter.distribution_of(path, settings=settings),
                reason="mirror",
                runner=kind,
            )
            for path in adapter.mirror_targets(list(changed_files), worktree=worktree, settings=settings)
        ]
    hits: list[CoreHit] = []

    if tier != "task" and contract is not None:
        for runner in contract.runners:
            if tier not in runner.tiers or tier not in registry.tiers_for(runner.kind):
                continue
            adapter = registry.adapter_for_kind(runner.kind)
            for operand in runner.targets or ("",):
                operand_path = operand.split("::", 1)[0]
                if operand_path and not (worktree / operand_path).is_file():
                    notes.append(f"contract operand missing on disk, skipped: {operand}")
                    continue
                targets.append(
                    TestTarget(
                        path=operand,
                        distribution=adapter.distribution_of(operand_path, settings=runner.settings),
                        reason="contract",
                        runner=runner.kind,
                    )
                )

    if tier != "task":
        index: ImportIndex | None = None
        package_sources_changed = any(module_name_for(path) is not None for path in changed_files)
        if contract is None or package_sources_changed:
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
            if not is_git:
                notes.append("worktree is not a git repository; skipping the import index (no impact/core detection)")
            else:
                try:
                    index = ImportIndex.load_or_build(worktree)
                except OSError:
                    notes.append("could not build the import index; skipping impact/core detection")

        if index is not None and contract is None:
            impacted = impacted_tests(index, list(changed_files), worktree=worktree, depth=1)
            by_dist: dict[str, list[str]] = {}
            for path in impacted:
                by_dist.setdefault(_dist(path), []).append(path)
            for dist, paths in by_dist.items():
                paths = sorted(paths)
                if len(paths) > policy.impact_cap:
                    notes.append(
                        f"{dist}: {len(paths)} impacted tests exceed cap {policy.impact_cap}; "
                        f"kept {policy.impact_cap}, rest covered by nightly"
                    )
                targets += [
                    TestTarget(path=path, distribution=dist, reason="import") for path in paths[: policy.impact_cap]
                ]

        if index is not None:
            hits = detect_core(index, list(changed_files), policy=policy)
            if hits:
                hit_paths = ", ".join(hit.path for hit in hits)
                notes.append(f"core change ({hit_paths}) — covered by nightly")

    if contract is None:
        notes.append("no test contract declared — bounded fallback (own tests + direct importers)")

    return build_plan(
        targets,
        tier=tier,
        worktree=worktree,
        policy=policy,
        core_hits=hits,
        notes=notes,
        contract=contract,
        mode=mode,
        registry=registry,
    )
