"""Flow Tools — ResultRetrievalTool.

Moved from ``parrot.bots.flow.tools`` to the canonical ``flows/`` location.
Updated to import ``ExecutionMemory`` from the shared ``flows.core.storage``
rather than the old ``bots/flow/storage``.

The original ``bots/flow/tools.py`` is NOT modified — it remains for any
remaining consumers until they are migrated.
"""
from typing import Any, Dict, Optional

from parrot.tools.abstract import AbstractTool
from .core.storage.memory import ExecutionMemory


class ResultRetrievalTool(AbstractTool):
    """Retrieval Tool for flows (AgentCrew, AgentsFlow).

    Allows agents to look up detailed execution results from the
    ``ExecutionMemory`` of a running flow.  Supports three actions:

    - ``list_agents``: List all agents with available results.
    - ``get_agent_result``: Retrieve the full result text for a specific agent.
    - ``search_results``: Semantic search across stored results (requires
      FAISS to be configured on the ``ExecutionMemory``).

    Args:
        memory: The ``ExecutionMemory`` instance to query.
    """

    name = "execution_context_tool"
    description = (
        "Retrieve detailed execution results and context from agents. "
        "Use this tool when you need more specific details about what an agent "
        "found than what is provided in the summary."
    )

    def __init__(
        self,
        memory: ExecutionMemory,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.memory = memory

    def get_schema(self) -> Dict[str, Any]:
        """Return the JSON schema for this tool's parameters.

        Returns:
            Dict describing the tool's name, description, and parameter schema.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_agents", "get_agent_result", "search_results"],
                        "description": (
                            "Action to perform: list available agents, "
                            "get specific result, or search across results."
                        ),
                    },
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "ID of the agent (required for 'get_agent_result')"
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query (required for 'search_results')"
                        ),
                    },
                },
                "required": ["action"],
            },
        }

    async def _execute(
        self,
        action: str,
        agent_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> str:
        """Execute the requested retrieval action.

        Args:
            action: One of ``list_agents``, ``get_agent_result``, or
                ``search_results``.
            agent_id: Required when ``action == 'get_agent_result'``.
            query: Required when ``action == 'search_results'``.

        Returns:
            Human-readable string with the requested information.
        """
        if action == "list_agents":
            agents = self.memory.execution_order
            return f"Agents with available results: {', '.join(agents)}"

        elif action == "get_agent_result":
            if not agent_id:
                return "Error: agent_id is required for get_agent_result"

            result = self.memory.get_results_by_agent(agent_id)
            if result:
                return f"Result for {agent_id}:\n{result.to_text()}"
            return f"No result found for agent_id: {agent_id}"

        elif action == "search_results":
            if not query:
                return "Error: query is required for search_results"

            results = self.memory.search_similar(query, top_k=5)
            if not results:
                return f"No relevant results found for '{query}'"

            output = []
            for chunk, res, score in results:
                output.append(
                    f"Match (Score: {score:.2f}) from {res.node_name}:\n{chunk}\n---"
                )

            return "\n".join(output)

        return f"Unknown action: {action}"
