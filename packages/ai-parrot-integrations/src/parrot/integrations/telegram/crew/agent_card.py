"""AgentCard and AgentSkill models for TelegramCrewTransport.

These Pydantic models describe an agent's identity, capabilities,
and status within a crew. They provide rendering methods for
Telegram-formatted announcements and pinned registry lines.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_STATUS_EMOJI = {
    "ready": "\u2705",      # checkmark
    "busy": "\u23f3",       # hourglass
    "offline": "\U0001f534",  # red circle
}

_VALID_STATUSES = frozenset(_STATUS_EMOJI.keys())


class AgentSkill(BaseModel):
    """Describes a single capability of an agent."""

    name: str = Field(..., description="Short skill name")
    description: str = Field(..., description="Human-readable skill description")
    input_types: List[str] = Field(
        default_factory=list, description="Accepted input types (e.g. text, csv, json)"
    )
    output_types: List[str] = Field(
        default_factory=list, description="Produced output types (e.g. text, chart)"
    )
    example: Optional[str] = Field(
        default=None, description="Example usage prompt"
    )


class AgentCard(BaseModel):
    """Identity and capability descriptor for an agent in the crew."""

    agent_id: str = Field(..., description="Internal agent identifier")
    agent_name: str = Field(..., description="Human-readable agent name")
    telegram_username: str = Field(..., description="Telegram bot username (without @)")
    telegram_user_id: int = Field(..., description="Telegram bot user ID")
    model: str = Field(..., description="LLM model identifier")
    skills: List[AgentSkill] = Field(
        default_factory=list, description="Agent capabilities"
    )
    tags: List[str] = Field(default_factory=list, description="Classification tags")
    accepts_files: List[str] = Field(
        default_factory=list, description="File types the agent can receive"
    )
    emits_files: List[str] = Field(
        default_factory=list, description="File types the agent can produce"
    )
    status: str = Field(default="ready", description="Current status: ready, busy, offline")
    current_task: Optional[str] = Field(
        default=None, description="Description of current task (when busy)"
    )
    joined_at: datetime = Field(
        ..., description="Timestamp when agent joined the crew"
    )
    last_seen: datetime = Field(
        ..., description="Timestamp of last activity"
    )

    def to_telegram_text(self) -> str:
        """Render a formatted announcement message for the Telegram group.

        Returns:
            Multi-line string with agent name, username, model, skills,
            and file type information.
        """
        lines = [
            f"Agent joined: {self.agent_name}",
            f"Username: @{self.telegram_username}",
            f"Model: {self.model}",
        ]
        if self.skills:
            lines.append("Skills:")
            for skill in self.skills:
                lines.append(f"  - {skill.name}: {skill.description}")
        if self.tags:
            lines.append(f"Tags: {', '.join(self.tags)}")
        if self.accepts_files:
            lines.append(f"Accepts: {', '.join(self.accepts_files)}")
        if self.emits_files:
            lines.append(f"Emits: {', '.join(self.emits_files)}")
        return "\n".join(lines)

    def to_registry_line(self) -> str:
        """Render a compact one-line status for the pinned registry message.

        Format: {emoji} @{username}  {agent_name} · {current_task}

        Returns:
            Single-line string with status emoji, username, name,
            and optional task description.
        """
        emoji = _STATUS_EMOJI.get(self.status, _STATUS_EMOJI["offline"])
        line = f"{emoji} @{self.telegram_username}  {self.agent_name}"
        if self.current_task:
            line += f" \u00b7 {self.current_task}"
        return line
