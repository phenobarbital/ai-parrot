"""Escalation action that opens a ticket in an external system."""
from typing import Any, Dict
from navconfig.logging import logging
from .base import EscalationAction


class TicketAction(EscalationAction):
    """Opens a ticket in Zammad/Zendesk."""

    def __init__(self):
        self.logger = logging.getLogger("parrot.human.actions.ticket")

    async def execute(self, interaction, tier) -> Dict[str, Any]:
        platform = tier.action_metadata.get("platform", "zammad")
        # In a real implementation, we would call the Zammad/Zendesk API here.
        # For now, we simulate the ticket creation.
        self.logger.info(
            f"Simulating TICKET creation on {platform} for "
            f"interaction {interaction.interaction_id}"
        )
        
        return {
            "ticket_id": "SIM-12345",
            "platform": platform,
            "status": "opened",
            "url": f"https://{platform}.example.com/tickets/SIM-12345",
            "message": f"Escalated to {platform.capitalize()}: Ticket #SIM-12345 has been opened."
        }
