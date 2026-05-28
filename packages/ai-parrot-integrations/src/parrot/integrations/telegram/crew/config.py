"""Configuration models for TelegramCrewTransport.

Pydantic v2 models for configuring a multi-agent crew
in a Telegram supergroup.
"""
import logging
import os
import re
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _substitute_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} patterns with environment variable values."""
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.environ.get(var_name, "")
        if not env_value:
            logger.warning("Environment variable %s is not set", var_name)
        return env_value
    return _ENV_VAR_PATTERN.sub(_replace, value)


def _walk_and_substitute(obj):
    """Recursively walk a data structure and substitute env vars in strings."""
    if isinstance(obj, str):
        return _substitute_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _walk_and_substitute(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_and_substitute(item) for item in obj]
    return obj


class CrewAgentEntry(BaseModel):
    """Configuration for a single agent in the crew."""

    chatbot_id: str = Field(..., description="ID used to retrieve agent from BotManager")
    bot_token: str = Field(..., description="Telegram Bot API token")
    username: str = Field(..., description="Telegram bot username (without @)")
    skills: List[dict] = Field(default_factory=list, description="Agent skill descriptors")
    tags: List[str] = Field(default_factory=list, description="Classification tags")
    accepts_files: List[str] = Field(
        default_factory=list, description="File types the agent can receive"
    )
    emits_files: List[str] = Field(
        default_factory=list, description="File types the agent can produce"
    )
    system_prompt_override: Optional[str] = Field(
        default=None, description="Override the agent's default system prompt"
    )


class TelegramCrewConfig(BaseModel):
    """Root configuration for a multi-agent crew in a Telegram supergroup."""

    group_id: int = Field(..., description="Telegram supergroup chat ID")
    coordinator_token: str = Field(..., description="Bot token for the coordinator bot")
    coordinator_username: str = Field(
        ..., description="Telegram username of the coordinator bot"
    )
    hitl_user_ids: List[int] = Field(
        default_factory=list,
        description="Telegram user IDs of human operators",
    )
    agents: Dict[str, CrewAgentEntry] = Field(
        default_factory=dict,
        description="Map of agent name to agent configuration",
    )
    announce_on_join: bool = Field(
        default=True, description="Announce when an agent joins the crew"
    )
    update_pinned_registry: bool = Field(
        default=True, description="Maintain a pinned registry message"
    )
    reply_to_sender: bool = Field(
        default=True, description="Always @mention the sender in replies"
    )
    silent_tool_calls: bool = Field(
        default=True, description="Suppress tool call messages in the group"
    )
    typing_indicator: bool = Field(
        default=True, description="Show typing indicator while processing"
    )
    max_message_length: int = Field(
        default=4000, description="Max chars per message before chunking"
    )
    temp_dir: str = Field(
        default="/tmp/parrot_crew", description="Temp directory for file exchange"
    )
    max_file_size_mb: int = Field(
        default=50, description="Max file size in MB for document exchange"
    )
    allowed_mime_types: List[str] = Field(
        default=[
            "text/csv",
            "application/json",
            "text/plain",
            "image/png",
            "image/jpeg",
            "application/pdf",
            "application/vnd.apache.parquet",
        ],
        description="Allowed MIME types for document exchange",
    )

    @field_validator("max_message_length")
    @classmethod
    def cap_message_length(cls, v: int) -> int:
        """Telegram messages are capped at 4096 characters."""
        if v > 4096:
            logger.warning(
                "max_message_length %d exceeds Telegram limit, capping to 4096", v
            )
            return 4096
        if v < 1:
            raise ValueError("max_message_length must be positive")
        return v

    @classmethod
    def from_yaml(cls, path: str) -> "TelegramCrewConfig":
        """Load configuration from a YAML file with ${ENV_VAR} substitution.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            A validated TelegramCrewConfig instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
            yaml.YAMLError: If the YAML is malformed.
            ValidationError: If the data fails Pydantic validation.
        """
        logger.info("Loading crew config from %s", path)
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if raw is None:
            raise ValueError(f"Empty YAML file: {path}")
        data = _walk_and_substitute(raw)
        return cls(**data)
