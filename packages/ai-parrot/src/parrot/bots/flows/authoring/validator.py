"""Semantic validation of a blueprint against the live component catalog.

Pydantic already enforces the blueprint's internal consistency (id shape,
required-field combinations, unique ids). This module adds everything that
needs the environment:

* every ``tools``/``tool`` name exists in the catalog
* every ``agent_ref`` is a registered agent (when the engine needs one)
* every ``kind`` is available for the chosen engine
* ``config`` validates against the node type's declared config model
* transitions resolve, the graph is acyclic, and it has one entry point
* every CEL predicate compiles *and* only reads variables that exist

That last check earns its place. ``CELPredicateEvaluator`` is fail-safe: any
evaluation error returns ``False`` and logs a warning, so a predicate reading
a misspelled field never errors — the branch simply never fires, and the
workflow silently takes the wrong path. Catching it here converts a silent
behavioural bug into a loud, fixable one. This is the same reasoning behind
``parrot.bots.flows.plan.validator``, whose ``ValidationIssue`` shape is
reused verbatim so issue text can be fed straight back to a repair round.

Issue messages are written to be actionable by the model that produced the
blueprint: they name the offending node, say what was wrong, and list what
was actually available.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .blueprint import WorkflowBlueprint
from .catalog import ComponentCatalog
from .contracts import CapabilityGap

__all__ = (
    "ValidationIssue",
    "ValidationReport",
    "validate_blueprint",
)

logger = logging.getLogger(__name__)

#: The complete activation surface of ``CELPredicateEvaluator``: a predicate
#: may read ``result``, ``error`` and ``ctx`` and nothing else.
_CEL_ROOTS = frozenset({"result", "error", "ctx"})

#: Leading identifier of a CEL expression term, e.g. ``result`` in
#: ``result.final_decision == "Pizza"``. The lookbehind is what makes it a
#: *root*: an identifier preceded by a dot is a field of something else and
#: must not be mistaken for a variable of its own. Quoted strings are
#: stripped first so words inside literals are not matched either.
_CEL_ROOT_RE = re.compile(r"(?<![.\w])([A-Za-z_][A-Za-z0-9_]*)")
_CEL_STRING_RE = re.compile(r"'[^']*'|\"[^\"]*\"")

#: CEL keywords and literals that are not variable references.
_CEL_RESERVED = frozenset(
    {"true", "false", "null", "in", "has", "size", "int", "double", "string", "bool"}
)


@dataclass(frozen=True)
class ValidationIssue:
    """A single finding.

    Attributes:
        node_id: Offending node, or ``None`` for a workflow-level issue.
        code: Stable machine-readable identifier.
        message: Human-readable explanation, phrased so the authoring model
            can correct the blueprint directly from it.
        severity: ``error`` blocks compilation; ``warning`` does not.
    """

    node_id: Optional[str]
    code: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        where = f"node {self.node_id!r}: " if self.node_id else ""
        return f"[{self.severity}:{self.code}] {where}{self.message}"


@dataclass
class ValidationReport:
    """Aggregated validation result."""

    issues: List[ValidationIssue] = field(default_factory=list)
    capability_gaps: List[CapabilityGap] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        """Blocking issues."""
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Non-blocking issues."""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        """``True`` when nothing blocks compilation."""
        return not self.errors

    def add(
        self,
        node_id: Optional[str],
        code: str,
        message: str,
        severity: str = "error",
    ) -> None:
        """Append one issue."""
        self.issues.append(ValidationIssue(node_id, code, message, severity))

    def raise_for_errors(self) -> None:
        """Raise when any blocking issue is present.

        Raises:
            ValueError: With every error rendered, one per line.
        """
        if self.errors:
            raise ValueError(
                "Blueprint validation failed:\n"
                + "\n".join(str(issue) for issue in self.errors)
            )

    def __str__(self) -> str:
        return "\n".join(str(issue) for issue in self.issues) or "(no issues)"


