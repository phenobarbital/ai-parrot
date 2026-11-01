"""Legacy Jira command aliases for generic MS Teams connections."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from botbuilder.core import TurnContext

    from parrot.integrations.msteams.commands import MSTeamsCommandRouter
    from parrot.integrations.msteams.commands.connect_commands import TeamsConnector

logger = logging.getLogger(__name__)

_MSTEAMS_CHANNEL = "msteams"  # compatibility export; pinned by test_msteams_channel_constant


def register_jira_commands(router: "MSTeamsCommandRouter", connector: "TeamsConnector") -> None:
    """Register the legacy Jira commands as aliases of generic connections."""

    async def _connect(turn_context: "TurnContext") -> None:
        await connector.connect(turn_context, "jira")

    async def _disconnect(turn_context: "TurnContext") -> None:
        await connector.disconnect(turn_context, "jira")

    async def _status(turn_context: "TurnContext") -> None:
        await connector.status(turn_context, "jira")

    async def _menu(turn_context: "TurnContext") -> None:
        await connector.status(turn_context)

    for name, handler in (
        ("connect_jira", _connect),
        ("disconnect_jira", _disconnect),
        ("jira_status", _status),
        ("jira", _menu),
        ("integrations", _menu),
    ):
        router.register(name, handler)
    logger.info("Registered Jira alias commands on MSTeamsCommandRouter")
