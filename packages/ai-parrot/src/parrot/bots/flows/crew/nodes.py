"""Crew-specific node type for AgentCrew orchestration.

Defines ``CrewAgentNode``, extracted from ``parrot.bots.orchestration.crew``
(formerly ``_CrewAgentNode``), with the public name and updated imports for
its new location under ``parrot.bots.flows.crew``.

The node subclasses ``AgentNode`` from ``flows.core.node`` and overrides
``_build_prompt`` to apply crew-specific formatting that combines the
initial task with results from upstream dependency agents.

FEAT-163 changes:
    - Converted from ``@dataclass`` to Pydantic ``BaseModel`` subclass
      (inherits frozen + arbitrary_types_allowed from the new ``AgentNode``).
    - ``_format_prompt(input_data)`` renamed/replaced by ``_build_prompt(ctx, deps)``
      override (same formatting logic, new signature matching the FEAT-163 contract).
    - ``execute_in_context(context, timeout)`` removed; callers use the
      inherited ``execute(ctx, deps, **kwargs)`` directly.
"""
from __future__ import annotations

from typing import Any, Dict

from ..core.context import FlowContext
from ..core.node import AgentNode as _CoreAgentNode
from ..core.types import DependencyResults


class CrewAgentNode(_CoreAgentNode):
    """Crew-specific node wrapping an agent with dependency metadata.

    Inherits ``execute()`` (with pre/post hooks) from the core ``AgentNode``.
    Overrides ``_build_prompt()`` for crew-specific prompt formatting:
    the initial task plus results from upstream dependency agents are
    combined into a single natural-language prompt string.

    Args:
        agent: The agent this node wraps.
        node_id: Unique identifier for this node in the graph.
        dependencies: Set of node_ids that must complete before this one.
        successors: Set of node_ids that depend on this one.
        fsm: Optional finite state machine for task lifecycle tracking.
    """

    def _build_prompt(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
    ) -> str:
        """Build a crew-style prompt from context and dependency results.

        Derives the structured input dict via
        ``ctx.get_input_for_agent(self.agent.name, self.dependencies)``
        and then formats it into a natural language prompt using the same
        logic as the legacy ``_format_prompt``.

        Args:
            ctx: The current workflow execution context.
            deps: Mapping of completed dependency node_id -> result string
                  (used by the base class; crew derives its own input from
                  ``ctx`` directly for backward compatibility).

        Returns:
            Formatted prompt string suitable for the agent.
        """
        input_data = ctx.get_input_for_agent(self.agent.name, self.dependencies)
        return self._format(input_data)

    @staticmethod
    def _format(input_data: Dict[str, Any]) -> str:
        """Format the input data dictionary into a string prompt.

        Converts structured input data (task + dependency results) into a
        natural language prompt the agent can understand.

        This is the renamed/refactored version of the legacy
        ``_format_prompt`` method, now a static utility.

        Args:
            input_data: Dict with ``'task'`` and optionally ``'dependencies'``.

        Returns:
            Formatted prompt string.
        """
        if not input_data:
            return ""

        # Start with the main task
        task = input_data.get("task", "")

        # If there are no dependencies, just return the task
        dependencies = input_data.get("dependencies", {})
        if not dependencies:
            return task

        # Build a prompt that includes results from dependent agents
        prompt_parts = [f"Task: {task}\n", "\nContext from previous agents:\n"]

        for dep_agent, dep_result in dependencies.items():
            prompt_parts.extend(
                (f"\n--- From {dep_agent} ---", str(dep_result), "")
            )

        return "\n".join(prompt_parts)
