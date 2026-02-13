"""
Telegram Callback Decorators.

Provides @telegram_callback decorator for agents to register
inline keyboard callback handlers, following the same pattern
as @telegram_command for commands.

Usage on an Agent:

    class JiraSpecialist(Agent):

        @telegram_callback(
            prefix="ticket_select",
            description="Handle ticket selection from daily standup"
        )
        async def on_ticket_selected(self, callback: CallbackContext) -> CallbackResult:
            ticket_key = callback.payload["ticket_key"]
            await self.transition_ticket(ticket_key, "In Progress")
            return CallbackResult(
                answer_text=f"✅ {ticket_key} → In Progress",
                edit_message=f"✅ Ticket *{ticket_key}* marcado como *In Progress*. ¡A trabajar! 💪"
            )
"""
from __future__ import annotations
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
)
import json
from dataclasses import dataclass

if TYPE_CHECKING:
    from aiogram.types import CallbackQuery


# ──────────────────────────────────────────────────────────────
# Data classes passed to callback handlers
# ──────────────────────────────────────────────────────────────

@dataclass
class CallbackContext:
    """
    Context object passed to @telegram_callback handlers.

    Attributes:
        prefix: The callback prefix that matched.
        payload: Decoded payload dict from callback_data.
        chat_id: Telegram chat ID.
        user_id: Telegram user ID who clicked the button.
        message_id: Message ID of the message containing the button.
        username: Telegram username (if available).
        raw_query: The original aiogram CallbackQuery object.
    """
    prefix: str
    payload: Dict[str, Any]
    chat_id: int
    user_id: int
    message_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    raw_query: Optional['CallbackQuery'] = None

    @property
    def display_name(self) -> str:
        """Best available display name for the user."""
        if self.first_name:
            return self.first_name
        if self.username:
            return f"@{self.username}"
        return str(self.user_id)


@dataclass
class CallbackResult:
    """
    Result returned by a @telegram_callback handler.

    All fields are optional — the wrapper will apply whichever are set.

    Attributes:
        answer_text: Toast notification shown to the user (up to 200 chars).
        show_alert: If True, answer_text is shown as a modal alert instead of toast.
        edit_message: Replace the original message text with this.
        edit_parse_mode: Parse mode for edit_message (default: Markdown).
        reply_text: Send a new message as reply to the callback message.
        reply_parse_mode: Parse mode for reply_text.
        reply_markup: New InlineKeyboardMarkup to replace the current one.
                      Set to None (default) to keep existing, or pass an empty
                      dict/markup to remove buttons.
        remove_keyboard: If True, removes inline keyboard from original message.
    """
    answer_text: Optional[str] = None
    show_alert: bool = False
    edit_message: Optional[str] = None
    edit_parse_mode: str = "Markdown"
    reply_text: Optional[str] = None
    reply_parse_mode: str = "Markdown"
    reply_markup: Optional[Any] = None  # InlineKeyboardMarkup or None
    remove_keyboard: bool = False


# ──────────────────────────────────────────────────────────────
# Callback Data Encoding/Decoding
# ──────────────────────────────────────────────────────────────

class CallbackData:
    """
    Encode/decode callback_data for Telegram InlineKeyboardButtons.

    Format: ``prefix:json_payload``

    Telegram limits callback_data to **64 bytes**, so payloads must be compact.
    Use short keys and values.

    Usage:
        # Encoding
        data = CallbackData.encode("tsel", {"t": "NAV-123", "d": "dev1"})
        # -> 'tsel:{"t":"NAV-123","d":"dev1"}'

        # Decoding
        prefix, payload = CallbackData.decode(data)
        # -> ("tsel", {"t": "NAV-123", "d": "dev1"})
    """

    SEPARATOR = ":"
    MAX_BYTES = 64

    @classmethod
    def encode(cls, prefix: str, payload: Dict[str, Any]) -> str:
        """
        Encode a prefix + payload into callback_data string.

        Raises ValueError if result exceeds 64 bytes.
        """
        json_str = json.dumps(payload, separators=(",", ":"))
        result = f"{prefix}{cls.SEPARATOR}{json_str}"
        if len(result.encode("utf-8")) > cls.MAX_BYTES:
            raise ValueError(
                f"callback_data exceeds {cls.MAX_BYTES} bytes: "
                f"{len(result.encode('utf-8'))} bytes. "
                f"Use shorter prefix/keys or store data externally."
            )
        return result

    @classmethod
    def decode(cls, data: str) -> tuple[str, Dict[str, Any]]:
        """
        Decode callback_data into (prefix, payload).

        Returns:
            Tuple of (prefix_string, payload_dict).
            If there's no payload, returns (prefix, {}).
        """
        if cls.SEPARATOR not in data:
            return data, {}
        prefix, json_str = data.split(cls.SEPARATOR, maxsplit=1)
        try:
            payload = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            payload = {"raw": json_str}
        return prefix, payload


# ──────────────────────────────────────────────────────────────
# Callback Metadata (stored on decorated methods)
# ──────────────────────────────────────────────────────────────

@dataclass
class CallbackMetadata:
    """Metadata stored on a method decorated with @telegram_callback."""
    prefix: str
    description: str
    method: Callable[..., Awaitable[CallbackResult]]
    method_name: str


# ──────────────────────────────────────────────────────────────
# The @telegram_callback decorator
# ──────────────────────────────────────────────────────────────

