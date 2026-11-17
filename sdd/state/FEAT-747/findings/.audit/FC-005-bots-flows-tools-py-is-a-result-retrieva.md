---
id: FC-005
query_id: Q025
type: read
intent: "Read bots/flows/tools.py: the existing agent-callable tools for delegation (origin tools for request/cfp)."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-005 — bots/flows/tools.py is a result-retrieval tool returning text

## Summary

`bots/flows/tools.py` defines only `ResultRetrievalTool` (`execution_context_tool`), which lets an agent read other agents' results from the crew's `ExecutionMemory` — actions `list_agents`, `get_agent_result`, `search_results`, `search_research`, `read_research_page`. Every action returns a human-readable **string** (`result.to_text()`); it is read-only and never sends anything to another agent. No delegate/ask_agent/cfp origin tool lives here.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/tools.py`
  lines: 16-48
  symbol: `ResultRetrievalTool`
  excerpt: |
    class ResultRetrievalTool(AbstractTool):
        name = "execution_context_tool"
        description = ("Retrieve detailed execution results and context from agents. ...")

- path: `packages/ai-parrot/src/parrot/bots/flows/tools.py`
  lines: 124-156
  symbol: `ResultRetrievalTool._execute`
  excerpt: |
    async def _execute(self, action: str, agent_id=None, query=None, page_id=None) -> str:
        if action == "list_agents":
            agents = self.memory.execution_order
            return f"Agents with available results: {', '.join(agents)}"
        elif action == "get_agent_result":
            result = self.memory.get_results_by_agent(agent_id)
            if result:
                return f"Result for {agent_id}:\n{result.to_text()}"


## Notes

The agent-to-agent *sending* tools found in this lane are `AgentSwarmToolkit.ask_agent/post_to_channel` (Matrix, FC-008) and the A2A client tools in ToolManager (FC-014). `[cross-lane: type=wiki_query, intent=confirm whether an AgentTool / agents-as-tools wrapper exists in parrot.bots (FW-003 may cover it)]`
