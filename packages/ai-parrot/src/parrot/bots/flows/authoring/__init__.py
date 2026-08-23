"""Author an ``AgentCrew`` or ``AgentsFlow`` from a natural-language request.

A model writes the workflow one node at a time; deterministic code joins the
pieces, validates them against the live registries, and compiles the result
into a real ``CrewDefinition`` or ``FlowDefinition``.

The pipeline::

    request ──► skeleton      (1 call: ids, kinds, one-line purposes)
             ──► node × N     (1 bounded call each, authored concurrently)
             ──► transitions  (1 call)
             ──► assemble     (deterministic)
             ──► validate     (Pydantic → JSON Schema → live registries)
             ──► repair       (1 bounded round, fed the validation report)
             ──► compile      (deterministic → Crew/Flow definition)

Why node-by-node: a per-node call sees only the skeleton digest, its own
stub, and the catalog slice its kind needs — never the other nodes' full
definitions. Workflow size therefore does not drive prompt size.

Why an intermediate ``WorkflowBlueprint`` rather than emitting a definition
directly: the two targets disagree about how agents are referenced, how edges
are named and whether conditions exist at all. The blueprint is engine-neutral
and ``assembler`` absorbs the difference — the same split as
``ExecutionPlan`` → ``to_flow_definition`` in ``parrot.bots.flows.plan``.

Typical use::

    from parrot.bots.flows.authoring import (
        FlowAuthoringOrchestrator, FlowAuthoringRequest,
    )

    orchestrator = FlowAuthoringOrchestrator(planner_llm="openai:gpt-4o")
    result = await orchestrator.build(
        FlowAuthoringRequest(description="a crew that researches a topic, "
                                         "writes a blog post and publishes it")
    )
    result.crew_definition   # ready for AgentCrew.from_definition
    result.capability_gaps   # anything the platform could not satisfy
"""
from .assembler import (
    AssemblyError,
    assemble,
    to_crew_definition,
    to_flow_definition,
)
from .author import FlowAuthor, FlowAuthoringError
from .blueprint import (
    BlueprintNode,
    BlueprintSkeleton,
    BlueprintTransition,
    NodeStub,
    WorkflowBlueprint,
)
from .catalog import (
    AgentEntry,
    ComponentCatalog,
    NodeTypeEntry,
    ToolEntry,
    build_catalog,
)
from .contracts import (
    AuthoringProgress,
    AuthoringStage,
    AuthoringStatus,
    CapabilityGap,
    FlowAuthoringRequest,
    FlowAuthoringResult,
)
from .orchestrator import FlowAuthoringOrchestrator
from .schemas import (
    blueprint_json_schema,
    node_config_json_schema,
    node_json_schema,
    skeleton_json_schema,
    transitions_json_schema,
    validate_against_schema,
)
from .validator import ValidationIssue, ValidationReport, validate_blueprint

__all__ = (
    "AgentEntry",
    "AssemblyError",
    "AuthoringProgress",
    "AuthoringStage",
    "AuthoringStatus",
    "BlueprintNode",
    "BlueprintSkeleton",
    "BlueprintTransition",
    "CapabilityGap",
    "ComponentCatalog",
    "FlowAuthor",
    "FlowAuthoringError",
    "FlowAuthoringOrchestrator",
    "FlowAuthoringRequest",
    "FlowAuthoringResult",
    "NodeStub",
    "NodeTypeEntry",
    "ToolEntry",
    "ValidationIssue",
    "ValidationReport",
    "WorkflowBlueprint",
    "assemble",
    "blueprint_json_schema",
    "build_catalog",
    "node_config_json_schema",
    "node_json_schema",
    "skeleton_json_schema",
    "to_crew_definition",
    "to_flow_definition",
    "transitions_json_schema",
    "validate_against_schema",
    "validate_blueprint",
)
