"""Deterministic checks over a procedure graph (FEAT-891). Pure: no I/O."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.procedure.models import ProbeCost, ProcedureSpec

ADVICE_MAX_CHARS = 300
_EDGE_EXEMPT = frozenset({"applies_to", "learned_from"})


class GraphFinding(BaseModel):
    """One problem found in a procedure graph."""

    code: str
    severity: Literal["error", "warning"]
    subjects: list[str] = Field(default_factory=list)
    message: str


def _mentions(command: str, name: str) -> bool:
    """Return whether ``name`` appears in ``command`` as a whole token."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", command) is not None


def _requires_cycles(specs: Sequence[ProcedureSpec]) -> list[list[str]]:
    """Return each requires-procedure cycle once, as its sorted member ids."""
    graph = {
        spec.id: sorted({target for target in spec.requires_procedures if target in {item.id for item in specs}})
        for spec in specs
    }
    cycles: set[tuple[str, ...]] = set()

    def visit(start: str, current: str, path: list[str], seen: set[str]) -> None:
        """Enumerate simple cycles whose lexicographically smallest member is ``start``."""
        for target in graph[current]:
            if target == start:
                cycles.add(tuple(sorted(path)))
            elif target >= start and target not in seen:
                visit(start, target, [*path, target], {*seen, target})

    for start in sorted(graph):
        visit(start, start, [start], {start})
    return [list(cycle) for cycle in sorted(cycles)]


def _broken_edges(spec: ProcedureSpec, ids: set[str]) -> list[GraphFinding]:
    """Return findings for non-exempt edges to unknown procedure ids."""
    return [
        GraphFinding(
            code="broken-edge",
            severity="error",
            subjects=[spec.id, dst],
            message=f"{spec.id} has a '{rel}' edge to unknown node {dst}",
        )
        for _src, dst, rel in spec.edges()
        if rel not in _EDGE_EXEMPT and dst not in ids
    ]


def _unknown_probes(spec: ProcedureSpec, known_probes: Mapping[str, ProbeCost]) -> list[GraphFinding]:
    """Return findings for probe checks absent from the probe registry."""
    return [
        GraphFinding(
            code="unknown-probe",
            severity="error",
            subjects=[spec.id, check.probe],
            message=f"{spec.id} references unknown probe {check.probe}",
        )
        for check in (*spec.preconditions, *spec.done_when)
        if check.probe not in known_probes
    ]


def _remote_guard_finding(spec: ProcedureSpec, known_probes: Mapping[str, ProbeCost]) -> GraphFinding | None:
    """Return a finding when a guarded node has only remote preconditions."""
    if not spec.guards or not spec.preconditions:
        return None
    if not all(known_probes.get(check.probe) == "remote" for check in spec.preconditions):
        return None
    return GraphFinding(
        code="remote-probe-in-guard",
        severity="warning",
        subjects=[spec.id],
        message=f"{spec.id} has guards but only remote preconditions",
    )


def _mandatory_enforcement_finding(spec: ProcedureSpec) -> GraphFinding | None:
    """Return a finding for a mandatory node with no enforcement mechanism."""
    if spec.mode != "mandatory" or spec.guards or spec.executor is not None:
        return None
    return GraphFinding(
        code="mandatory-without-enforcement",
        severity="error",
        subjects=[spec.id],
        message=f"{spec.id} is mandatory but has no guard or executor",
    )


def _bypass_alternative_finding(spec: ProcedureSpec) -> GraphFinding | None:
    """Return a finding for a bypass guard with no replacement command."""
    if spec.use_instead or not any(guard.kind == "bypass" for guard in spec.guards):
        return None
    return GraphFinding(
        code="bypass-without-alternative",
        severity="error",
        subjects=[spec.id],
        message=f"{spec.id} has a bypass guard but no use_instead command",
    )


def _learned_mandatory_finding(spec: ProcedureSpec) -> GraphFinding | None:
    """Return a finding when a learned procedure is mandatory or confirming."""
    if spec.source != "learned" or (spec.mode != "mandatory" and not spec.confirm):
        return None
    return GraphFinding(
        code="learned-mandatory",
        severity="error",
        subjects=[spec.id],
        message=f"{spec.id} is learned and cannot be mandatory or require confirmation",
    )


def _advice_length_finding(spec: ProcedureSpec) -> GraphFinding | None:
    """Return a finding when advice exceeds the fixed character limit."""
    if len(spec.advice) <= ADVICE_MAX_CHARS:
        return None
    return GraphFinding(
        code="advice-too-long",
        severity="error",
        subjects=[spec.id],
        message=f"{spec.id} advice is longer than {ADVICE_MAX_CHARS} characters",
    )


def _cycle_findings(specs: Sequence[ProcedureSpec]) -> list[GraphFinding]:
    """Return one finding for each unique requires-procedure cycle."""
    return [
        GraphFinding(
            code="requires-cycle",
            severity="error",
            subjects=cycle,
            message=f"requires_procedures cycle: {' -> '.join(cycle)}",
        )
        for cycle in _requires_cycles(specs)
    ]


def _uncovered_commands(specs: Sequence[ProcedureSpec], known_commands: Sequence[str]) -> list[GraphFinding]:
    """Return findings for known commands absent from every procedure command."""
    return [
        GraphFinding(
            code="uncovered-command",
            severity="warning",
            subjects=[name],
            message=f"No procedure command covers {name}",
        )
        for name in known_commands
        if not any(_mentions(spec.command, name) for spec in specs)
    ]


def validate_graph(
    specs: Sequence[ProcedureSpec],
    *,
    known_probes: Mapping[str, ProbeCost],
    known_commands: Sequence[str] = (),
) -> list[GraphFinding]:
    """Return every finding, sorted by ``(code, subjects)``."""
    findings: list[GraphFinding] = []
    ids = {spec.id for spec in specs}
    for spec in specs:
        findings.extend(_broken_edges(spec, ids))
        findings.extend(_unknown_probes(spec, known_probes))
        findings.extend(
            finding
            for finding in (
                _remote_guard_finding(spec, known_probes),
                _mandatory_enforcement_finding(spec),
                _bypass_alternative_finding(spec),
                _learned_mandatory_finding(spec),
                _advice_length_finding(spec),
            )
            if finding is not None
        )
    findings.extend(_cycle_findings(specs))
    findings.extend(_uncovered_commands(specs, known_commands))
    return sorted(findings, key=lambda finding: (finding.code, finding.subjects))
