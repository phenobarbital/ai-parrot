"""Group selected targets into one pytest invocation per distribution (FEAT-563 M1)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .datatypes import CoreHit, PytestInvocation, ScopePlan, TestTarget
from .mirror import prune_nested
from .policy import AGENT_FLAGS, TIERS, ScopePolicy

# Decision from spike S2 (artifacts/logs/feat-563-s2-conftest-rootdir.md). Placeholders: {worktree}, {dist_root}.
PER_DIST_EXTRA_ARGS: tuple[str, ...] = ("--confcutdir", "{worktree}")

# Preference order when the same path is selected under two different reasons
# (lower index wins). Bounded by AC11.
_REASON_PRIORITY: dict[str, int] = {"declared": 0, "core": 1, "escalated": 2, "import": 3, "mirror": 4}


def _dist_root(distribution: str) -> str:
    """Repo-relative root of a distribution ('.' for the repo-root tests tree)."""
    return "." if distribution == "root" else f"packages/{distribution}"


def _invocation(
    distribution: str, targets: Sequence[TestTarget], *, worktree: Path, policy: ScopePolicy
) -> PytestInvocation:
    """Build the argv for one distribution's pruned targets."""
    kept_paths = prune_nested({t.path for t in targets})
    candidates = tuple(t for t in targets if t.path in kept_paths)
    # Dedupe by path (first reason wins, preferring declared > core > escalated > import > mirror).
    best: dict[str, TestTarget] = {}
    for candidate in candidates:
        current = best.get(candidate.path)
        if current is None or _REASON_PRIORITY.get(candidate.reason, len(_REASON_PRIORITY)) < _REASON_PRIORITY.get(
            current.reason, len(_REASON_PRIORITY)
        ):
            best[candidate.path] = candidate
    kept = tuple(sorted(best.values(), key=lambda t: t.path))
    xdist = ("-n", "auto") if distribution in policy.xdist_safe else ()
    extra = tuple(a.format(worktree=str(worktree), dist_root=_dist_root(distribution)) for a in PER_DIST_EXTRA_ARGS)
    argv = ("pytest", *AGENT_FLAGS, "-m", policy.marker_expression, *xdist, *extra, *kept_paths)
    return PytestInvocation(distribution=distribution, argv=argv, targets=kept)


def build_plan(
    targets: Sequence[TestTarget],
    *,
    tier: str,
    worktree: Path,
    policy: ScopePolicy,
    escalated: Sequence[str] = (),
    core_hits: Sequence[CoreHit] = (),
    skipped_escalations: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> ScopePlan:
    """Group by distribution, prune nested, add flags/markers/xdist → one PytestInvocation per group.

    Raises:
        ValueError: when ``tier`` is not one of ``TIERS``.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    groups: dict[str, list[TestTarget]] = {}
    for target in targets:
        groups.setdefault(target.distribution, []).append(target)
    invocations = tuple(_invocation(dist, groups[dist], worktree=worktree, policy=policy) for dist in sorted(groups))
    return ScopePlan(
        tier=tier,
        invocations=invocations,
        escalated=tuple(sorted(set(escalated))),
        core_hits=tuple(core_hits),
        skipped_escalations=tuple(sorted(set(skipped_escalations))),
        notes=tuple(notes),
    )
