from typing import Any, Dict, Optional, List
from parrot.tools.abstract import AbstractTool
from .storage.memory import ExecutionMemory

class ResultRetrievalTool(AbstractTool):
    name = "execution_context_tool"
    description = "Retrieve detailed execution results and context from agents. Use this tool when you need more specific details about what an agent found than what is provided in the summary."
    
    def __init__(self, memory: ExecutionMemory):
        self.memory = memory

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_agents", "get_agent_result", "search_results"],
                        "description": "Action to perform: list available agents, get specific result, or search across results."
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent (required for 'get_agent_result')"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query (required for 'search_results')"
                    }
                },
                "required": ["action"]
            }
        }

    async def _execute(self, action: str, agent_id: Optional[str] = None, query: Optional[str] = None) -> str:
        if action == "list_agents":
            agents = self.memory.execution_order
            return f"Agents with available results: {', '.join(agents)}"
            
        elif action == "get_agent_result":
            if not agent_id:
                return "Error: agent_id is required for get_agent_result"
                
            result = self.memory.get_results_by_agent(agent_id)
            if result:
                # Return full text but warn if too large? 
                # AgentResult.to_text() handles formatting
                return f"Result for {agent_id}:\n{result.to_text()}"
            return f"No result found for agent_id: {agent_id}"
            
        elif action == "search_results":
            if not query:
                return "Error: query is required for search_results"
                
            # Perform semantic search on memory
            # normalize threshold? using default from memory search
            results = self.memory.search_similar(query, top_k=5)
            if not results:
                return f"No relevant results found for '{query}'"
                
            output = []
            for chunk, res, score in results:
                output.append(f"Match (Score: {score:.2f}) from {res.agent_name}:\n{chunk}\n---")
            
            return "\n".join(output)
            
        return f"Unknown action: {action}"
