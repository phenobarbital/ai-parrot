# -*- coding: utf-8 -*-
"""Handoff Tool implementation for Parrot Core.

.. deprecated::
    Use :class:`parrot.human.tool.HumanTool` with ``policy_id`` for tiered
    escalation.  ``HandoffTool`` is kept for backward compatibility and will
    be removed in a future release.
"""

import asyncio
import warnings
from typing import Any, Optional, Type

from pydantic import BaseModel, Field

from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema


class HandoffToolSchema(AbstractToolArgsSchema):
    """Arguments for the HandoffTool."""

    prompt: str = Field(
        ...,
        description=(
            "The detailed text prompt to send to the human user asking "
            "for the required information."
        ),
    )
    policy_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional ID of the tiered escalation policy to follow if "
            "the user does not respond."
        ),
    )


class HandoffTool(AbstractTool):
    """Tool for handing off task execution to a human user.

    .. deprecated::
        Prefer :class:`parrot.human.tool.HumanTool` with ``policy_id``
        for new code that requires tiered escalation.  ``HandoffTool``
        raises ``HumanInteractionInterrupt`` which requires the
        orchestrator to suspend the agent; ``HumanTool`` awaits the
        interaction directly and avoids the suspend/resume cycle
        entirely.

    When an agent does not have enough information to complete a task,
    it can call this tool with a prompt.  The tool attempts a short
    bounded poll (5 × 100 ms) for an already-resolved result from the
    manager.  If the result is available within the window, it is
    returned immediately and the agent is never suspended.  If not, the
    legacy ``HumanInteractionInterrupt`` is raised so the
    orchestrator's existing suspend/resume path takes over.
    """

    _deprecation_warned: bool = False  # class-level — fires once per process

    name: str = "handoff_to_human"
    description: str = (
        "DEPRECATED — prefer ask_human (HumanTool) for new code. "
        "Use this tool when you need information from a human user to "
        "explicitly continue your current task. Provide a clear, detailed "
        "prompt explaining what you need. Calling this will pause your "
        "execution until the user replies."
    )
    args_schema: Type[BaseModel] = HandoffToolSchema
    return_direct: bool = False

    def __init__(self, manager: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.manager = manager
        if not HandoffTool._deprecation_warned:
            warnings.warn(
                "HandoffTool is deprecated; prefer HumanTool with policy_id "
                "for tiered escalation. See "
                "documentation/hitl_tiered_escalation_example.md.",
                DeprecationWarning,
                stacklevel=2,
            )
            HandoffTool._deprecation_warned = True

    async def _aexecute(
        self,
        prompt: str,
        policy_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """Execute the handoff tool asynchronously.

        Registers the interaction with the HITL manager, then polls for
        an immediately-resolved result (bounded to 5 × 100 ms).  Returns
        the resolved value without raising if available; otherwise falls
        back to raising :exc:`~parrot.core.exceptions.HumanInteractionInterrupt`.

        Args:
            prompt: The question or request to present to the human.
            policy_id: Optional escalation policy ID passed to the manager.
            **kwargs: Extra kwargs forwarded to the manager (e.g., ``channel``).

        Returns:
            The resolved string value from the manager when the interaction
            completes within the polling window.

        Raises:
            HumanInteractionInterrupt: When the interaction does not
                resolve within the polling window, or when no manager is
                configured.
        """
        interaction_id = None

        if self.manager:
            from parrot.human.models import HumanInteraction, InteractionType

            interaction = HumanInteraction(
                question=prompt,
                interaction_type=InteractionType.FREE_TEXT,
                policy_id=policy_id,
                source_agent=getattr(self, "source_agent", None),
            )

            try:
                # Register the interaction so the tiered escalation cycle starts.
                interaction_id = await self.manager.request_human_input_async(
                    interaction,
                    channel=kwargs.get("channel", "telegram"),
                )
            except Exception:
                # If registration fails, fall through to the interrupt path.
                pass
            else:
                # Short bounded poll (≤ 500 ms) for an already-resolved result.
                # Non-INTERACT starting tiers (Notify, Ticket) may resolve
                # fire-and-forget before the loop finishes.
                for _ in range(5):
                    await asyncio.sleep(0.1)
                    result = await self.manager.get_result(interaction_id)
                    if result is not None:
                        msg = (result.action_metadata or {}).get("message")
                        if msg:
                            return msg
                        if result.consolidated_value is not None:
                            return result.consolidated_value
                        # Resolved but empty value — fall through to interrupt.
                        break

        raise HumanInteractionInterrupt(
            prompt=prompt,
            interaction_id=interaction_id,
            policy_id=policy_id,
        )

    def _execute(self, prompt: str, **kwargs: Any) -> Any:
        """Fallback for synchronous execution — always raises interrupt."""
        raise HumanInteractionInterrupt(prompt=prompt)
