# -*- coding: utf-8 -*-
"""Handoff Tool implementation for Parrot Core."""

from typing import Any, Type
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.core.exceptions import HumanInteractionInterrupt


class HandoffToolSchema(AbstractToolArgsSchema):
    """Arguments for the HandoffTool."""
    prompt: str = Field(
        ...,
        description="The detailed text prompt to send to the human user asking for the required information."
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

    def _execute(self, prompt: str, **kwargs: Any) -> Any:
        """Execute the handoff tool synchronously."""
        raise HumanInteractionInterrupt(prompt=prompt)

    async def _aexecute(self, prompt: str, **kwargs: Any) -> Any:
        """Execute the handoff tool asynchronously."""
        # Note: AbstractTool in ai-parrot typically wraps the async/sync logic,
        # but we implement _aexecute to be safe if the base class prefers it for async workloads.
        raise HumanInteractionInterrupt(prompt=prompt)