def _closest(name: str, candidates: Sequence[str], limit: int = 3) -> List[str]:
    """Return the nearest catalog names to ``name``.

    A near-miss is by far the most common failure (``s3_filter_report`` for
    ``s3_filter_reports``), and naming the alternatives is what lets a repair
    round succeed in one pass instead of guessing again.

    Args:
        name: The unresolved name.
        candidates: Available names.
        limit: How many suggestions to return.

    Returns:
        Up to ``limit`` close matches, best first.
    """
    import difflib  # noqa: PLC0415 — only needed on the error path

    return difflib.get_close_matches(name, list(candidates), n=limit, cutoff=0.6)


def _cel_roots(expression: str) -> set[str]:
    """Extract the root identifiers a CEL expression reads.

    Args:
        expression: The predicate source.

    Returns:
        Root identifiers, excluding literals and reserved words.
    """
    stripped = _CEL_STRING_RE.sub(" ", expression)
    return {
        match.group(1)
        for match in _CEL_ROOT_RE.finditer(stripped)
        if match.group(1) not in _CEL_RESERVED
    }


def _validate_predicate(
    report: ValidationReport, predicate: str, where: str
) -> None:
    """Check that a CEL predicate compiles and reads only real variables."""
    try:
        from parrot.bots.flows.flow.cel_evaluator import (  # noqa: PLC0415
            CELPredicateEvaluator,
        )

        CELPredicateEvaluator(predicate)
    except ImportError:  # pragma: no cover - celpy not installed
        report.add(
            None,
            "cel_unavailable",
            f"Could not compile the predicate for {where}: the CEL evaluator "
            "is unavailable in this environment.",
            severity="warning",
        )
        return
    except Exception as exc:
        report.add(
            None,
            "predicate_invalid",
            f"Predicate for {where} does not compile: {exc}. Expression was: "
            f"{predicate!r}",
        )
        return

    unknown = sorted(_cel_roots(predicate) - _CEL_ROOTS)
    if unknown:
        report.add(
            None,
            "predicate_unknown_variable",
            f"Predicate for {where} reads {unknown}, which are not in scope. "
            f"Only {sorted(_CEL_ROOTS)} are available ('result' is the source "
            "node's output, 'error' its error string, 'ctx' the shared "
            "context). Note that CEL evaluation is fail-safe: an unknown name "
            "makes the predicate silently false, so this branch would never "
            "be taken.",
        )


def validate_blueprint(
    blueprint: WorkflowBlueprint,
    catalog: ComponentCatalog,
) -> ValidationReport:
    """Validate ``blueprint`` against the live ``catalog``.

    Args:
        blueprint: The assembled blueprint.
        catalog: Catalog built from the live registries.

    Returns:
        A report carrying every issue and every capability gap. Callers
        decide whether to repair, degrade or fail.
    """
    report = ValidationReport()
    engine = blueprint.engine
    known_tools = catalog.tool_names()
    known_agents = catalog.agent_names()
    available_kinds = set(catalog.kinds_for(engine))

    node_ids = set(blueprint.node_ids())

    for node in blueprint.nodes:
        _validate_node(
            report,
            node,
            engine=engine,
            catalog=catalog,
            known_tools=known_tools,
            known_agents=known_agents,
            available_kinds=available_kinds,
        )

    _validate_shared_tools(report, blueprint, known_tools)
    _validate_transitions(report, blueprint, node_ids, engine)

    return report


