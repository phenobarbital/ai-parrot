"""Data models for Slack bot configuration."""
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from navconfig import config


@dataclass
class SlackAgentConfig:
    """Configuration for a single agent exposed via Slack."""

    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    signing_secret: Optional[str] = None
    kind: str = "slack"
    welcome_message: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    allowed_channel_ids: Optional[list[str]] = None
    webhook_path: Optional[str] = None

    def __post_init__(self):
        if not self.bot_token:
            self.bot_token = config.get(f"{self.name.upper()}_SLACK_BOT_TOKEN")
        if not self.signing_secret:
            self.signing_secret = config.get(f"{self.name.upper()}_SLACK_SIGNING_SECRET")

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'SlackAgentConfig':
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            bot_token=data.get("bot_token"),
            signing_secret=data.get("signing_secret"),
            welcome_message=data.get("welcome_message"),
            commands=data.get("commands", {}),
            allowed_channel_ids=data.get("allowed_channel_ids"),
            webhook_path=data.get("webhook_path"),
        )
