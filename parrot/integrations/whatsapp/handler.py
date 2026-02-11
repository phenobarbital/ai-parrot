"""
WhatsApp user session tracking.

Manages per-user conversation state and 24-hour messaging window tracking.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...memory import ConversationMemory


@dataclass
class WhatsAppUserSession:
    """
    Per-user session tracking for WhatsApp conversations.

    Tracks conversation memory, message timestamps (for 24h window),
    and per-user metadata.

    Attributes:
        phone_number: The user's WhatsApp phone number (wa_id).
        conversation_memory: InMemoryConversation instance for this user.
        last_message_time: Timestamp of the user's last incoming message (UTC).
        message_count: Total messages received from this user.
        metadata: Arbitrary per-user metadata.
    """
    phone_number: str
    conversation_memory: Optional['ConversationMemory'] = None
    last_message_time: Optional[datetime] = None
    message_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_within_24h_window(self) -> bool:
        """
        Check if the user's last message is within the 24-hour messaging window.

        WhatsApp restricts free-form messages to 24 hours after the user's
        last message. Outside this window, only template messages can be sent.
        """
        if not self.last_message_time:
            return False
        now = datetime.now(timezone.utc)
        last = self.last_message_time
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last).total_seconds() < 86400

    def touch(self) -> None:
        """Update last message time and increment counter."""
        self.last_message_time = datetime.now(timezone.utc)
        self.message_count += 1
