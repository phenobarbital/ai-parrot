# -*- coding: utf-8 -*-
"""Handoff Tool implementation for Parrot Core."""

from typing import Any, Optional, Type
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.core.exceptions import HumanInteractionInterrupt


class HandoffToolSchema(AbstractToolArgsSchema):
    """Arguments for the HandoffTool."""
    prompt: str = Field(
        ...,
        description="The detailed text prompt to send to the human user asking for the required information."
    )
    policy_id: Optional[str] = Field(
        default=None,
        description="Optional ID of the tiered escalation policy to follow if the user doesn't respond."
    )


class HandoffTool(AbstractTool):
    """
    Tool for handing off task execution to a human user.
    
    When an agent does not have enough information to complete a task, it can
    call this tool with a prompt. Calling this tool immediately suspends the
    agent's current execution and sends the prompt to the human user (e.g., via
    Slack, Telegram). The agent will resume once the human replies.
    """
    name: str = "handoff_to_human"
    description: str = (
        "Use this tool when you need information from a human user to explicitly continue "
        "your current task. Provide a clear, detailed prompt explaining what you need. "
        "Calling this will pause your execution until the user replies."
    )
    args_schema: Type[BaseModel] = HandoffToolSchema
    return_direct: bool = False

    def __init__(self, manager: Any = None, **kwargs):
        super().__init__(**kwargs)
        self.manager = manager

    async def _aexecute(self, prompt: str, policy_id: Optional[str] = None, **kwargs: Any) -> Any:
        """Execute the handoff tool asynchronously and register it with the HITL manager."""
        interaction_id = None
        
        if self.manager:
            from parrot.human.models import HumanInteraction, InteractionType
            
            interaction = HumanInteraction(
                question=prompt,
                interaction_type=InteractionType.FREE_TEXT,
                policy_id=policy_id,
                source_agent=getattr(self, "source_agent", None)
            )
            
            try:
                # Register the interaction so it starts the tiered escalation cycle
                interaction_id = await self.manager.request_human_input_async(
                    interaction,
                    channel=kwargs.get("channel", "telegram")
                )
            except Exception:
                # Fallback to pure interrupt if manager fails
                pass

        raise HumanInteractionInterrupt(
            prompt=prompt, 
            interaction_id=interaction_id,
            policy_id=policy_id
        )

    def _execute(self, prompt: str, **kwargs: Any) -> Any:
        """Fallback for sync execution."""
        raise HumanInteractionInterrupt(prompt=prompt)
