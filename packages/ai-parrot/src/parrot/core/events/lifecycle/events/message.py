"""Message lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: messages entering the agent's conversation history.
"""
from dataclasses import dataclass
from navigator_eventbus.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class MessageAddedEvent(LifecycleEvent):
    """Emitted when a message is added to the conversation history.

    Emitted from the canonical history-insertion point in AbstractBot
    (save_conversation_turn / add_turn) so every code path is covered
    by a single emission site.

    Attributes:
        agent_name: Name of the agent whose history is updated.
        role: Message role (``"user"``, ``"assistant"``, ``"tool"``,
            ``"system"``).
        content_length: Character length of the message content.
        has_tool_calls: True if the message contains tool call blocks.
    """

    agent_name: str = ""
    role: str = ""                    # "user" | "assistant" | "tool" | "system"
    content_length: int = 0
    has_tool_calls: bool = False
