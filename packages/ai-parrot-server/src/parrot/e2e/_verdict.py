"""Shared required-node verdict computation for the E2E runner and evidence verifier.

Both :func:`parrot.e2e.runner._verdict_status` and
:func:`parrot.e2e.evidence.verify_evidence` must agree on whether a required
node is satisfied; this module is the single place that decides it.
"""

from __future__ import annotations

from typing import Iterable, Literal, Mapping, NamedTuple

from parrot.e2e.models import ScenarioResult

FindingKind = Literal["missing", "blocked", "not_passed", "phase_failure"]


class NodeFinding(NamedTuple):
    """One unsatisfied required node.

    Attributes:
        node_id: The required pytest node ID.
        kind: ``missing`` (no result), ``blocked`` (result outcome blocked),
            ``not_passed`` (any other non-passed outcome) or ``phase_failure``
            (passed outcome with a non-passed setup/call/teardown phase).
        reason_code: Machine-readable reason, e.g. ``required_node_missing:<id>``.
    """

    node_id: str
    kind: FindingKind
    reason_code: str


def evaluate_required_nodes(
    required_node_ids: Iterable[str],
    results_by_node: Mapping[str, ScenarioResult],
    *,
    check_phases: bool = False,
) -> list[NodeFinding]:
    """Return one finding per unsatisfied required node (empty means all satisfied).

    Args:
        required_node_ids: Node IDs that must have passed.
        results_by_node: Recorded results keyed by node ID.
        check_phases: Also require clean setup/call/teardown phases.

    Returns:
        Findings in sorted node order.
    """
    findings: list[NodeFinding] = []
    for node_id in sorted(set(required_node_ids)):
        result = results_by_node.get(node_id)
        if result is None:
            findings.append(NodeFinding(node_id, "missing", f"required_node_missing:{node_id}"))
        elif result.outcome == "blocked":
            findings.append(NodeFinding(node_id, "blocked", f"required_node_not_passed:{node_id}:blocked"))
        elif result.outcome != "passed":
            findings.append(
                NodeFinding(node_id, "not_passed", f"required_node_not_passed:{node_id}:{result.outcome}")
            )
        elif check_phases:
            for phase in ("setup", "call", "teardown"):
                if getattr(result, f"{phase}_outcome") not in (None, "passed"):
                    findings.append(NodeFinding(node_id, "phase_failure", f"required_node_{phase}_failure:{node_id}"))
    return findings
