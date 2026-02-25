"""Data models for Slack bot configuration."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from navconfig import config


@dataclass
class SlackAgentConfig:
    """Configuration for a single agent exposed via Slack.

    Attributes:
        name: Unique identifier for this bot configuration.
        chatbot_id: ID of the AI-Parrot chatbot to use.
        bot_token: Slack bot token (xoxb-...). Falls back to {NAME}_SLACK_BOT_TOKEN env var.
        signing_secret: Slack signing secret for request verification.
            Falls back to {NAME}_SLACK_SIGNING_SECRET env var.
        kind: Integration type, always "slack".
        welcome_message: Message sent when a user starts a conversation.
        commands: Mapping of slash command names to descriptions.
        allowed_channel_ids: If set, only respond in these channels.
        webhook_path: Custom webhook path (default: /api/slack/{chatbot_id}/events).
        app_token: Slack app-level token (xapp-...) for Socket Mode.
            Falls back to {NAME}_SLACK_APP_TOKEN env var.
        connection_mode: Connection method - "webhook" (HTTP) or "socket" (WebSocket).
        enable_assistant: Enable Slack Agents & AI Apps feature.
        suggested_prompts: Suggested prompts shown in assistant container.
            Each dict should have "title" and "message" keys.
        max_concurrent_requests: Maximum concurrent agent requests (default: 10).
    """

    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    signing_secret: Optional[str] = None
    kind: str = "slack"
    welcome_message: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    allowed_channel_ids: Optional[List[str]] = None
    webhook_path: Optional[str] = None

    # New fields for enhanced Slack integration
    app_token: Optional[str] = None
    connection_mode: str = "webhook"
    enable_assistant: bool = False
    suggested_prompts: Optional[List[Dict[str, str]]] = None
    max_concurrent_requests: int = 10

    def __post_init__(self):
        """Initialize config with environment variable fallbacks and validation."""
        # Load tokens from environment if not provided
        if not self.bot_token:
            self.bot_token = config.get(f"{self.name.upper()}_SLACK_BOT_TOKEN")
        if not self.signing_secret:
            self.signing_secret = config.get(f"{self.name.upper()}_SLACK_SIGNING_SECRET")
        if not self.app_token:
            self.app_token = config.get(f"{self.name.upper()}_SLACK_APP_TOKEN")

        # Validate Socket Mode requirements
        if self.connection_mode == "socket" and not self.app_token:
            raise ValueError(
                f"Socket Mode requires app-level token (xapp-...) for '{self.name}'."
            )

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'SlackAgentConfig':
        """Create a SlackAgentConfig from a dictionary.

        Args:
            name: Unique identifier for this bot configuration.
            data: Dictionary containing configuration values.

        Returns:
            SlackAgentConfig instance.
        """
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            bot_token=data.get("bot_token"),
            signing_secret=data.get("signing_secret"),
            welcome_message=data.get("welcome_message"),
            commands=data.get("commands", {}),
            allowed_channel_ids=data.get("allowed_channel_ids"),
            webhook_path=data.get("webhook_path"),
            # New fields
            app_token=data.get("app_token"),
            connection_mode=data.get("connection_mode", "webhook"),
            enable_assistant=data.get("enable_assistant", False),
            suggested_prompts=data.get("suggested_prompts"),
            max_concurrent_requests=data.get("max_concurrent_requests", 10),
        )
