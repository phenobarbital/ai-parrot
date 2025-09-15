"""
Agent Orchestration System for AI-Parrot
Agent-as-a-Tool Framework to use LLMs agents as tools in a broader system.

This implementation builds on the existing AI-parrot architecture with:
- Proper use of conversation() and invoke() methods
- Integration with existing ToolManager
- Agent-as-Tool wrapper using AbstractTool
- Support for both Orchestrator and Crew patterns
- Tool sharing between agents
"""
from typing import Dict, List, Any, Optional, Union, Callable
from dataclasses import dataclass, field
from .abstract import AbstractTool
from ..bots.agent import BasicAgent
from ..bots.abstract import AbstractBot
from ..models.responses import AIMessage, AgentResponse
from ..memory import ConversationTurn


@dataclass
class AgentContext:
    """Context passed between agents in orchestration."""
    user_id: str
    session_id: str
    original_query: str
    conversation_history: List[ConversationTurn] = field(default_factory=list)
    shared_data: Dict[str, Any] = field(default_factory=dict)
    agent_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentTool(AbstractTool):
    """
    Wraps any BasicAgent/AbstractBot as a tool for use by other agents.

    This allows agents to be used as tools in the existing ToolManager system.
    """

    def __init__(
        self,
        agent: Union[BasicAgent, AbstractBot],
        tool_name: str = None,
        tool_description: str = None,
        use_conversation_method: bool = True,
        context_filter: Optional[Callable[[AgentContext], AgentContext]] = None,
        question_description: str = "The question or request to send to the specialized agent",
        context_description: str = "Additional context information to pass to the agent"
    ):
        super().__init__()

        self.agent = agent
        self.name = tool_name or f"{agent.name.lower().replace(' ', '_')}_agent"
        self.description = tool_description or f"Specialized agent for {agent.name} related queries"
        self.use_conversation_method = use_conversation_method
        self.context_filter = context_filter

        # Track usage
        self.call_count = 0
        self.last_response = None

        # Define input schema for the tool
        self.input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": question_description
                },
                "context": {
                    "type": "object",
                    "description": context_description,
                    "properties": {
                        "user_info": {"type": "object"},
                        "shared_data": {"type": "object"},
                        "previous_results": {"type": "object"}
                    },
                    "additionalProperties": False
                }
            },
            "required": ["query"],
            "additionalProperties": False
        }

    async def _execute(self, query: str, context: Dict[str, Any] = None, **kwargs) -> str:
        """
        Execute the wrapped agent using the appropriate method.

        Uses either conversation() or invoke() based on configuration.
        """
        self.call_count += 1

        try:
            # Create AgentContext
            agent_context = AgentContext(
                user_id=context.get('user_id', 'system') if context else 'system',
                session_id=context.get('session_id', f'tool_call_{self.call_count}') if context else f'tool_call_{self.call_count}',
                original_query=query,
                shared_data=context.get(
                    'shared_data', {}
                ) if context else {},
                agent_results=context.get(
                    'previous_results', {}
                ) if context else {}
            )

            # Apply context filter if provided
            if self.context_filter:
                agent_context = self.context_filter(agent_context)

            # Choose method based on configuration and availability
            if self.use_conversation_method and hasattr(self.agent, 'conversation'):
                response = await self.agent.conversation(
                    question=query,
                    session_id=agent_context.session_id,
                    user_id=agent_context.user_id,
                    use_conversation_history=True,
                    **agent_context.shared_data
                )
            elif hasattr(self.agent, 'invoke'):
                response = await self.agent.invoke(
                    question=query,
                    session_id=agent_context.session_id,
                    user_id=agent_context.user_id,
                    use_conversation_history=True,
                    **agent_context.shared_data
                )
            else:
                # Fallback for basic agents
                # TODO: generate the chat() method if needed.
                return f"Agent {self.agent.name} does not support conversation or invoke methods"

            # Extract content from response
            if isinstance(response, (AIMessage, AgentResponse)):
                result = response.content
            elif hasattr(response, 'content'):
                result = response.content
            else:
                result = str(response)

            self.last_response = result
            return result

        except Exception as e:
            error_msg = f"Error executing {self.name}: {str(e)}"
            return error_msg

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics for this agent tool."""
        return {
            'name': self.name,
            'agent_name': self.agent.name,
            'call_count': self.call_count,
            'last_response_length': len(self.last_response) if self.last_response else 0
        }
