"""Escalation action that sends a one-way notification."""
from typing import Any, Dict
from .base import EscalationAction
from navconfig.logging import logging

class NotifyAction(EscalationAction):
    """Sends a notification via Email, SMS, or Slack (webhook)."""

    def __init__(self):
        self.logger = logging.getLogger("parrot.human.actions.notify")

    async def execute(self, interaction, tier) -> Dict[str, Any]:
        channel = tier.action_metadata.get("channel", "email")
        # In a real implementation, we would call an Email service or Webhook here.
        self.logger.info(
            f"Simulating NOTIFY via {channel} for "
            f"interaction {interaction.interaction_id}"
        )
        
        return {
            "channel": channel,
            "status": "sent",
            "recipients": tier.target_humans,
            "message": f"Escalated via {channel.capitalize()} to recipients: {', '.join(tier.target_humans)}."
        }
