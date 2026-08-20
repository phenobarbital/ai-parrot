"""``WorkflowBlueprint`` — the one artifact an authoring model produces.

The blueprint exists because ``CrewDefinition`` and ``FlowDefinition`` are
asymmetric in ways no single prompt can straddle:

===================  ==============================  ============================
                     CrewDefinition                  FlowDefinition
===================  ==============================  ============================
agent reference      inline (class + config +        ``agent_ref`` resolved from
                     system_prompt) — *constructs*   ``AgentRegistry`` — *looks
                     the agent                       up* an existing agent
edges                ``FlowRelation`` by effective   ``EdgeDefinition`` by node
                     display name, unconditional     id, 5 conditions + CEL
execution mode       explicit field                  implied by the DAG
tool node            ``ToolNodeDefinition``          ``type: "tool"``
===================  ==============================  ============================

Asking a model to emit either target directly means teaching it both sets of
rules and hoping it picks the right one. Instead it emits *this* — one flat,
engine-neutral shape — and ``assembler.py`` absorbs the asymmetry in
deterministic code. Same split as ``ExecutionPlan`` → ``to_flow_definition``,
for the same reason: the surface a model writes should be the smallest one
that can express the intent, not the one the executor happens to consume.

Every model is closed (``extra="forbid"``). A hallucinated field must fail
loudly here, while a repair round can still fix it, rather than being
dropped on the floor and discovered as a missing workflow step later.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = (
    "BlueprintNode",
    "BlueprintSkeleton",
    "BlueprintTransition",
    "NODE_ID_RE",
    "NodeStub",
    "WorkflowBlueprint",
)

#: Blueprint ids are lower_snake_case. Dots are excluded deliberately: they
#: are ambiguous inside the ``{nodes.<id>.output}`` placeholder both engines
#: use for cross-node references.
NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: The node kinds a blueprint may declare. ``start``/``end`` are absent on
#: purpose — the compilers emit those sentinels themselves, so a model
#: cannot get the graph's entry and exit wrong.
NodeKind = Literal["agent", "tool", "decision", "interactive_decision", "synthesis"]

Engine = Literal["crew", "flow"]


def _validate_id(value: str, *, field: str) -> str:
    """Enforce the shared id shape.

    Args:
        value: The candidate id.
        field: Field name, for the error message.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If the id is not lower_snake_case.
    """
    if not NODE_ID_RE.match(value):
        raise ValueError(
            f"{field} {value!r} must be lower_snake_case matching "
            f"{NODE_ID_RE.pattern} (no dots, spaces or capitals — dots are "
            f"ambiguous inside {{nodes.<id>.output}} placeholders)."
        )
    return value


class NodeStub(BaseModel):
    """One line of the skeleton: what a node is, before it is authored.

    The skeleton stage emits these and nothing else. They are what every
    per-node call sees of the *other* nodes, which is what keeps a long
    workflow from filling the context window.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="lower_snake_case node id, unique in the workflow")
    kind: NodeKind = Field(..., description="What sort of node this is")
    purpose: str = Field(
        ...,
        min_length=1,
        max_length=280,
        description="One or two sentences: what this node does and why it exists",
    )

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return _validate_id(value, field="node id")


