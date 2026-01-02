"""
A2A-Enhanced Orchestrator Agent.

This module provides an OrchestratorAgent with built-in A2A (Agent-to-Agent) 
communication capabilities, enabling hybrid orchestration across local and remote agents.
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional, Union, Type
from pydantic import BaseModel, Field

from ...tools.abstract import AbstractTool, AbstractToolArgsSchema
from ...a2a.mixin import A2AClientMixin
from ...a2a.client import A2AClient, A2AAgentConnection
from .agent import OrchestratorAgent


# ─────────────────────────────────────────────────────────────────────────────
# Discovery Tool
# ─────────────────────────────────────────────────────────────────────────────

class DiscoverA2AAgentsInput(AbstractToolArgsSchema):
    """Input schema for ListAvailableA2AAgentsTool."""
    endpoints: Optional[List[str]] = Field(
        None,
        description="Optional list of A2A agent endpoint URLs to probe. If not provided, returns currently connected agents."
    )
    register_as_tools: bool = Field(
        default=True,
        description="If True, register discovered agents as callable tools"
    )


class ListAvailableA2AAgentsTool(AbstractTool):
    """
    Tool that discovers available A2A agents from specified endpoints.

    This tool allows the LLM to dynamically discover what remote agents
    are available for orchestration tasks.
    """

    name: str = "list_available_a2a_agents"
    description: str = (
        "Discover and list available remote A2A agents. "
        "Can probe new endpoints or list currently connected agents. "
        "Use this to find out what remote agents are available before calling them."
    )
    args_schema: Type[BaseModel] = DiscoverA2AAgentsInput

    def __init__(self, orchestrator: "A2AOrchestratorAgent", **kwargs):
        """
        Initialize the discovery tool.

        Args:
            orchestrator: The A2AOrchestratorAgent instance to manage connections
        """
        self.orchestrator = orchestrator
        self.tags = ["a2a", "discovery", "orchestration"]
        super().__init__(**kwargs)

    async def _execute(
        self,
        endpoints: Optional[List[str]] = None,
        register_as_tools: bool = True,
        **kwargs
    ) -> str:
        """
        Execute the discovery tool.

        Args:
            endpoints: Optional list of URLs to probe for A2A agents
            register_as_tools: Whether to register discovered agents as tools

        Returns:
            A formatted string describing available agents
        """
        results = []

        # If endpoints provided, try to connect to them
        if endpoints:
            for url in endpoints:
                try:
                    connection = await self.orchestrator.add_a2a_agent(
                        url,
                        register_as_tool=register_as_tools,
                    )
                    agent_info = {
                        "name": connection.name,
                        "url": connection.url,
                        "description": connection.card.description,
                        "skills": [
                            {"id": s.id, "name": s.name, "description": s.description}
                            for s in connection.card.skills
                        ],
                        "status": "connected"
                    }
                    results.append(agent_info)
                except Exception as e:
                    results.append({
                        "url": url,
                        "status": "error",
                        "error": str(e)
                    })
        else:
            # Return currently connected agents
            for name in self.orchestrator.list_a2a_agents():
                conn = self.orchestrator.get_a2a_agent(name)
                if conn:
                    agent_info = {
                        "name": conn.name,
                        "url": conn.url,
                        "description": conn.card.description,
                        "skills": [
                            {"id": s.id, "name": s.name, "description": s.description}
                            for s in conn.card.skills
                        ],
                        "status": "connected"
                    }
                    results.append(agent_info)

        if not results:
            return "No A2A agents are currently connected. Provide endpoint URLs to discover new agents."

        # Format results
        lines = ["Available A2A Agents:"]
        for agent in results:
            if agent.get("status") == "error":
                lines.append(f"\n❌ {agent['url']}: {agent.get('error', 'Connection failed')}")
            else:
                lines.append(f"\n✅ {agent['name']} ({agent['url']})")
                lines.append(f"   Description: {agent.get('description', 'N/A')}")
                if agent.get("skills"):
                    lines.append("   Skills:")
                    for skill in agent["skills"]:
                        lines.append(f"      - {skill['name']}: {skill['description']}")
                lines.append(f"   Tool name: ask_{agent['name']}")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# A2A Orchestrator Agent
# ─────────────────────────────────────────────────────────────────────────────

class A2AOrchestratorAgent(A2AClientMixin, OrchestratorAgent):
    """
    An orchestrator agent that supports both local and remote A2A agents.

    This class combines the OrchestratorAgent's ability to coordinate local
    specialized agents with A2AClientMixin's remote agent communication.

    Features:
        - Add local agents with add_agent()
        - Add remote A2A agents with add_a2a_agent()  
        - Both types become callable tools for the LLM
        - Built-in discovery tool for finding remote agents
        - Enhanced system prompt explaining hybrid orchestration

    Example:
        orchestrator = A2AOrchestratorAgent(
            name="HybridOrchestrator",
            llm="google:gemini-2.0-flash"
        )
        await orchestrator.configure()

        # Add local agents
        local_agent = BasicAgent(name="Analyst", llm="openai:gpt-4")
        await local_agent.configure()
        orchestrator.add_agent(local_agent)

        # Add remote A2A agents
        await orchestrator.add_a2a_agent("http://localhost:8082")
        await orchestrator.add_a2a_agent("http://localhost:8083")

        # Now orchestrator can use both local and remote agents
        response = await orchestrator.ask("Analyze data and summarize")
    """

    def __init__(
        self,
        name: str = "A2AOrchestratorAgent",
        orchestration_prompt: str = None,
        a2a_endpoints: Optional[List[str]] = None,
        auto_discover: bool = False,
        **kwargs
    ):
        """
        Initialize the A2A-enhanced orchestrator.

        Args:
            name: Name of the orchestrator
            orchestration_prompt: Custom system prompt (optional)
            a2a_endpoints: List of A2A agent URLs to connect to on startup
            auto_discover: If True, automatically discover agents from endpoints
            **kwargs: Additional arguments for parent classes
        """
        super().__init__(name=name, orchestration_prompt=orchestration_prompt, **kwargs)

        # A2A-specific initialization
        self._a2a_endpoints = a2a_endpoints or []
        self._auto_discover = auto_discover
        self._discovery_tool: Optional[ListAvailableA2AAgentsTool] = None

        # Set enhanced system prompt if not custom provided
        if not orchestration_prompt:
            self._set_a2a_orchestration_prompt()

    def _set_a2a_orchestration_prompt(self):
        """Set system prompt for hybrid orchestration behavior."""
        self.system_prompt_template = """
