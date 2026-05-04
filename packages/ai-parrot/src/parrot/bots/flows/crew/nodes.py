"""Crew-specific node type for AgentCrew orchestration.

Defines ``CrewAgentNode``, extracted from ``parrot.bots.orchestration.crew``
(formerly ``_CrewAgentNode``), with the public name and updated imports for
its new location under ``parrot.bots.flows.crew``.

The node subclasses ``AgentNode`` from ``flows.core.node`` and adds
crew-specific prompt formatting and context-driven execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..core.node import AgentNode as _CoreAgentNode
from ..core.context import FlowContext


@dataclass
class CrewAgentNode(_CoreAgentNode):
    """Crew-specific node wrapping an agent with dependency metadata.

    Inherits ``execute()`` (with timeout, time tracking, and pre/post hooks)
    from the core ``AgentNode``.  Adds ``_format_prompt()`` for crew-specific
    prompt formatting and ``execute_in_context()`` for context-driven execution.

    Args:
        agent: The agent this node wraps.
        node_id: Unique identifier for this node in the graph.
        dependencies: Set of node_ids that must complete before this one.
        successors: Set of node_ids that depend on this one.
        fsm: Optional finite state machine for task lifecycle tracking.
    """

    def _format_prompt(self, input_data: Dict[str, Any]) -> str:
        """Format the input data dictionary into a string prompt.

        Converts structured input data (task + dependency results) into a
        natural language prompt the agent can understand.

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
            prompt_parts.extend((f"\n--- From {dep_agent} ---", str(dep_result), ""))

        return "\n".join(prompt_parts)

    async def execute_in_context(
        self, context: FlowContext, timeout: Optional[float] = None
    ) -> Any:
        """Execute the agent with context from previous agents.

        Resolves the prompt from the ``FlowContext`` using dependency data,
        then delegates to the inherited ``execute()`` method.

        Args:
            context: The current workflow execution context.
            timeout: Optional timeout in seconds for the agent call.

        Returns:
            Dict with ``'response'``, ``'output'``, ``'execution_time'``,
            ``'prompt'``.
        """
        # Get input data based on dependencies.
        # ``get_input_for_agent`` already falls back to ``initial_task``
        # when the node has no dependencies and no prior results.
        input_data = context.get_input_for_agent(
            self.agent.name, self.dependencies
        )

        prompt = self._format_prompt(input_data)
        return await self.execute(prompt, timeout=timeout)
