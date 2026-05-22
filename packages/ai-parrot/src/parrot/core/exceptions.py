# -*- coding: utf-8 -*-
"""Exception Definitions for Parrot Core.

This module contains custom exceptions used by the autonomous orchestrator
and core agent runtimes.
"""

from typing import Optional
from parrot.exceptions import ParrotError


class HumanInteractionInterrupt(ParrotError):
    """Raised when an agent tool requests human interaction to continue.
    
    This interrupt is meant to be caught by the orchestrator so it can suspend
    the current execution state and propagate the prompt out to the user via
    a chat integration.
    """

    def __init__(
        self, 
        prompt: str, 
        interaction_id: Optional[str] = None,
        policy_id: Optional[str] = None,
        *args, **kwargs
    ):
        """Initialize the interrupt.
        
        Args:
            prompt: The text prompt the agent wants to send to the human.
            interaction_id: Optional UUID of the persisted interaction in parrot.human.
            policy_id: Optional ID of the escalation policy to follow.
        """
        super().__init__(prompt, *args, **kwargs)
        self.prompt = prompt
        self.interaction_id = interaction_id
        self.policy_id = policy_id
        self.state = None
        self.tool_call_id = None
        self.agent_name = None
        self.messages = None

