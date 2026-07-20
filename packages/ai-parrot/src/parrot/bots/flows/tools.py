"""Flow Tools — ResultRetrievalTool.

Moved from ``parrot.bots.flow.tools`` to the canonical ``flows/`` location.
Updated to import ``ExecutionMemory`` from the shared ``flows.core.storage``
rather than the old ``bots/flow/storage``.

The original ``bots/flow/tools.py`` is NOT modified — it remains for any
remaining consumers until they are migrated.
"""
from typing import Any, Callable, Dict, Optional

from parrot.tools.abstract import AbstractTool
from .core.storage.memory import ExecutionMemory


class ResultRetrievalTool(AbstractTool):
    """Retrieval Tool for flows (AgentCrew, AgentsFlow).

    Allows agents to look up detailed execution results from the
    ``ExecutionMemory`` of a running flow.  Supports five actions:

    - ``list_agents``: List all agents with available results.
    - ``get_agent_result``: Retrieve the full result text for a specific agent.
    - ``search_results``: Semantic search across stored results (requires
        FAISS to be configured on the ``ExecutionMemory``).
    - ``search_research``: BM25 (+ optional embedding) search across the
        crew's execution wiki — runs, intermediate agent results, and raw
        tool-call results from ALL recorded runs (requires an execution
        wiki to be enabled on the crew).
    - ``read_research_page``: Read one execution-wiki page in full by its
        ``concept_id`` (progressive disclosure after ``search_research``).

    Args:
        memory: The ``ExecutionMemory`` instance to query.
        wiki_provider: Optional zero-arg callable returning the crew's
            ``ExecutionWikiRecorder`` (or ``None``). A callable — not the
            recorder itself — because the recorder is created lazily by
            the crew.
    """

    name = "execution_context_tool"
    description = (
        "Retrieve detailed execution results and context from agents. "
        "Use this tool when you need more specific details about what an agent "
        "found than what is provided in the summary. The 'search_research' "
        "action searches the execution wiki: intermediate agent results and "
        "raw tool-call results recorded across all previous runs."
    )

    def __init__(
        self,
        memory: ExecutionMemory,
        *args,
        wiki_provider: Optional[Callable[[], Any]] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.memory = memory
        self._wiki_provider = wiki_provider

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
                        "enum": [
                            "list_agents",
                            "get_agent_result",
                            "search_results",
                            "search_research",
                            "read_research_page",
                        ],
                        "description": (
                            "Action to perform: list available agents, "
                            "get specific result, search across results, "
                            "search the execution wiki (intermediate results "
                            "+ tool calls), or read a wiki page in full."
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
                            "Search query (required for 'search_results' "
                            "and 'search_research')"
                        ),
                    },
                    "page_id": {
                        "type": "string",
                        "description": (
                            "Execution-wiki page concept_id (required for "
                            "'read_research_page'; returned by "
                            "'search_research')"
                        ),
                    },
                },
                "required": ["action"],
            },
        }

    def _get_wiki(self) -> Any:
        """Resolve the execution wiki recorder via the provider (or None)."""
        if self._wiki_provider is None:
            return None
        try:
            return self._wiki_provider()
        except Exception:  # noqa: BLE001 — tool must degrade gracefully
            return None

    async def _execute(
        self,
        action: str,
        agent_id: Optional[str] = None,
        query: Optional[str] = None,
        page_id: Optional[str] = None,
    ) -> str:
        """Execute the requested retrieval action.

        Args:
            action: One of ``list_agents``, ``get_agent_result``,
                ``search_results``, ``search_research``, or
                ``read_research_page``.
            agent_id: Required when ``action == 'get_agent_result'``.
            query: Required when ``action`` is ``'search_results'`` or
                ``'search_research'``.
            page_id: Required when ``action == 'read_research_page'``.

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

        elif action == "search_research":
            if not query:
                return "Error: query is required for search_research"

            wiki = self._get_wiki()
            if wiki is None:
                return (
                    "Execution wiki is not available "
                    "(disabled or not yet initialised)."
                )
            hits = await wiki.search(query, top_k=5)
            if not hits:
                return f"No research-wiki matches found for '{query}'"

            output = []
            for hit in hits:
                output.append(
                    f"[{hit.get('category')}] {hit.get('title')} "
                    f"(Score: {hit.get('score', 0):.2f})\n"
                    f"page_id: {hit.get('concept_id')}\n"
                    f"{hit.get('summary', '')}\n---"
                )
            output.append(
                "Use action 'read_research_page' with a page_id to read a "
                "full page (including raw tool-call results)."
            )
            return "\n".join(output)

        elif action == "read_research_page":
            if not page_id:
                return "Error: page_id is required for read_research_page"

            wiki = self._get_wiki()
            if wiki is None:
                return (
                    "Execution wiki is not available "
                    "(disabled or not yet initialised)."
                )
            page = await wiki.get_page(page_id)
            if not page:
                return f"No research-wiki page found for '{page_id}'"
            return (
                f"# {page.get('title')} [{page.get('concept_id')}]\n"
                f"category: {page.get('category')}\n\n"
                f"{page.get('body', '')}"
            )

        return f"Unknown action: {action}"
