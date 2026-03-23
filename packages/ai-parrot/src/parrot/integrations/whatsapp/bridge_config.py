"""Configuration for WhatsApp Bridge integration."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from navconfig import config


@dataclass
class WhatsAppBridgeConfig:
    """Configuration for WhatsApp Bridge wrapper (whatsmeow-based).

    Attributes:
        name: Wrapper name (used for logging and route generation).
        chatbot_id: Agent name in BotManager / agent registry.
        bridge_url: URL of the Go whatsmeow bridge.
        webhook_path: Path to register for incoming message callbacks.
        welcome_message: Greeting sent on first interaction.
        system_prompt_override: Override agent's default system prompt.
        allowed_numbers: Phone allowlist (digits only, no +). Empty = all.
        commands: Custom slash-command map.
        max_message_length: Max chars before splitting.
    """

    name: str
    chatbot_id: str
    bridge_url: str = "http://localhost:8765"
    webhook_path: Optional[str] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    allowed_numbers: Optional[List[str]] = None
    max_message_length: int = 4096

    def __post_init__(self):
        """Resolve bridge_url from environment if not set."""
        if not self.bridge_url:
            self.bridge_url = config.get(
                "WHATSAPP_BRIDGE_URL", "http://localhost:8765"
            )

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "WhatsAppBridgeConfig":
        """Create config from dictionary (YAML parsed data)."""
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            bridge_url=data.get("bridge_url", "http://localhost:8765"),
            webhook_path=data.get("webhook_path"),
            welcome_message=data.get("welcome_message"),
            system_prompt_override=data.get("system_prompt_override"),
            commands=data.get("commands", {}),
            allowed_numbers=data.get("allowed_numbers"),
            max_message_length=data.get("max_message_length", 4096),
        )
