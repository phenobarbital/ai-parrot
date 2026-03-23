"""Configuration models for MatrixCrewTransport.

Pydantic v2 models for configuring a multi-agent crew
operating on a Matrix homeserver via the Application Service protocol.
"""
import logging
import os
import re
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ``${ENV_VAR}`` patterns with environment variable values.

    Args:
        value: String potentially containing ``${VAR}`` placeholders.

    Returns:
        String with placeholders replaced by their env-var values.
    """

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        if not env_value:
            logger.warning("Environment variable %s is not set", var_name)
        return env_value

    return _ENV_VAR_PATTERN.sub(_replace, value)


def _walk_and_substitute(obj):
    """Recursively walk a data structure and substitute env vars in strings.

    Args:
        obj: A string, dict, list, or scalar value.

    Returns:
        The same structure with all string values env-var substituted.
    """
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _walk_and_substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_substitute(item) for item in obj]
    return obj


class MatrixCrewAgentEntry(BaseModel):
    """Configuration for a single agent in the Matrix crew.

    Attributes:
        chatbot_id: BotManager lookup key.
        display_name: Human-readable name shown in Matrix.
        mxid_localpart: Localpart of the virtual MXID (e.g. "analyst").
        avatar_url: Optional mxc:// URL for the agent's avatar.
        dedicated_room_id: Agent's own private room (optional).
        skills: Skill descriptions shown on the status board.
        tags: Routing tags for message routing.
        file_types: Accepted file MIME types.
    """

    chatbot_id: str = Field(..., description="BotManager lookup key")
    display_name: str = Field(..., description="Human-readable display name")
    mxid_localpart: str = Field(
        ..., description="Localpart for virtual MXID (e.g. 'analyst')"
    )
    avatar_url: Optional[str] = Field(
        default=None, description="mxc:// URL for agent avatar"
    )
    dedicated_room_id: Optional[str] = Field(
        default=None, description="Agent's private dedicated room ID"
    )
    skills: List[str] = Field(
        default_factory=list, description="Skill descriptions for status board"
    )
    tags: List[str] = Field(default_factory=list, description="Routing tags")
    file_types: List[str] = Field(
        default_factory=list, description="Accepted file MIME types"
    )


class MatrixCrewConfig(BaseModel):
    """Root configuration for a Matrix multi-agent crew.

    Attributes:
        homeserver_url: Matrix homeserver URL.
        server_name: Server domain name (e.g. "example.com").
        as_token: Application Service token.
        hs_token: Homeserver token.
        bot_mxid: Coordinator bot MXID.
        general_room_id: Shared room for all agents.
        agents: Mapping of agent_name to MatrixCrewAgentEntry.
        appservice_port: AS HTTP listener port.
        pinned_registry: Whether to pin the status board in the general room.
        typing_indicator: Whether to show typing while processing.
        streaming: Whether to use edit-based streaming.
        unaddressed_agent: Default agent for unmentioned messages.
        max_message_length: Chunk responses beyond this length.
    """

    homeserver_url: str = Field(..., description="Matrix homeserver URL")
    server_name: str = Field(
        ..., description="Server domain name (e.g. 'example.com')"
    )
    as_token: str = Field(..., description="Application Service token")
    hs_token: str = Field(..., description="Homeserver token")
    bot_mxid: str = Field(..., description="Coordinator bot full MXID")
    general_room_id: str = Field(..., description="Shared room ID for all agents")
    agents: Dict[str, MatrixCrewAgentEntry] = Field(
        default_factory=dict, description="agent_name → configuration"
    )
    appservice_port: int = Field(
        default=8449, description="AS HTTP listener port"
    )
    pinned_registry: bool = Field(
        default=True, description="Pin status board in general room"
    )
    typing_indicator: bool = Field(
        default=True, description="Show typing indicator while processing"
    )
    streaming: bool = Field(
        default=True, description="Use edit-based streaming for responses"
    )
    unaddressed_agent: Optional[str] = Field(
        default=None, description="Default agent for unmentioned messages"
    )
    max_message_length: int = Field(
        default=4096, description="Chunk responses beyond this length"
    )

    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewConfig":
        """Load configuration from a YAML file with ``${ENV_VAR}`` substitution.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A validated MatrixCrewConfig instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            ValidationError: If the data fails Pydantic validation.
            ValueError: If the YAML file is empty.
        """
        logger.info("Loading Matrix crew config from %s", path)
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            raise ValueError(f"Empty YAML file: {path}")
        data = _walk_and_substitute(raw)
        return cls(**data)
