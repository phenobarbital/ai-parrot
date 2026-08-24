"""Configuration for WhatsApp Bridge integration."""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from navconfig import config

#: Strips anything that isn't a digit (``+``, spaces, dashes, parens, ...).
#: Used to normalize both the configured allowlist and an incoming phone
#: number before comparing them (FEAT-453 TASK-2397) — a literal string
#: compare against ``allowed_numbers`` silently fails to authorize a number
#: formatted with a leading ``+`` or internal spaces.
_DIGITS_ONLY = re.compile(r"\D+")


def normalize_phone_number(number: str) -> str:
    """Normalize *number* to digits-only (no ``+``, spaces, dashes, ...)."""
    return _DIGITS_ONLY.sub("", number)


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
            For an agent that exposes any financial-write (``SUBMIT``)
            operation, an empty allowlist is a fail-closed condition — see
            :class:`~parrot.integrations.whatsapp.bridge_wrapper.WhatsAppBridgeWrapper`.
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
            self.bridge_url = config.get("WHATSAPP_BRIDGE_URL", "http://localhost:8765")

    @property
    def normalized_allowed_numbers(self) -> Optional[List[str]]:
        """``allowed_numbers`` normalized to digits-only for comparison.

        Returns ``None``/empty exactly when ``allowed_numbers`` is
        ``None``/empty (i.e. "allow all" is preserved), never an empty-vs-
        populated distinction introduced by normalization itself.
        """
        if not self.allowed_numbers:
            return self.allowed_numbers
        return [normalize_phone_number(n) for n in self.allowed_numbers]

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
