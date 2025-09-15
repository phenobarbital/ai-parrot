from typing import List, Dict, Any, Union, Optional
import asyncio
import uuid
from navconfig.logging import logging
from ..agent import BasicAgent
from ..abstract import AbstractBot
from ...tools.manager import ToolManager
from ...tools.abstract import AbstractTool
from ...tools.agent import AgentContext
from ...models.responses import AIMessage, AgentResponse


class AgentCrew:
    """
    A crew where agents are called in sequence, passing results to the next agent.

    This implements a pipeline pattern where each agent processes the output
    of the previous agent in the sequence.
    """

    def __init__(
        self,
        name: str = "AgentCrew",
        agents: List[Union[BasicAgent, AbstractBot]] = None,
        shared_tool_manager: ToolManager = None
    ):
        self.name = name
        self.agents: List[Union[BasicAgent, AbstractBot]] = agents or []
        self.shared_tool_manager = shared_tool_manager or ToolManager()
        self.execution_log: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(f"parrot.crews.{self.name}")

        # Share tools across all agents if shared tool manager is provided
        if shared_tool_manager:
            self._setup_shared_tools()

    def _setup_shared_tools(self):
        """Setup shared tools across all agents in the crew."""
        for agent in self.agents:
            # Merge shared tools into each agent's tool manager
            for tool_name in self.shared_tool_manager.list_tools():
                tool = self.shared_tool_manager.get_tool(tool_name)
                if tool and not agent.tool_manager.get_tool(tool_name):
                    agent.tool_manager.add_tool(tool, tool_name)

    def add_agent(self, agent: Union[BasicAgent, AbstractBot], position: int = None) -> None:
        """
        Add an agent to the crew.

        Args:
            agent: Agent to add
            position: Position in sequence (None to append)
        """
        if position is None:
            self.agents.append(agent)
        else:
            self.agents.insert(position, agent)

        # Share tools with new agent
        if self.shared_tool_manager:
            for tool_name in self.shared_tool_manager.list_tools():
                tool = self.shared_tool_manager.get_tool(tool_name)
                if tool and not agent.tool_manager.get_tool(tool_name):
                    agent.tool_manager.add_tool(tool, tool_name)

    def remove_agent(self, agent_name: str) -> bool:
        """Remove an agent from the crew by name."""
        for i, agent in enumerate(self.agents):
            if agent.name == agent_name:
                del self.agents[i]
                return True
        return False

    def add_shared_tool(self, tool: AbstractTool, tool_name: str = None) -> None:
        """Add a tool that will be shared across all agents in the crew."""
        self.shared_tool_manager.add_tool(tool, tool_name)

        # Add to all existing agents
        for agent in self.agents:
            if not agent.tool_manager.get_tool(tool_name or tool.name):
                agent.tool_manager.add_tool(tool, tool_name)

    async def execute(
        self,
        initial_query: str,
        user_id: str = None,
        session_id: str = None,
        use_conversation_method: bool = True,
        pass_full_context: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute the crew in sequence, passing results between agents.

        Args:
            initial_query: Initial query to start the crew with
            user_id: User identifier
            session_id: Session identifier
            use_conversation_method: Whether to use conversation() or invoke()
            pass_full_context: Whether to pass full context or just previous result
            **kwargs: Additional arguments

        Returns:
            Dictionary with final result and execution log
        """
        if not self.agents:
            return {
                'final_result': 'No agents in crew',
                'execution_log': [],
                'success': False
            }

        # Setup session
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or 'crew_user'

        # Initialize context
        current_input = initial_query
        crew_context = AgentContext(
            user_id=user_id,
            session_id=session_id,
            original_query=initial_query,
            shared_data=kwargs,
            agent_results={}
        )

        self.execution_log = []

        # Execute agents in sequence
        for i, agent in enumerate(self.agents):
            try:
                agent_start_time = asyncio.get_event_loop().time()

                # Prepare input for this agent
                if i == 0:
                    # First agent gets the original query
                    agent_input = initial_query
                else:
                    # Subsequent agents get processed input
                    if pass_full_context:
                        # Include context from all previous agents
                        context_summary = self._build_context_summary(crew_context)
                        agent_input = f"Original query: {initial_query}\n\nPrevious processing:\n{context_summary}\n\nCurrent task: {current_input}"
                    else:
                        # Just use the output from previous agent
                        agent_input = current_input

                # Execute agent
                if use_conversation_method and hasattr(agent, 'conversation'):
                    response = await agent.conversation(
                        question=agent_input,
                        session_id=f"{session_id}_agent_{i}",
                        user_id=user_id,
                        use_conversation_history=False,  # Keep each agent's context separate
                        **crew_context.shared_data
                    )
                elif hasattr(agent, 'invoke'):
                    response = await agent.invoke(
                        question=agent_input,
                        session_id=f"{session_id}_agent_{i}",
                        user_id=user_id,
                        use_conversation_history=False,
                        **crew_context.shared_data
                    )
                else:
                    raise ValueError(f"Agent {agent.name} does not support conversation or invoke methods")

                # Extract result
                if isinstance(response, (AIMessage, AgentResponse)):
                    result = response.content
                elif hasattr(response, 'content'):
                    result = response.content
                else:
                    result = str(response)

                agent_end_time = asyncio.get_event_loop().time()
                execution_time = agent_end_time - agent_start_time

                # Log execution
                log_entry = {
                    'agent_name': agent.name,
                    'agent_index': i,
                    'input': agent_input,
                    'output': result,
                    'execution_time': execution_time,
                    'success': True
                }
                self.execution_log.append(log_entry)

                # Store result in context
                crew_context.agent_results[agent.name] = result

                # Prepare input for next agent
                current_input = result

            except Exception as e:
                error_msg = f"Error executing agent {agent.name}: {str(e)}"
                log_entry = {
                    'agent_name': agent.name,
                    'agent_index': i,
                    'input': current_input,
                    'output': error_msg,
                    'execution_time': 0,
                    'success': False,
                    'error': str(e)
                }
                self.execution_log.append(log_entry)

                # Continue with error message as input for next agent
                current_input = f"Error from {agent.name}: {error_msg}"

        return {
            'final_result': current_input,
            'execution_log': self.execution_log,
            'agent_results': crew_context.agent_results,
            'success': all(log['success'] for log in self.execution_log)
        }

    def _build_context_summary(self, context: AgentContext) -> str:
        """Build a summary of previous agent results."""
        summaries = []
        for agent_name, result in context.agent_results.items():
            # Truncate long results
            truncated_result = result[:200] + "..." if len(result) > 200 else result
            summaries.append(f"- {agent_name}: {truncated_result}")
        return "\n".join(summaries)

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get summary of the last execution."""
        if not self.execution_log:
            return {'message': 'No executions yet'}

        total_time = sum(log['execution_time'] for log in self.execution_log)
        success_count = sum(1 for log in self.execution_log if log['success'])

        return {
            'total_agents': len(self.agents),
            'executed_agents': len(self.execution_log),
            'successful_agents': success_count,
            'total_execution_time': total_time,
            'average_time_per_agent': total_time / len(self.execution_log) if self.execution_log else 0
        }
