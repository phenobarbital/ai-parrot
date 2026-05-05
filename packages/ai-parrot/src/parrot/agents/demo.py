"""HITL Demo Agent — Travel Concierge.

This module defines the ``HITLDemoAgent`` ("Travel Concierge") registered as
``hitl_demo`` in the agent registry. It demonstrates the full web HITL flow:

1. Uses :class:`~parrot.handlers.web_hitl.WebHumanTool` (single_choice) to
   ask the user to pick a travel destination.
2. Uses :class:`~parrot.handlers.web_hitl.WebHumanTool` (free_text) to ask
   for the desired travel date.
3. Calls :class:`BookFlightTool` with the supplied destination and date.
   - If the date is malformed, ``BookFlightTool`` raises
     :class:`~parrot.core.exceptions.HumanInteractionInterrupt`, exercising
     the ``HandoffTool`` resume path.
   - If the date is valid, a fake confirmation string is returned.
4. Summarises the trip for the user.

Usage (via the web HITL stack)::

    POST /api/v1/agents/chat/hitl_demo
    {
        "query": "I want to book a flight",
        "session_id": "my-session-id",
        "ws_channel_id": "my-session-id"
    }
"""
from __future__ import annotations

import logging
import re
from typing import Any, List, Optional, Type

from pydantic import BaseModel, Field

from parrot.bots.agent import BasicAgent
from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.core.tools.handoff import HandoffTool
from parrot.handlers.web_hitl import WebHumanTool
from parrot.registry import register_agent
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BookFlightTool
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BookFlightSchema(AbstractToolArgsSchema):
    """Arguments for the BookFlightTool."""

    destination: str = Field(
        ...,
        description="Travel destination city or airport (e.g. 'Paris', 'CDG').",
    )
    date: str = Field(
        ...,
        description=(
            "Departure date in YYYY-MM-DD format (e.g. '2026-06-15'). "
            "If the date is not in this format, the booking will be rejected."
        ),
    )


class BookFlightTool(AbstractTool):
    """Demo tool that books a flight — or raises an interrupt on invalid input.

    Accepts a *destination* and a *date*. If the date does not match
    ``YYYY-MM-DD``, raises :class:`~parrot.core.exceptions.HumanInteractionInterrupt`
    so the agent can ask the user to provide a corrected date via the handoff
    path. On a valid date, returns a fake booking confirmation string.

    Attributes:
        name: Tool name as registered in the LLM function-calling schema.
    """

    name: str = "book_flight"
    description: str = (
        "Book a flight to a destination on a specific date. "
        "The date MUST be in YYYY-MM-DD format; the tool will reject other "
        "formats and ask you to collect the correct date from the user."
    )
    args_schema: Type[BaseModel] = BookFlightSchema

    async def _execute(self, destination: str, date: str, **kwargs: Any) -> str:
        """Attempt to book a flight.

        Args:
            destination: Travel destination.
            date: Departure date in ``YYYY-MM-DD`` format.
            **kwargs: Ignored.

        Returns:
            A confirmation string when the booking succeeds.

        Raises:
            HumanInteractionInterrupt: When ``date`` does not match the expected
                format, signalling that the user must supply a corrected value.
        """
        if not _DATE_RE.match(date):
            logger.info(
                "BookFlightTool: invalid date '%s' — raising HumanInteractionInterrupt.",
                date,
            )
            raise HumanInteractionInterrupt(
                prompt=(
                    f"The date '{date}' is not in YYYY-MM-DD format "
                    f"(e.g. 2026-06-15). Please provide the departure date "
                    f"for your trip to {destination} in the correct format."
                )
            )

        confirmation = (
            f"Booking confirmation: Flight to {destination} on {date}. "
            f"Confirmation number: DEMO-{destination[:3].upper()}-{date.replace('-', '')}"
        )
        logger.info("BookFlightTool: booked flight — %s", confirmation)
        return confirmation


# ---------------------------------------------------------------------------
# HITLDemoAgent
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the Travel Concierge, a friendly AI assistant that helps users book flights.

Your workflow:
1. Greet the user and use 'ask_human' (single_choice) to ask them to pick a destination
   from a short list. Include at least: Paris, Tokyo, New York, Sydney, and London.
   Always add a 'skip' option so the user can exit.
2. Use 'ask_human' (free_text) to ask for the desired departure date in YYYY-MM-DD format.
3. Call 'book_flight' with the chosen destination and date.
   - If the date is invalid, the tool will raise an interrupt. The runtime will return
     the user's corrected date to you. Use that to retry the booking.
   - If successful, summarise the trip and the confirmation number for the user.

Important guidelines:
- Always be polite and concise.
- After collecting the destination and date, confirm them with the user before booking.
- If the user picks 'skip' at any point, acknowledge and end the conversation gracefully.
- If 'book_flight' fails due to an invalid date, tell the user what format is required.
"""


@register_agent(name="hitl_demo", at_startup=True)
class HITLDemoAgent(BasicAgent):
    """Travel Concierge — demonstrates the web HITL (Human-in-the-Loop) flow.

    This agent uses :class:`~parrot.handlers.web_hitl.WebHumanTool` to ask
    interactive questions over WebSocket, :class:`BookFlightTool` to simulate
    flight booking (with intentional ``HumanInteractionInterrupt`` on bad dates),
    and :class:`~parrot.core.tools.handoff.HandoffTool` for explicit handoff.

    Attributes:
        agent_id: Registry name for this agent, fixed to ``"hitl_demo"``.
    """

    agent_id: str = "hitl_demo"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialise the HITLDemoAgent.

        Args:
            *args: Forwarded to :class:`~parrot.bots.agent.BasicAgent`.
            **kwargs: Forwarded to :class:`~parrot.bots.agent.BasicAgent`.
        """
        super().__init__(
            *args,
            name="Travel Concierge",
            agent_id="hitl_demo",
            use_llm="google",
            system_prompt=_SYSTEM_PROMPT,
            use_tools=True,
            **kwargs,
        )
        self.logger = logging.getLogger(__name__)

    def agent_tools(self) -> List[AbstractTool]:
        """Return the tools used by this agent.

        Returns:
            A list containing :class:`WebHumanTool`, :class:`HandoffTool`,
            and :class:`BookFlightTool`.
        """
        return [
            WebHumanTool(source_agent="hitl_demo"),
            HandoffTool(),
            BookFlightTool(),
        ]
