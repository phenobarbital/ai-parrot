from typing import Dict, List, Any, Optional, Union, Callable
from parrot.bots.agent import BasicAgent
from parrot.bots.abstract import AbstractBot
from ...tools.agent import AgentContext, AgentTool
from ...tools.manager import ToolManager


class OrchestratorAgent(BasicAgent):
    """
    An orchestrator agent that can coordinate multiple specialized agents.

    This agent decides which specialists to consult and synthesizes their responses.
    """

    def __init__(
        self,
        name: str = "OrchestratorAgent",
        orchestration_prompt: str = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)

        # Store wrapped agents and their tools
        self.agent_tools: Dict[str, AgentTool] = {}
        self.specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}
        # Set orchestration-specific system prompt
        if orchestration_prompt:
            self.system_prompt = orchestration_prompt
        else:
            self._set_default_orchestration_prompt()

    def _set_default_orchestration_prompt(self):
        """Set default system prompt for orchestration behavior."""
        self.system_prompt = """
You are an orchestrator agent that coordinates multiple specialized agents to provide comprehensive answers.

Your responsibilities:
1. Analyze user queries to understand what type of information is needed
2. Decide which specialized agents to consult based on their capabilities
3. Call the appropriate agent tools with well-formed queries
4. Coordinate between multiple agents when different perspectives are needed
5. Synthesize responses from multiple agents into a coherent, comprehensive answer

Available specialized agents will be provided as tools you can call.

Guidelines for using agents:
- Always explain which agents you're consulting and why
- When multiple agents are needed, coordinate their responses thoughtfully
- Provide a unified answer that addresses all aspects of the user's question
- If no specialized agent is appropriate, answer directly using your own knowledge
- Always maintain context and avoid redundant information
"""

    def add_agent(
        self,
        agent: Union[BasicAgent, AbstractBot],
        tool_name: str = None,
        description: str = None,
        use_conversation_method: bool = True,
        context_filter: Optional[Callable[[AgentContext], AgentContext]] = None
    ) -> None:
        """
        Add a specialized agent to this orchestrator.

        Args:
            agent: The specialized agent to add
            tool_name: Custom name for the tool (optional)
            description: Description of what this agent handles
            use_conversation_method: Whether to use conversation() or invoke()
            context_filter: Optional function to filter context before passing to agent
        """
        # Create agent tool wrapper
        agent_tool = AgentTool(
            agent=agent,
            tool_name=tool_name,
            tool_description=description,
            use_conversation_method=use_conversation_method,
            context_filter=context_filter
        )

        # Store references
        self.agent_tools[agent_tool.name] = agent_tool
        self.specialist_agents[agent.name] = agent

        # Add to the existing ToolManager
        self.tool_manager.add_tool(agent_tool)

        self.logger.info(f"Added specialist agent '{agent.name}' as tool '{agent_tool.name}'")

    def remove_agent(self, agent_name: str) -> None:
        """Remove a specialized agent from this orchestrator."""
        # Find and remove the agent tool
        if tool_to_remove := next(
            (
                tool_name
                for tool_name, agent_tool in self.agent_tools.items()
                if agent_tool.agent.name == agent_name
            ),
            None,
        ):
            del self.agent_tools[tool_to_remove]
            self.tool_manager.remove_tool(tool_to_remove)
            self.logger.info(
                f"Removed agent tool: {tool_to_remove}"
            )

        if agent_name in self.specialist_agents:
            del self.specialist_agents[agent_name]
            self.logger.info(
                f"Removed specialist agent: {agent_name}"
            )

    def list_agents(self) -> List[str]:
        """List all registered specialist agents."""
        return list(self.specialist_agents.keys())

    def get_orchestration_stats(self) -> Dict[str, Any]:
        """Get statistics about agent usage in orchestration."""
        stats = {
            'total_specialists': len(self.specialist_agents),
            'agent_tools': {}
        }

        for tool_name, agent_tool in self.agent_tools.items():
            stats['agent_tools'][tool_name] = agent_tool.get_usage_stats()

        return stats