class BlueprintSkeleton(BaseModel):
    """The workflow's shape, before any node is filled in."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Human-readable workflow name")
    description: str = Field(default="", description="What the workflow accomplishes")
    engine: Engine = Field(
        ...,
        description=(
            "'crew' builds agents inline from the blueprint; 'flow' resolves "
            "existing agents from the AgentRegistry by agent_ref"
        ),
    )
    nodes: List[NodeStub] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "BlueprintSkeleton":
        """Reject duplicate node ids."""
        seen: set[str] = set()
        duplicates = sorted({n.id for n in self.nodes if n.id in seen or seen.add(n.id)})
        if duplicates:
            raise ValueError(f"Duplicate node ids in skeleton: {duplicates}")
        return self

    def summarize(self) -> str:
        """Render the one-line-per-node digest given to per-node calls.

        Returns:
            A compact listing: enough for a node to know its neighbours
            exist and what they do, without carrying their full definitions.
        """
        lines = [f"Workflow: {self.name} (engine={self.engine})"]
        if self.description:
            lines.append(f"Goal: {self.description}")
        lines.append("Nodes:")
        lines.extend(f"  - {n.id} [{n.kind}]: {n.purpose}" for n in self.nodes)
        return "\n".join(lines)


class BlueprintNode(BaseModel):
    """A fully authored node.

    Which fields apply depends on ``kind``; the model validator enforces the
    combinations rather than leaving a half-specified node to fail later at
    compile or run time.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="lower_snake_case node id, matching its stub")
    kind: NodeKind
    title: str = Field(default="", description="Human-readable display name")
    purpose: str = Field(default="", description="What this node does")

    # kind="agent"
    agent_ref: Optional[str] = Field(
        default=None,
        description=(
            "Name of an agent already registered in the AgentRegistry. "
            "Required when engine='flow'."
        ),
    )
    agent_class: Optional[str] = Field(
        default=None,
        description="Agent class to construct (engine='crew' only), e.g. 'BasicAgent'",
    )
    system_prompt: Optional[str] = Field(
        default=None, description="System prompt for an inline agent"
    )
    model: Optional[str] = Field(
        default=None, description="LLM as 'provider:model', e.g. 'openai:gpt-4o'"
    )
    tools: List[str] = Field(
        default_factory=list,
        description="Tool names from the catalog. Never invent a name.",
    )

    # kind="tool"
    tool: Optional[str] = Field(
        default=None, description="Catalog tool name executed by a tool node"
    )
    args: List[Any] = Field(default_factory=list)
    kwargs: Dict[str, Any] = Field(default_factory=dict)

    # kind="decision" | "interactive_decision" | "synthesis"
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific config, validated against the node type's schema",
    )

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return _validate_id(value, field="node id")

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "BlueprintNode":
        """Enforce the field combinations each kind requires."""
        if self.kind == "tool" and not self.tool:
            raise ValueError(f"Node {self.id!r} of kind 'tool' must set 'tool'.")
        if self.kind != "tool" and self.tool:
            raise ValueError(
                f"Node {self.id!r} of kind {self.kind!r} must not set 'tool' "
                "(only kind='tool' executes a tool directly; an agent lists "
                "tools it may call in 'tools')."
            )
        if self.kind != "agent" and (self.agent_ref or self.agent_class):
            raise ValueError(
                f"Node {self.id!r} of kind {self.kind!r} must not set "
                "'agent_ref'/'agent_class'."
            )
        return self


class BlueprintTransition(BaseModel):
    """A directed edge between blueprint nodes.

    ``condition``/``predicate`` are expressible for both engines but only
    *meaningful* for ``flow``; the validator rejects them for a crew rather
    than compiling them away silently, since a dropped condition changes
    what the workflow does.
    """

    model_config = ConfigDict(extra="forbid")

    source: Union[str, List[str]] = Field(..., description="Upstream node id(s)")
    target: Union[str, List[str]] = Field(..., description="Downstream node id(s)")
    condition: Literal[
        "always", "on_success", "on_error", "on_timeout", "on_condition"
    ] = "on_success"
    predicate: Optional[str] = Field(
        default=None,
        description=(
            "CEL expression, required when condition='on_condition'. Only "
            "'result', 'error' and 'ctx' are in scope."
        ),
    )
    instruction: Optional[str] = Field(
        default=None, description="Prompt override for the target node(s)"
    )

    @model_validator(mode="after")
    def _check_predicate(self) -> "BlueprintTransition":
        """``on_condition`` needs a predicate; nothing else may carry one."""
        if self.condition == "on_condition" and not self.predicate:
            raise ValueError(
                f"Transition {self.source!r} -> {self.target!r} uses "
                "condition='on_condition' and must supply a 'predicate'."
            )
        if self.condition != "on_condition" and self.predicate:
            raise ValueError(
                f"Transition {self.source!r} -> {self.target!r} supplies a "
                f"'predicate' but condition is {self.condition!r}; the "
                "predicate would never be evaluated."
            )
        return self

    def source_ids(self) -> List[str]:
        """Normalise ``source`` to a list."""
        return [self.source] if isinstance(self.source, str) else list(self.source)

    def target_ids(self) -> List[str]:
        """Normalise ``target`` to a list."""
        return [self.target] if isinstance(self.target, str) else list(self.target)


class WorkflowBlueprint(BaseModel):
    """The assembled, engine-neutral workflow.

    Produced by ``assembler.assemble`` from a skeleton plus its authored
    nodes and transitions; consumed by ``validate_blueprint`` and then by
    one of the two compilers.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str = ""
    engine: Engine
    execution_mode: Literal["sequential", "parallel", "flow", "loop"] = "flow"
    nodes: List[BlueprintNode] = Field(..., min_length=1)
    transitions: List[BlueprintTransition] = Field(default_factory=list)
    shared_tools: List[str] = Field(
        default_factory=list, description="Tools every agent in the workflow gets"
    )

    @model_validator(mode="after")
    def _unique_ids(self) -> "WorkflowBlueprint":
        """Reject duplicate node ids (referential checks live in the validator)."""
        seen: set[str] = set()
        duplicates = sorted({n.id for n in self.nodes if n.id in seen or seen.add(n.id)})
        if duplicates:
            raise ValueError(f"Duplicate node ids: {duplicates}")
        return self

    def node_ids(self) -> List[str]:
        """Node ids in declaration order."""
        return [node.id for node in self.nodes]

    def node(self, node_id: str) -> Optional[BlueprintNode]:
        """Look up one node by id."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
