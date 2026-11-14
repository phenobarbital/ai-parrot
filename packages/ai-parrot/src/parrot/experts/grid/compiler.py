"""Scope grid → FlowDefinition compiler (FEAT-890 M5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from parrot.bots.flows.core.gates.kinds import is_registered
from parrot.bots.flows.flow.definition import EdgeDefinition, FlowDefinition, NodeDefinition
from parrot.experts.grid.models import ExpertStageConfig, ScopeGrid, ScopeGridError, ScopeGridErrorCode
import parrot.experts.stages  # noqa: F401 - register the expert_stage node type.

if TYPE_CHECKING:
    from parrot.experts.registry import ExpertRegistry


_GATE_APPROVED_PREDICATE = 'result.metadata.gate.status == "approved"'


def _expert(registry: "ExpertRegistry", name: str) -> Any:
    """Return one known expert or raise the stable compiler error."""
    try:
        return registry.get(name)
    except KeyError as exc:
        raise ScopeGridError(ScopeGridErrorCode.UNKNOWN_EXPERT, f"unknown expert {name!r}") from exc


def _check_inline_rule_clashes(stage: ExpertStageConfig, registry: "ExpertRegistry") -> None:
    """Refuse an inline stage whose experts declare the same governance rule line.

    Uses each expert bundle's own rules (static, so this stays a pure compile-time check). Workspace-level rule
    layers are only known at run time; ``build_inline_conductor`` repeats the check there as a backstop.
    """
    owners: dict[str, str] = {}
    for name in stage.experts:
        rules = _expert(registry, name).bundle.rules
        for line in () if rules is None else (*rules.mandated, *rules.forbidden):
            other = owners.setdefault(line, name)
            if other != name:
                raise ScopeGridError(
                    ScopeGridErrorCode.RULE_CLASH,
                    f"inline stage {stage.stage!r}: rule {line!r} is declared by both {other!r} and {name!r}",
                )


def _validate_stage(stage: ExpertStageConfig, registry: "ExpertRegistry") -> None:
    """Validate registry and gate contracts used by one stage."""
    for name in stage.experts:
        _expert(registry, name)
    if stage.conductor is not None:
        _expert(registry, stage.conductor)
    if stage.mode == "inline":
        _check_inline_rule_clashes(stage, registry)
    if stage.gate is None:
        return
    if not is_registered(stage.gate.kind):
        raise ScopeGridError(ScopeGridErrorCode.UNKNOWN_GATE_KIND, f"unknown gate kind {stage.gate.kind!r}")
    if stage.gate.pre_review is None:
        return
    reviewer = _expert(registry, stage.gate.pre_review)
    if "review" not in reviewer.bundle.manifest.capabilities:
        raise ScopeGridError(
            ScopeGridErrorCode.CAPABILITY_MISMATCH,
            f"pre_review expert {stage.gate.pre_review!r} for stage {stage.stage!r} lacks review capability",
        )


def _stage_nodes(stage: ExpertStageConfig) -> list[NodeDefinition]:
    """Compile one declared stage into one or more executable nodes."""
    if stage.mode != "pipeline":
        return [NodeDefinition(id=stage.stage, type="expert_stage", label=stage.stage, config=stage.model_dump())]
    nodes: list[NodeDefinition] = []
    for index, expert in enumerate(stage.experts):
        config = stage.model_copy(
            update={
                "stage": f"{stage.stage}-{index + 1}",
                "experts": [expert],
                "mode": "subagent",
                "gate": stage.gate if index == len(stage.experts) - 1 else None,
            }
        )
        nodes.append(
            NodeDefinition(id=config.stage, type="expert_stage", label=config.stage, config=config.model_dump())
        )
    return nodes


def _edge(source: str, target: str, *, gated: bool) -> EdgeDefinition:
    """Build a normal or gate-approval transition edge."""
    payload: dict[str, str] = {"from": source, "to": target}
    if gated:
        payload.update(condition="on_condition", predicate=_GATE_APPROVED_PREDICATE)
    else:
        payload["condition"] = "always"
    return EdgeDefinition(**payload)


def compile_scope(grid: ScopeGrid, *, registry: "ExpertRegistry") -> FlowDefinition:
    """Compile a scope grid into a pure executable flow definition.

    Raises:
        ScopeGridError: For unknown experts, capability mismatches, unknown gate
            kinds, or a generated graph cycle.
    """
    for stage in grid.stages:
        _validate_stage(stage, registry)
    nodes = [NodeDefinition(id="__start__", type="start")]
    edges: list[EdgeDefinition] = []
    previous = "__start__"
    previous_gated = False
    for stage in grid.stages:
        for node in _stage_nodes(stage):
            edges.append(_edge(previous, node.id, gated=previous_gated))
            previous = node.id
            previous_gated = node.config.get("gate") is not None
            nodes.append(node)
        if stage.mode == "mob":
            synthesis_id = f"{stage.stage}-synthesis"
            edges.append(_edge(previous, synthesis_id, gated=previous_gated))
            nodes.append(NodeDefinition(id=synthesis_id, type="synthesis", label=f"{stage.stage} synthesis"))
            previous = synthesis_id
            previous_gated = False
    nodes.append(NodeDefinition(id="__end__", type="end"))
    edges.append(_edge(previous, "__end__", gated=previous_gated))
    try:
        return FlowDefinition(flow=grid.scope, description=grid.description, nodes=nodes, edges=edges)
    except ValidationError as exc:
        if "Cycle detected" in str(exc):
            raise ScopeGridError(ScopeGridErrorCode.CYCLE, str(exc)) from exc
        raise ScopeGridError(ScopeGridErrorCode.INVALID, str(exc)) from exc
