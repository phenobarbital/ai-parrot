"""
Complete Fixed AgentTool with Correct Schema Structure
"""
from typing import Dict, List, Any, Optional, Union, Callable
from dataclasses import dataclass, field
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool
from parrot.bots.abstract import AbstractBot, OutputMode
from parrot.models.responses import AIMessage, AgentResponse
from parrot.memory import ConversationTurn


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


class QuestionInput(BaseModel):
    """Input schema for AgentTool - defines the question parameter."""
    question: str = Field(
        ...,
        description="The question or task to ask the agent"
    )


class AgentTool(AbstractTool):
    """
    Wraps any BasicAgent/AbstractBot as a tool for use by other agents.

    - Schema includes "parameters" key for Google GenAI compatibility
    - Uses Pydantic args_schema for validation
    - Accepts all args as **kwargs in _execute()
    """

    # Use Pydantic schema for validation
    args_schema = QuestionInput

    def __init__(
        self,
        agent: AbstractBot,
        tool_name: str = None,
        tool_description: str = None,
        use_conversation_method: bool = True,
        context_filter: Optional[Callable[[AgentContext], AgentContext]] = None,
    ):
        super().__init__()

        self.agent = agent
        self.name = tool_name or f"{agent.name.lower().replace(' ', '_')}"

        # Build description
        if tool_description:
            self.description = tool_description
        else:
            # Auto-generate from agent properties
            desc_parts = []
            if hasattr(agent, 'role') and agent.role:
                desc_parts.append(f"Role: {agent.role}")
            if hasattr(agent, 'goal') and agent.goal:
                desc_parts.append(f"Goal: {agent.goal}")
            if hasattr(agent, 'capabilities') and agent.capabilities:
                desc_parts.append(f"Capabilities: {agent.capabilities}")

            if desc_parts:
                self.description = f"Agent: {agent.name}. " + ". ".join(desc_parts)
            else:
                self.description = f"Consult {agent.name} for specialized assistance"

        self.use_conversation_method = use_conversation_method
        self.context_filter = context_filter

        # Track usage
        self.call_count = 0
        self.last_response = None

        # Build schema in the correct format for Google GenAI
        # CRITICAL: Must have "parameters" key at top level
        self._schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {  # ← Google GenAI extracts this key
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": f"The question or task to ask {agent.name}"
                    }
                },
                "required": ["question"],
                "additionalProperties": False
            }
        }

    def get_tool_schema(self) -> Dict[str, Any]:
        """
        Return the tool schema in the format expected by Google GenAI.

        Returns:
            Schema with structure:
            {
                "name": "tool_name",
                "description": "...",
                "parameters": {  # ← Google GenAI looks for this
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        """
        return self._schema

    async def _execute(self, **kwargs) -> str:
        """
        Execute the wrapped agent using the appropriate method.

        Args:
            **kwargs: Must include 'question' key with the question to ask.
            AbstractTool validates this using args_schema.

        Returns:
            Agent's response as a string
        """
        self.call_count += 1

        # Extract question from kwargs (validated by args_schema)
        question = kwargs.pop('question', '')

        if not question:
            return "Error: No question provided to agent tool"

        try:
            # Auto-construct context from kwargs
            user_id = kwargs.pop('user_id', 'orchestrator')
            session_id = kwargs.pop('session_id', f'tool_call_{self.call_count}')

            # Create AgentContext
            agent_context = AgentContext(
                user_id=user_id,
                session_id=session_id,
                original_query=question,
                shared_data=kwargs,
                agent_results={}
            )

            # Apply context filter if provided
            if self.context_filter:
                agent_context = self.context_filter(agent_context)

            # Choose method based on configuration and availability
            if self.use_conversation_method and hasattr(self.agent, 'conversation'):
                response = await self.agent.conversation(
                    question=question,
                    session_id=agent_context.session_id,
                    user_id=agent_context.user_id,
                    use_conversation_history=False,  # Keep tool calls stateless
                    **agent_context.shared_data
                )
            elif hasattr(self.agent, 'ask'):
                response = await self.agent.ask(
                    question=question,
                    session_id=agent_context.session_id,
                    user_id=agent_context.user_id,
                    use_conversation_history=True,
                    output_mode=OutputMode.DEFAULT,
                    **agent_context.shared_data
                )
            elif hasattr(self.agent, 'invoke'):
                response = await self.agent.invoke(
                    question=question,
                    session_id=agent_context.session_id,
                    user_id=agent_context.user_id,
                    use_conversation_history=False,
                    **agent_context.shared_data
                )
            else:
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
            self.logger.error(error_msg)
            return error_msg

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics for this agent tool."""
        return {
            'name': self.name,
            'agent_name': self.agent.name,
            'call_count': self.call_count,
            'last_response_length': len(self.last_response) if self.last_response else 0
        }