You are an orchestrator agent that coordinates multiple specialized agents to provide comprehensive answers.
You have access to TWO types of agents:

## Local Agents
Local agents are specialized AI assistants running in the same process. They are fast and reliable.
Each local agent is available as a tool named `ask_<agent_name>`.

## Remote A2A Agents  
Remote A2A agents are external agents accessible via the A2A (Agent-to-Agent) protocol over HTTP.
They may provide capabilities not available locally (specialized tools, databases, APIs, etc.).
Each remote agent is available as a tool named `ask_<agent_name>`.

## Discovering Remote Agents
Use the `list_available_a2a_agents` tool to:
- See what remote agents are currently connected
- Connect to new remote agents by providing their URLs
- Find out what skills each remote agent offers

## Your Responsibilities
1. Analyze user queries to understand what type of information/action is needed
2. Decide which agents (local or remote) to consult based on their capabilities
3. Call the appropriate agent tools with well-formed queries
4. Coordinate between multiple agents when different perspectives are needed
5. Synthesize responses from multiple agents into a coherent, comprehensive answer

## Guidelines
- YOU MUST USE AT LEAST ONE SPECIALIZED AGENT FOR EVERY REQUEST
- DO NOT ANSWER DIRECTLY USING YOUR OWN KNOWLEDGE
- Always explain which agents you're consulting and why
- For complex tasks, consider using multiple agents in sequence or parallel
- If you're unsure which agent can help, use `list_available_a2a_agents` to check capabilities
- Provide a unified answer that addresses all aspects of the user's question
- Always maintain context and avoid redundant information

## Available Agents
The specialized agents (both local and remote) will be provided as tools you can call.
Use `list_available_a2a_agents` to discover remote agents if needed.
"""

    async def configure(self, app=None) -> None:
        """
        Configure the A2AOrchestratorAgent.

        This sets up:
        - Base orchestrator configuration
        - The discovery tool
        - Auto-connects to configured A2A endpoints
        """
        await super().configure(app)

        # Add discovery tool
        self._discovery_tool = ListAvailableA2AAgentsTool(self)
        self.tool_manager.register_tool(self._discovery_tool)

        # Connect to pre-configured endpoints
        if self._a2a_endpoints and self._auto_discover:
            for endpoint in self._a2a_endpoints:
                try:
                    await self.add_a2a_agent(endpoint)
                except Exception as e:
                    self.logger.warning(f"Failed to connect to A2A agent at {endpoint}: {e}")

        # Sync tools to LLM
        if self._llm:
            self._sync_tools_to_llm()

    def list_all_agents(self) -> Dict[str, List[str]]:
        """
        List all agents (both local and remote).

        Returns:
            Dict with 'local' and 'remote' keys containing agent names
        """
        return {
            "local": self.list_agents(),
            "remote": self.list_a2a_agents(),
        }

    def get_all_agent_stats(self) -> Dict[str, Any]:
        """
        Get statistics about all agent usage.

        Returns:
            Dict with orchestration stats and A2A connection info
        """
        stats = self.get_orchestration_stats()
        stats["remote_agents"] = {
            name: {
                "url": conn.url,
                "skills": [s.name for s in conn.card.skills],
            }
            for name, conn in self._a2a_clients.items()
        }
        return stats

    async def shutdown(self, **kwargs) -> None:
        """Shutdown orchestrator and cleanup all connections."""
        # A2AClientMixin.shutdown_a2a() is called via super() chain
        await super().shutdown(**kwargs)