def _validate_node(
    report: ValidationReport,
    node,
    *,
    engine: str,
    catalog: ComponentCatalog,
    known_tools: set,
    known_agents: set,
    available_kinds: set,
) -> None:
    """Validate one node against the catalog."""
    if node.kind not in available_kinds:
        report.add(
            node.id,
            "kind_unavailable",
            f"kind {node.kind!r} is not available for engine {engine!r}. "
            f"Available kinds: {sorted(available_kinds)}.",
        )
        report.capability_gaps.append(
            CapabilityGap(
                kind="node_type",
                requested=node.kind,
                reason=f"Not supported by engine {engine!r}.",
                suggestion=(
                    "Use engine='flow'" if engine == "crew" else None
                ),
                node_id=node.id,
            )
        )

    # Tools referenced by an agent, and the tool a tool-node executes.
    for tool_name in list(node.tools) + ([node.tool] if node.tool else []):
        if tool_name in known_tools:
            continue
        suggestions = _closest(tool_name, sorted(known_tools))
        report.add(
            node.id,
            "tool_not_found",
            f"tool {tool_name!r} is not in the catalog."
            + (f" Closest available: {suggestions}." if suggestions else "")
            + " Never invent a tool name — use one from the catalog or drop it.",
        )
        report.capability_gaps.append(
            CapabilityGap(
                kind="tool",
                requested=tool_name,
                reason="No such tool is registered on this platform.",
                suggestion=suggestions[0] if suggestions else None,
                node_id=node.id,
            )
        )

    if node.kind == "agent":
        if engine == "flow":
            if not node.agent_ref:
                report.add(
                    node.id,
                    "agent_ref_required",
                    "engine='flow' resolves agents from the AgentRegistry, so "
                    "this node must set 'agent_ref'. Use engine='crew' to "
                    "define a new agent inline instead.",
                )
            elif node.agent_ref not in known_agents:
                suggestions = _closest(node.agent_ref, sorted(known_agents))
                report.add(
                    node.id,
                    "agent_not_found",
                    f"agent_ref {node.agent_ref!r} is not registered."
                    + (f" Closest available: {suggestions}." if suggestions else ""),
                )
                report.capability_gaps.append(
                    CapabilityGap(
                        kind="agent",
                        requested=node.agent_ref,
                        reason="Not present in the AgentRegistry.",
                        suggestion=suggestions[0] if suggestions else None,
                        node_id=node.id,
                    )
                )
        elif not node.system_prompt:
            report.add(
                node.id,
                "system_prompt_missing",
                "engine='crew' constructs this agent inline, so it needs a "
                "'system_prompt' describing its role.",
                severity="warning",
            )

    _validate_node_config(report, node, catalog)


def _validate_node_config(report: ValidationReport, node, catalog: ComponentCatalog) -> None:
    """Validate ``node.config`` against its node type's declared model."""
    entry = catalog.node_type(node.kind)
    if entry is None or not entry.config_schema:
        if node.config and node.kind in {"agent", "tool"}:
            report.add(
                node.id,
                "config_unexpected",
                f"kind {node.kind!r} takes no 'config' block; put tool "
                "arguments in 'args'/'kwargs' and agent settings in the "
                "dedicated fields.",
                severity="warning",
            )
        return

    from parrot.bots.flows.flow.flow import NODE_CONFIG_MODELS  # noqa: PLC0415

    model = NODE_CONFIG_MODELS.get(node.kind)
    if model is None:
        return
    try:
        model.model_validate(node.config or {})
    except Exception as exc:
        report.add(
            node.id,
            "config_invalid",
            f"'config' does not satisfy the schema for node type "
            f"{node.kind!r}: {exc}",
        )


def _validate_shared_tools(
    report: ValidationReport, blueprint: WorkflowBlueprint, known_tools: set
) -> None:
    """Check workflow-level shared tools exist."""
    for tool_name in blueprint.shared_tools:
        if tool_name in known_tools:
            continue
        suggestions = _closest(tool_name, sorted(known_tools))
        report.add(
            None,
            "shared_tool_not_found",
            f"shared tool {tool_name!r} is not in the catalog."
            + (f" Closest available: {suggestions}." if suggestions else ""),
        )
        report.capability_gaps.append(
            CapabilityGap(
                kind="tool",
                requested=tool_name,
                reason="No such tool is registered on this platform.",
                suggestion=suggestions[0] if suggestions else None,
            )
        )


