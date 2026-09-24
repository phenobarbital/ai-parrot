"""Runtime delta eligibility, merge and validation (FEAT-585 M5, goal D2).

A ``PlanDelta`` is deliberately not a standalone plan: a replacement node may
depend on a successful node that is not itself part of the delta (finding
R5). So the delta is merged into the original node set, the merged
``ExecutionPlan`` is validated with the frozen ``validate_with_allowlist``
(``catalog.py:145``), and the toolkit-specific invariants — eligibility,
protected ids, identity preservation, key collisions and allowlist
intersection — are checked on top, never patched into the frozen validator.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Sequence

from parrot.bots.flows.plan import DelegatePlanNode, ExecutionPlan, PlanNode
from parrot.bots.flows.plan.validator import ValidationIssue, ValidationReport

from .catalog import validate_with_allowlist
from .models import PlanDelta, PlanRun

__all__ = ("eligible_repair_nodes", "merge_delta", "protected_node_ids", "validate_delta")

_REPAIRABLE_RUN_STATUSES = frozenset({"failed", "partial"})


def eligible_repair_nodes(run: PlanRun) -> FrozenSet[str]:
    """Return the node ids a repair delta may replace.

    Eligible ids are the explicit error refs (which ``project_run``
    synthesizes for both recorded hard failures and never-dispatched nodes
    of a terminal run as ``status="error"``), and only when the run itself
    is terminal-failed or terminal-partial. ``partial`` refs are never
    eligible (D2, spec §1 Non-Goals last bullet): a fan-out that partially
    succeeded is not reclassified as a failure.

    Args:
        run: The terminal run being repaired.

    Returns:
        The frozen set of eligible node ids; empty for a ``running`` or
        ``completed`` run.
    """
    if run.status not in _REPAIRABLE_RUN_STATUSES:
        return frozenset()
    return frozenset(ref.node_id for ref in run.refs if ref.status == "error")


def protected_node_ids(run: PlanRun) -> FrozenSet[str]:
    """Return every node id that must not be replaced or re-executed.

    Args:
        run: The terminal run being repaired.

    Returns:
        Every plan node id not returned by :func:`eligible_repair_nodes`
        (ok / skipped / partial nodes).
    """
    eligible = eligible_repair_nodes(run)
    return frozenset(node.id for node in run.metadata.plan.nodes if node.id not in eligible)


def merge_delta(plan: ExecutionPlan, delta: PlanDelta) -> ExecutionPlan:
    """Merge a delta's replacement nodes into ``plan``, in original order.

    Args:
        plan: The plan the delta is being applied to.
        delta: Replacement nodes, keyed by their existing id.

    Returns:
        A new :class:`ExecutionPlan` with replaced nodes swapped in place;
        node order and plan-level ``name``/``objective``/``metadata`` are
        unchanged.

    Raises:
        ValueError: If ``delta`` names an id that is not in ``plan`` — a
        delta may never add nodes, so an unknown id must fail loudly rather
        than be silently appended or dropped.
    """
    replacements: Dict[str, PlanNode] = {node.id: node for node in delta.nodes}
    unknown = set(replacements) - {node.id for node in plan.nodes}
    if unknown:
        raise ValueError(f"delta names ids not in the plan: {sorted(unknown)}")
    merged = [replacements.get(node.id, node) for node in plan.nodes]
    return ExecutionPlan(name=plan.name, objective=plan.objective, nodes=merged, metadata=plan.metadata)


def validate_delta(
    delta: PlanDelta,
    *,
    run: PlanRun,
    tool_manager: Any,
    allowed_tools: Sequence[str],
    delegates: Optional[Sequence[Any]] = None,
    allow_delegate_side_effects: bool = False,
) -> ValidationReport:
    """Validate a repair delta's toolkit invariants, then the merged plan.

    Args:
        delta: Replacement nodes proposed for the repair.
        run: The terminal run being repaired.
        tool_manager: Live manager forwarded to ``validate_with_allowlist``.
        allowed_tools: Current host policy allowlist. Intersected with
            ``run.metadata.allowed_tools`` — the effective allowlist is
            never widened relative to what the run was originally accepted
            with.
        delegates: Delegate chain forwarded to ``validate_with_allowlist``.
        allow_delegate_side_effects: Host delegate side-effect policy
            forwarded to ``validate_with_allowlist``.

    Returns:
        A :class:`ValidationReport`. Toolkit-invariant errors short-circuit
        before the merge (a delta that fails identity/eligibility checks is
        never merged), otherwise the report from
        ``validate_with_allowlist(merged, tool_manager, effective_allowlist)``.
    """
    plan = run.metadata.plan
    original: Dict[str, PlanNode] = {node.id: node for node in plan.nodes}
    protected = protected_node_ids(run)
    effective_allowlist = sorted(set(run.metadata.allowed_tools) & set(allowed_tools))  # never widened
    successful_keys = {key for ref in run.refs if ref.status == "ok" for key in ref.keys}
    issues: List[ValidationIssue] = []
    for node in delta.nodes:
        if node.id not in original:
            issues.append(ValidationIssue(node_id=node.id, code="delta_new_id", message="delta may not add nodes"))
            continue
        if node.id in protected:
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_protected_id",
                    message="node is ok/skipped/partial; not repairable",
                )
            )
        original_node = original[node.id]
        if isinstance(original_node, DelegatePlanNode):
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_delegate_not_repairable",
                    message="delegate nodes are not repairable in v1; the delta may only replace tool nodes",
                )
            )
            continue
        if node.store_as != original_node.store_as:
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_store_as_changed",
                    message=(
                        f"replacement store_as {node.store_as!r} differs from the original "
                        f"{original_node.store_as!r}"
                    ),
                )
            )
        if set(node.depends_on) != set(original_node.depends_on):
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_depends_on_changed",
                    message=(
                        f"replacement depends_on {sorted(node.depends_on)} differs from the original "
                        f"{sorted(original_node.depends_on)}"
                    ),
                )
            )
        if _for_each_identity_changed(original_node, node):
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_for_each_identity_changed",
                    message="replacement changes fan-out identity (presence, source, select or skip_existing)",
                )
            )
        if node.store_as in successful_keys:
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_key_collision",
                    message=f"store_as {node.store_as!r} collides with a successful node's artifact key",
                )
            )
        if node.tool not in effective_allowlist:
            issues.append(
                ValidationIssue(
                    node_id=node.id,
                    code="delta_tool_not_allowed",
                    message=f"tool {node.tool!r} is not in the effective allowlist {effective_allowlist}",
                )
            )
    if issues:
        return ValidationReport(issues=issues)
    merged = merge_delta(plan, delta)
    return validate_with_allowlist(
        merged,
        tool_manager,
        effective_allowlist,
        delegates=delegates,
        allow_delegate_side_effects=allow_delegate_side_effects,
    )


def _for_each_identity_changed(original_node: PlanNode, replacement: PlanNode) -> bool:
    """Whether a replacement node's fan-out identity differs from the original.

    Fan-out identity is presence of ``for_each`` plus its ``source``,
    ``select`` and ``skip_existing`` — the parts that determine what is
    iterated and whether an already-produced item is skipped, not
    concurrency/error-handling knobs the planner may still tune.

    Args:
        original_node: The node currently in the plan.
        replacement: The delta's proposed replacement.

    Returns:
        ``True`` when ``for_each`` was added, removed, or its identity
        fields changed.
    """
    original_fe = original_node.for_each
    replacement_fe = replacement.for_each
    if (original_fe is None) != (replacement_fe is None):
        return True
    if original_fe is None or replacement_fe is None:
        return False
    return (
        original_fe.source != replacement_fe.source
        or original_fe.select != replacement_fe.select
        or original_fe.skip_existing != replacement_fe.skip_existing
    )
