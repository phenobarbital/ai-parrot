"""
Core crew definition models.

Defines the data structures used to describe an AgentCrew: execution modes,
agent definitions, flow relations, and complete crew definitions.

These models are intentionally placed in ``parrot/models/`` (not in the HTTP
handler layer) so they can be imported from any part of the framework —
including ``parrot/bots/`` — without creating circular dependencies.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timezone
from enum import Enum
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ExecutionMode(str, Enum):
    """Execution modes for AgentCrew."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    FLOW = "flow"
    LOOP = "loop"


class AgentDefinition(BaseModel):
    """Definition of an agent in a crew.

    Attributes:
        agent_id: Unique identifier for the agent within this crew.
        agent_class: Agent class name used to resolve the concrete class
            (e.g. "BaseAgent", "Chatbot", "WebSearchAgent").
        name: Human-readable display name for the agent. Falls back to
            ``agent_id`` when not provided.
        config: Arbitrary agent configuration forwarded as ``**kwargs``
            to the agent constructor (e.g. ``llm``, ``model``,
            ``temperature``, provider-specific options).
        tools: List of tool names that this agent has access to.
        system_prompt: Optional system prompt to set on the agent after
            construction.
    """

    agent_id: str = Field(description="Unique identifier for the agent")
    agent_class: str = Field(
        default="BaseAgent",
        description="Agent class name (BaseAgent, Chatbot, etc.)"
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-readable name for the agent"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Agent configuration (llm, model, temperature, etc.)"
    )
    tools: List[str] = Field(
        default_factory=list,
        description="List of tool names available to this agent"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt for the agent"
    )


class ToolNodeDefinition(BaseModel):
    """Definition of a deterministic tool-execution node in a crew.

    A tool node is NOT an LLM agent: it invokes the referenced tool
    directly with the declared ``args``/``kwargs`` (pass-through) and wraps
    the result as an agent-execution result, so it participates in every
    crew execution mode without spending LLM tokens.

    String values inside ``args``/``kwargs`` may contain template
    placeholders resolved deterministically at execution time:

    - ``{input}`` — the node's input (previous output / initial task).
    - ``{nodes.<node_name>.output}`` — a previously completed node's output.

    Avoid dots in ``node_id``: they are ambiguous inside the
    ``{nodes.<node_name>.output}`` placeholder syntax.

    Attributes:
        node_id: Unique identifier for the tool node within this crew.
        tool: Tool name/slug resolved via the tool resolver.
        name: Human-readable display name (defaults to ``node_id``).
        description: Optional description of the node's purpose.
        args: Positional arguments passed through to the tool.
        kwargs: Keyword arguments passed through to the tool.
    """

    node_id: str = Field(
        description="Unique identifier for the tool node within the crew"
    )
    tool: str = Field(
        description="Tool name/slug resolved via the tool resolver"
    )
    name: Optional[str] = Field(
        default=None,
        description="Human-readable display name (defaults to node_id)"
    )
    description: Optional[str] = Field(
        default=None,
        description="Description of the tool node's purpose"
    )
    args: List[Any] = Field(
        default_factory=list,
        description="Positional arguments passed through to the tool"
    )
    kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Keyword arguments passed through to the tool. String values "
            "may embed {input} or {nodes.<node_name>.output} placeholders."
        )
    )


class FlowRelation(BaseModel):
    """Defines a dependency relationship between agents in flow mode.

    Attributes:
        source: The display name (or list of names) of the agent(s) that must
            complete first.  Must match ``AgentDefinition.name`` when set, or
            ``AgentDefinition.agent_id`` when ``name`` is ``None``.
        target: The display name (or list of names) of the agent(s) that depend
            on ``source`` completion before they can execute.  Same naming
            convention as ``source``.
    """

    source: Union[str, List[str]] = Field(
        description="Source agent(s) that must complete first"
    )
    target: Union[str, List[str]] = Field(
        description="Target agent(s) that depend on source completion"
    )


class CrewDefinition(BaseModel):
    """Complete definition of an AgentCrew.

    Attributes:
        crew_id: Unique identifier for this crew definition (auto-generated).
        tenant: Tenant identifier for crew isolation in multi-tenant deployments.
        name: Display name of the crew.
        description: Optional human-readable description of the crew's purpose.
        execution_mode: How the crew should execute its agents.
        agents: Ordered list of agent definitions.
        tool_nodes: Deterministic tool-execution nodes (no LLM) that
            participate in the crew alongside agents.
        flow_relations: Directed dependency edges used when ``execution_mode``
            is ``FLOW``. Ignored for other modes.
        shared_tools: Tool names that are shared across all agents.
        max_parallel_tasks: Semaphore limit for concurrent agent executions.
        metadata: Arbitrary extra data attached to the definition.
        created_at: Timestamp when this definition was created.
        updated_at: Timestamp of the most recent update.
    """

    crew_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the crew"
    )
    tenant: str = Field(
        default="global",
        description="Tenant identifier for crew isolation"
    )
    name: str = Field(description="Name of the crew")
    description: Optional[str] = Field(
        default=None,
        description="Description of the crew's purpose"
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.SEQUENTIAL,
        description="Execution mode: sequential, parallel, or flow"
    )
    agents: List[AgentDefinition] = Field(
        description="List of agent definitions in the crew"
    )
    tool_nodes: List[ToolNodeDefinition] = Field(
        default_factory=list,
        description=(
            "Deterministic tool-execution nodes (no LLM) that participate "
            "in the crew alongside agents"
        )
    )
    flow_relations: List[FlowRelation] = Field(
        default_factory=list,
        description="Flow relationships (only used in flow mode)"
    )
    shared_tools: List[str] = Field(
        default_factory=list,
        description="Tools shared across all agents"
    )
    max_parallel_tasks: int = Field(
        default=10,
        description="Maximum number of parallel tasks"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp"
    )

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat()},
    )


__all__ = [
    "ExecutionMode",
    "AgentDefinition",
    "ToolNodeDefinition",
    "FlowRelation",
    "CrewDefinition",
]