def _validate_transitions(
    report: ValidationReport,
    blueprint: WorkflowBlueprint,
    node_ids: set,
    engine: str,
) -> None:
    """Check transition references, engine support, predicates and acyclicity."""
    edges: List[Tuple[str, str]] = []

    for transition in blueprint.transitions:
        where = f"{transition.source!r} -> {transition.target!r}"
        sources = transition.source_ids()
        targets = transition.target_ids()

        for ref in sources + targets:
            if ref not in node_ids:
                suggestions = _closest(ref, sorted(node_ids))
                report.add(
                    None,
                    "transition_unknown_node",
                    f"Transition {where} references unknown node {ref!r}."
                    + (f" Closest declared: {suggestions}." if suggestions else "")
                    + f" Declared nodes: {sorted(node_ids)}.",
                )

        if engine == "crew" and transition.condition not in {"always", "on_success"}:
            report.add(
                None,
                "condition_unsupported",
                f"Transition {where} uses condition "
                f"{transition.condition!r}, but a crew has no conditional "
                "edges — every relation is an unconditional dependency. Use "
                "engine='flow' for conditional routing.",
            )

        if transition.predicate:
            _validate_predicate(report, transition.predicate, where)

        edges.extend(
            (source, target)
            for source in sources
            for target in targets
            if source in node_ids and target in node_ids
        )

    _validate_acyclic(report, blueprint, node_ids, edges)
    _validate_reachability(report, blueprint, node_ids, edges)


def _validate_acyclic(
    report: ValidationReport,
    blueprint: WorkflowBlueprint,
    node_ids: set,
    edges: Sequence[Tuple[str, str]],
) -> None:
    """Reject cycles via Kahn's algorithm.

    ``on_condition`` back-edges are exempt for a flow — a CEL-gated loop is a
    deliberate, bounded repair cycle the explicit-edge executor supports (the
    dev-loop's ``qa -> development`` edge is exactly this). A crew has no
    conditional edges at all, so every cycle there is a deadlock.
    """
    conditional: set = {
        (source, target)
        for transition in blueprint.transitions
        if transition.condition == "on_condition"
        for source in transition.source_ids()
        for target in transition.target_ids()
    }
    considered = [edge for edge in edges if edge not in conditional]

    in_degree: Dict[str, int] = {node_id: 0 for node_id in node_ids}
    adjacency: Dict[str, List[str]] = defaultdict(list)
    for source, target in considered:
        adjacency[source].append(target)
        in_degree[target] += 1

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for successor in adjacency[current]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    if visited < len(in_degree):
        cyclic = sorted(node_id for node_id, degree in in_degree.items() if degree > 0)
        report.add(
            None,
            "cycle_detected",
            f"The transitions form a cycle involving {cyclic}. A workflow "
            "must be a DAG; only an 'on_condition' edge may loop back, and "
            "only in engine='flow'.",
        )


def _validate_reachability(
    report: ValidationReport,
    blueprint: WorkflowBlueprint,
    node_ids: set,
    edges: Sequence[Tuple[str, str]],
) -> None:
    """Warn about nodes that can never run.

    A node with no inbound edge in a multi-node workflow is either a second
    entry point (legitimate for a parallel fan-out) or an orphan the model
    forgot to wire — worth surfacing, not worth blocking on.
    """
    if len(node_ids) < 2 or not blueprint.transitions:
        return

    has_inbound = {target for _, target in edges}
    roots = sorted(node_ids - has_inbound)
    if not roots:
        report.add(
            None,
            "no_entry_point",
            "Every node has an inbound transition, so the workflow has no "
            "entry point. At least one node must start the workflow.",
        )
    elif len(roots) > 1:
        report.add(
            None,
            "multiple_entry_points",
            f"Nodes {roots} have no inbound transition and will all start "
            "concurrently. If that is not intended, wire them into the chain.",
            severity="warning",
        )