def telegram_callback(
    prefix: str,
    description: str = "",
):
    """
    Decorator to register an agent method as a Telegram inline callback handler.

    The method will be called when a user clicks an InlineKeyboardButton
    whose ``callback_data`` starts with the given prefix.

    Args:
        prefix: Unique prefix string that identifies this callback.
                Must be short (recommended ≤8 chars) to leave room for payload
                within Telegram's 64-byte callback_data limit.
        description: Human-readable description of what this callback does.

    The decorated method must have signature:
        async def handler(self, callback: CallbackContext) -> CallbackResult

    Usage:
        @telegram_callback(prefix="tsel", description="Select ticket for today")
        async def on_ticket_selected(self, callback: CallbackContext) -> CallbackResult:
            ticket_key = callback.payload["t"]
            # ... do work ...
            return CallbackResult(
                answer_text="✅ Done",
                edit_message=f"Selected: {ticket_key}"
            )
    """
    def decorator(func: Callable) -> Callable:
        # Store metadata on the function for later discovery
        func._telegram_callback = CallbackMetadata(
            prefix=prefix,
            description=description or func.__doc__ or f"Callback: {prefix}",
            method=func,
            method_name=func.__name__,
        )
        func._is_telegram_callback = True
        return func
    return decorator


# ──────────────────────────────────────────────────────────────
# CallbackRegistry: collects callbacks from an agent instance
# ──────────────────────────────────────────────────────────────

class CallbackRegistry:
    """
    Discovers and stores @telegram_callback handlers from an agent.

    Used by TelegramAgentWrapper to route incoming CallbackQuery
    updates to the correct agent method.
    """

    def __init__(self):
        self._handlers: Dict[str, CallbackMetadata] = {}

    def discover_from_agent(self, agent: Any) -> int:
        """
        Scan an agent instance for methods decorated with @telegram_callback.

        Returns:
            Number of callbacks discovered.
        """
        count = 0
        for attr_name in dir(agent):
            if attr_name.startswith("__"):
                continue
            try:
                attr = getattr(agent, attr_name, None)
            except Exception:
                continue
            if callable(attr) and getattr(attr, "_is_telegram_callback", False):
                meta: CallbackMetadata = attr._telegram_callback
                # Bind the method to the agent instance
                bound_meta = CallbackMetadata(
                    prefix=meta.prefix,
                    description=meta.description,
                    method=attr,  # already bound since we got it from instance
                    method_name=meta.method_name,
                )
                self._handlers[meta.prefix] = bound_meta
                count += 1
        return count

    def register(self, prefix: str, handler: Callable, description: str = "") -> None:
        """Programmatically register a callback handler."""
        self._handlers[prefix] = CallbackMetadata(
            prefix=prefix,
            description=description,
            method=handler,
            method_name=getattr(handler, "__name__", prefix),
        )

    def get_handler(self, prefix: str) -> Optional[CallbackMetadata]:
        """Get handler metadata by prefix."""
        return self._handlers.get(prefix)

    def match(self, callback_data: str) -> Optional[tuple[CallbackMetadata, Dict[str, Any]]]:
        """
        Match callback_data against registered prefixes.

        Returns:
            Tuple of (CallbackMetadata, payload_dict) or None.
        """
        prefix, payload = CallbackData.decode(callback_data)
        handler = self._handlers.get(prefix)
        if handler:
            return handler, payload
        return None

    @property
    def prefixes(self) -> List[str]:
        """List all registered prefixes."""
        return list(self._handlers.keys())

    @property
    def handlers(self) -> Dict[str, CallbackMetadata]:
        """All registered handlers."""
        return dict(self._handlers)

    def __len__(self) -> int:
        return len(self._handlers)

    def __bool__(self) -> bool:
        return bool(self._handlers)


# ──────────────────────────────────────────────────────────────
# InlineKeyboard builder helper
# ──────────────────────────────────────────────────────────────

def build_inline_keyboard(
    buttons: List[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """
    Build an InlineKeyboardMarkup dict compatible with aiogram.

    Each button dict should have:
        - text: str — Button label
        - callback_data: str — Already-encoded callback data

    Or use the helper:
        - text: str
        - prefix: str + payload: dict → auto-encodes callback_data

    Args:
        buttons: 2D list of button dicts (rows × columns).

    Returns:
        InlineKeyboardMarkup-compatible dict.

    Usage:
        keyboard = build_inline_keyboard([
            [{"text": "▶️ NAV-123", "prefix": "tsel", "payload": {"t": "NAV-123"}}],
            [{"text": "⏭️ Skip", "prefix": "tskip", "payload": {}}],
        ])
    """
    rows = []
    for row in buttons:
        built_row = []
        for btn in row:
            if "callback_data" in btn:
                built_row.append({
                    "text": btn["text"],
                    "callback_data": btn["callback_data"],
                })
            elif "prefix" in btn:
                built_row.append({
                    "text": btn["text"],
                    "callback_data": CallbackData.encode(
                        btn["prefix"],
                        btn.get("payload", {})
                    ),
                })
            elif "url" in btn:
                built_row.append({
                    "text": btn["text"],
                    "url": btn["url"],
                })
            else:
                built_row.append(btn)
        rows.append(built_row)
    return {"inline_keyboard": rows}
