"""Group selected targets into one pytest invocation per distribution (FEAT-563 M1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from .datatypes import CoreHit, Invocation, ScopePlan, TestContract, TestTarget
from .mirror import prune_nested
from .policy import AGENT_FLAGS, TIERS, ScopePolicy
from .runners.registry import RunnerRegistry, load_registry

# Decision from spike S2 (artifacts/logs/feat-563-s2-conftest-rootdir.md). Placeholders: {worktree}, {dist_root}.
PER_DIST_EXTRA_ARGS: tuple[str, ...] = ("--confcutdir", "{worktree}")

# Preference order when the same path is selected under two different reasons
# (lower index wins). Bounded by AC11.
_REASON_PRIORITY: dict[str, int] = {"declared": 0, "contract": 1, "core": 2, "escalated": 3, "import": 4, "mirror": 5}
OVERRIDE_MARKER_EXPRESSION: str = "not real_llm"


def _contract_markers(contract: TestContract | None) -> tuple[str, ...]:
    """Return normalized marker names from the contract's pytest runner."""
    block = contract.pytest if contract is not None else None
    raw = block.settings.get("markers", "") if block is not None else ""
    return tuple(marker for marker in raw.split(",") if marker)


def marker_expression_for(targets: Sequence[TestTarget], *, contract: TestContract | None, policy: ScopePolicy) -> str:
    """Return the permissive marker expression for an all-contract invocation."""
    if contract is not None and targets and all(target.reason == "contract" for target in targets):
        return OVERRIDE_MARKER_EXPRESSION
    return policy.marker_expression


def _dist_root(distribution: str) -> str:
    """Repo-relative root of a distribution ('.' for the repo-root tests tree)."""
    return "." if distribution == "root" else f"packages/{distribution}"


def _invocation(
    distribution: str,
    targets: Sequence[TestTarget],
    *,
    worktree: Path,
    policy: ScopePolicy,
    marker_expression: str | None = None,
) -> Invocation:
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
    expression = marker_expression or policy.marker_expression
    argv = ("pytest", *AGENT_FLAGS, "-m", expression, *xdist, *extra, *kept_paths)
    return Invocation(distribution=distribution, argv=argv, targets=kept)


def build_plan(
    targets: Sequence[TestTarget],
    *,
    tier: str,
    worktree: Path,
    policy: ScopePolicy,
    escalated: Sequence[str] = (),
    core_hits: Sequence[CoreHit] = (),
    skipped_escalations: Sequence[str] = (),
    cap_hits: Mapping[str, tuple[str, ...]] | None = None,
    cap_impacted: Mapping[str, str] | None = None,
    notes: Sequence[str] = (),
    contract: TestContract | None = None,
    mode: str = "fallback",
    registry: RunnerRegistry | None = None,
) -> ScopePlan:
    """Group targets by runner/distribution and construct runner-owned invocations.

    Raises:
        ValueError: when ``tier`` is not one of ``TIERS``.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    registry = registry or load_registry(worktree)
    groups: dict[tuple[str, str], list[TestTarget]] = {}
    for target in targets:
        groups.setdefault((target.runner, target.distribution), []).append(target)

    invocations: list[Invocation] = []
    for runner, distribution in sorted(groups):
        group = groups[(runner, distribution)]
        adapter = registry.adapter_for_kind(runner)
        settings = registry.settings_for(runner)
        if runner != "pytest":
            invocations.append(
                adapter.invocation(
                    group,
                    distribution=distribution,
                    worktree=worktree,
                    settings=settings,
                    policy=policy,
                    report_path="",
                )
            )
            continue

        contract_paths = {target.path for target in group if target.reason == "contract"}
        default_targets = [target for target in group if target.path not in contract_paths]
        contract_targets = [target for target in group if target.reason == "contract"]

        if default_targets:
            invocations.append(
                adapter.invocation(
                    default_targets,
                    distribution=distribution,
                    worktree=worktree,
                    settings=settings,
                    policy=policy,
                    report_path="",
                )
            )
        if contract_targets:
            invocations.append(
                _invocation(
                    distribution,
                    contract_targets,
                    worktree=worktree,
                    policy=policy,
                    marker_expression=marker_expression_for(contract_targets, contract=contract, policy=policy),
                )
            )
            markers = _contract_markers(contract)
            if markers:
                tests_root = "tests" if distribution == "root" else f"packages/{distribution}/tests"
                marker_target = TestTarget(path=tests_root, distribution=distribution, reason="contract")
                marker_expression = f"({' or '.join(markers)}) and {OVERRIDE_MARKER_EXPRESSION}"
                invocations.append(
                    _invocation(
                        distribution,
                        (marker_target,),
                        worktree=worktree,
                        policy=policy,
                        marker_expression=marker_expression,
                    )
                )
    return ScopePlan(
        tier=tier,
        invocations=tuple(invocations),
        escalated=tuple(sorted(set(escalated))),
        core_hits=tuple(core_hits),
        skipped_escalations=tuple(sorted(set(skipped_escalations))),
        notes=tuple(notes),
        cap_hits=dict(cap_hits or {}),
        cap_impacted=dict(cap_impacted or {}),
        mode=mode,
    )
