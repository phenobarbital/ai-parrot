"""Pydantic configuration models for Matrix Application Service."""
from __future__ import annotations
from typing import Dict, List
from pydantic import BaseModel, Field


class MatrixAppServiceConfig(BaseModel):
    """Configuration for Matrix Application Service mode."""

    # Tokens (shared secrets between AS and homeserver)
    as_token: str
    hs_token: str

    # Homeserver connection
    homeserver: str = "http://localhost:8008"
    server_name: str = "parrot.local"

    # AS HTTP listener (receives events from homeserver)
    listen_host: str = "0.0.0.0"
    listen_port: int = 9090

    # Bot identity
    bot_localpart: str = "parrot"
    as_id: str = "ai-parrot"

    # Virtual user namespace
    namespace_regex: str = "parrot-.*"

    # Agent → MXID mapping (agent_name → localpart)
    agent_mxid_map: Dict[str, str] = Field(default_factory=dict)

    # Rooms the bot should auto-join
    auto_join_rooms: List[str] = Field(default_factory=list)

    @property
    def bot_mxid(self) -> str:
        """Full MXID of the AS bot user."""
        return f"@{self.bot_localpart}:{self.server_name}"

    def agent_mxid(self, agent_name: str) -> str:
        """Full MXID for a named agent."""
        localpart = self.agent_mxid_map.get(
            agent_name,
            f"parrot-{agent_name.lower().replace(' ', '-')}",
        )
        return f"@{localpart}:{self.server_name}"

