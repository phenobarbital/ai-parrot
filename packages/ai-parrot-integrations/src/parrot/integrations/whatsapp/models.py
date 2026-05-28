"""
Data models for WhatsApp bot configuration.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from navconfig import config


@dataclass
class WhatsAppAgentConfig:
    """
    Configuration for a single agent exposed via WhatsApp Business API.

    Attributes:
        name: Agent name (used as key in YAML and for env var fallback).
        chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
        phone_id: WhatsApp Phone Number ID from Meta (not the phone number itself).
        token: Permanent access token from Meta System User.
        verify_token: Webhook verification token (you define this).
        app_id: Meta App ID.
        app_secret: Meta App Secret (used for webhook signature validation).
        kind: Integration type (whatsapp).
        webhook_path: Optional custom webhook path override.
        welcome_message: Custom welcome message for new conversations.
        system_prompt_override: Override the agent's default system prompt.
        enable_group_mentions: Respond in groups only when mentioned.
        allowed_numbers: Optional phone number allowlist (without + prefix).
        commands: Custom commands map.
        max_message_length: Maximum message length before splitting (default 4096).
    """
    name: str
    chatbot_id: str
    phone_id: Optional[str] = None
    token: Optional[str] = None
    verify_token: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    kind: str = "whatsapp"
    webhook_path: Optional[str] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    enable_group_mentions: bool = True
    allowed_numbers: Optional[List[str]] = None
    max_message_length: int = 4096

    def __post_init__(self):
        """
        Resolve credentials from environment variables if not provided in YAML.

        Falls back to {AGENT_NAME}_WHATSAPP_{FIELD} environment variables.
        For example, MyBot would look for MYBOT_WHATSAPP_TOKEN.
        """
        prefix = self.name.upper()
        if not self.phone_id:
            self.phone_id = config.get(f"{prefix}_WHATSAPP_PHONE_ID")
        if not self.token:
            self.token = config.get(f"{prefix}_WHATSAPP_TOKEN")
        if not self.verify_token:
            self.verify_token = config.get(f"{prefix}_WHATSAPP_VERIFY_TOKEN")
        if not self.app_id:
            self.app_id = config.get(f"{prefix}_WHATSAPP_APP_ID")
        if not self.app_secret:
            self.app_secret = config.get(f"{prefix}_WHATSAPP_APP_SECRET")

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'WhatsAppAgentConfig':
        """Create config from dictionary (YAML parsed data)."""
        return cls(
            name=name,
            chatbot_id=data.get('chatbot_id', name),
            phone_id=data.get('phone_id'),
            token=data.get('token'),
            verify_token=data.get('verify_token'),
            app_id=str(data['app_id']) if 'app_id' in data else None,
            app_secret=data.get('app_secret'),
            webhook_path=data.get('webhook_path'),
            welcome_message=data.get('welcome_message'),
            system_prompt_override=data.get('system_prompt_override'),
            commands=data.get('commands', {}),
            enable_group_mentions=data.get('enable_group_mentions', True),
            allowed_numbers=data.get('allowed_numbers'),
            max_message_length=data.get('max_message_length', 4096),
        )
