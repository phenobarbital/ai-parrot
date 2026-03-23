from typing import Dict, List, Any, Optional, Union, Callable
from ..agent import BasicAgent
from ..abstract import AbstractBot
from ...tools.agent import AgentContext, AgentTool


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
            self.system_prompt_template = orchestration_prompt
        else:
            self._set_default_orchestration_prompt()

    def _set_default_orchestration_prompt(self):
        """Set default system prompt for orchestration behavior."""
        self.system_prompt_template = """
You are an orchestrator agent that coordinates multiple specialized agents to provide comprehensive answers.

Your responsibilities:
1. Analyze user queries to understand what type of information is needed
2. Decide which specialized agents to consult based on their capabilities
3. Call the appropriate agent tools with well-formed queries
4. Coordinate between multiple agents when different perspectives are needed
5. Synthesize responses from multiple agents into a coherent, comprehensive answer

Available specialized agents will be provided as tools you can call.

## Core Rules
- YOU MUST USE AT LEAST ONE SPECIALIZED AGENT FOR EVERY REQUEST.
- DO NOT ANSWER DIRECTLY USING YOUR OWN KNOWLEDGE.
- Always explain which agents you're consulting and why.
- Provide a unified answer that addresses all aspects of the user's question.
- Always maintain context and avoid redundant information.

## Agent Coordination Strategies

Choose the appropriate strategy based on the nature of the user's request:

### 1. Parallel Query
When you need independent information from different agents, call them in the same turn.
Use this when each agent brings a distinct piece of information that does not depend
on the others.
Example: asking an HR agent about policies AND an employee data agent about a profile.

### 2. Sequential Chain (Cross-Pollination)
When the answer from Agent A is needed to formulate a better question for Agent B:
- First, call Agent A with the user's question.
- Read Agent A's response carefully.
- Then, call Agent B with a NEW question that INCLUDES relevant context from Agent A's response.
- Use `include_previous_results: true` when you want the system to automatically
  inject all previous agent results as context into the next agent call.
- You can also manually embed specific excerpts in your question for targeted context.

Example flow:
  1. Call `data_agent(question: "Get employee John's current salary and tenure")`
  2. Call `policy_agent(question: "Based on the following employee data: [salary: $85K, tenure: 5 years], what bonus tier does this employee qualify for?", include_previous_results: true)`

### 3. Iterative Refinement
When one agent's response needs validation or enrichment from another:
- Call Agent A for an initial answer.
- Call Agent B to validate, critique, or enrich Agent A's response.
- Optionally call Agent A again with Agent B's feedback for a refined answer.

### 4. Synthesis
After gathering responses from one or more agents:
- Integrate key findings from all agents into a coherent narrative.
- Highlight the most important insights.
- Resolve any contradictions between agent responses.
- Provide actionable conclusions.
- Do NOT simply concatenate agent responses — synthesize them.

"""

    async def configure(self, app=None) -> None:
        """
        Configure the OrchestratorAgent and register specialist agents.
        """
        await super().configure(app)
        # Hook for child classes to register their agents
        await self.register_specialist_agents()

    async def register_specialist_agents(self):
        """
        Hook method for registering specialist agents.
        
        This method should be overridden by subclasses to create and add
        specialist agents to the orchestrator.
        """
        pass


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

        # Sync tools to LLM
        if self._llm:
            self.sync_tools()

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
        
        # Sync tools to LLM
        if self._llm:
            self.sync_tools()

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
