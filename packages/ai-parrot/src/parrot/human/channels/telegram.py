"""
Telegram Human Channel for AI-Parrot HITL.

Uses aiogram v3 to send interactive messages (inline keyboards, polls)
to humans via Telegram private chat, and captures responses through
callback queries.

Security:
- All interactions are point-to-point (private chat only).
- Callback buttons use secure tokens (not raw interaction IDs).
- Tokens are single-use and bound to a specific human + interaction.
- Respondent identity is verified against the interaction's target_humans.

This channel is designed to work alongside the existing Telegram
integration (TelegramBotManager / TelegramAgentWrapper). It can
share the same aiogram Bot instance or use a dedicated one for HITL.

Usage:
    from aiogram import Bot
    bot = Bot(token="YOUR_BOT_TOKEN")
    channel = TelegramHumanChannel(bot=bot, redis=redis_client)
    await channel.register_response_handler(manager.receive_response)
"""
import json
import secrets
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from navconfig.logging import logging

from .base import HumanChannel
from ..models import (
    HumanInteraction,
    HumanResponse,
    InteractionType,
    ChoiceOption,
)

try:
    from aiogram import Bot, Router, F
    from aiogram.filters import Command
    from aiogram.types import (
        CallbackQuery,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
        Message,
    )

    HAS_AIOGRAM = True
except ImportError:
    HAS_AIOGRAM = False


class TelegramHumanChannel(HumanChannel):
    """Telegram channel for Human-in-the-Loop interactions.

    Translates HumanInteraction objects into Telegram-native UI:
    - Approval → Two inline buttons (✅ Approve / ❌ Reject)
    - Single choice → Inline keyboard with one button per option
    - Multi choice → Toggle buttons + Done button
    - Free text → Text prompt, human replies with a message
    - Poll → Telegram native poll (for consensus/voting)
    - Form → Sequential text prompts (simplified in Telegram)

    All callbacks use secure, single-use tokens stored in Redis
    to prevent unauthorized responses and replay attacks.

    Args:
        bot: aiogram Bot instance (can be shared with TelegramBotManager).
        redis: Async Redis client.
        token_ttl: TTL for callback tokens in seconds (default: 24h).
        parse_mode: Telegram message parse mode.
    """

    channel_type = "telegram"

    def __init__(
        self,
        bot: Any,  # aiogram.Bot — typed as Any for import safety
        redis: Any,
        token_ttl: int = 86400,
        parse_mode: str = "Markdown",
    ) -> None:
        if not HAS_AIOGRAM:
            raise ImportError(
                "aiogram v3 is required for TelegramHumanChannel. "
                "Install it with: pip install aiogram"
            )

        self.bot: Bot = bot
        self.redis = redis
        self.token_ttl = token_ttl
        self.parse_mode = parse_mode
        self.logger = logging.getLogger("HITL.Telegram")

        # Router for handling callback queries
        self.router = Router(name="hitl_telegram")

        # Response + cancel callbacks registered by the manager
        self._response_callback: Optional[Callable] = None
        self._cancel_callback: Optional[Callable] = None

        # Track multi-choice selections in progress: {token: set(keys)}
        self._multi_selections: Dict[str, Set[str]] = {}

        # Track free-text interactions waiting for a reply: {chat_id: interaction_id}
        self._awaiting_text: Dict[int, str] = {}

        # Track every pending interaction per chat (all types) so /cancel can
        # abort them. Callback interactions live in Redis tokens; this is the
        # in-memory index to reverse-lookup them by chat.
        self._pending_by_chat: Dict[int, Set[str]] = {}

        # Register handlers
        self._register_handlers()

    def _track_pending(self, chat_id: int, interaction_id: str) -> None:
        self._pending_by_chat.setdefault(chat_id, set()).add(interaction_id)

    def _untrack_pending(self, chat_id: int, interaction_id: str) -> None:
        bucket = self._pending_by_chat.get(chat_id)
        if not bucket:
            return
        bucket.discard(interaction_id)
        if not bucket:
            self._pending_by_chat.pop(chat_id, None)

    def _register_handlers(self) -> None:
        """Register aiogram callback and message handlers."""
        # Inline button callbacks (approval, single_choice, multi_choice, cancel)
        self.router.callback_query.register(
            self._handle_callback, F.data.startswith("hitl:")
        )

        # /cancel command — must be registered BEFORE the free-text handler
        # so it wins when the user types /cancel while we're awaiting text.
        # Filtered to chats that actually have pending interactions so it
        # falls through to the wrapper otherwise (which may not have its own
        # /cancel and will reply with a generic help message).
        self.router.message.register(
            self._handle_cancel_command,
            F.chat.type == "private",
            Command("cancel"),
            self._has_pending_filter,
        )

        # Free-text replies — only claim the update when we are actually
        # awaiting a text answer for this chat. Otherwise the filter fails
        # and aiogram falls through to the next router (e.g. the regular
        # TelegramAgentWrapper), which prevents user replies from being
        # fed back into the agent loop as fresh prompts.
        self.router.message.register(
            self._handle_text_reply,
            F.chat.type == "private",
            F.text,
            self._awaiting_text_filter,
        )

    def _awaiting_text_filter(self, message: "Message") -> bool:
        """Filter: only handle the message when we're awaiting a reply here."""
        return message.chat.id in self._awaiting_text

    def _has_pending_filter(self, message: "Message") -> bool:
        """Filter: only handle /cancel when there is something to cancel."""
        return bool(self._pending_by_chat.get(message.chat.id))

    # ─── HumanChannel interface ──────────────────────────────────────────

    async def register_response_handler(
        self,
        callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None:
        """Register the manager's response callback."""
        self._response_callback = callback

    async def register_cancel_handler(
        self,
        callback: Callable[[str], Awaitable[bool]],
    ) -> None:
        """Register the manager's cancel callback (cancel_pending)."""
        self._cancel_callback = callback

    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        """Send an interaction to a human via Telegram private chat."""
        chat_id = int(recipient)

        try:
            handler = {
                InteractionType.APPROVAL: self._send_approval,
                InteractionType.SINGLE_CHOICE: self._send_single_choice,
                InteractionType.MULTI_CHOICE: self._send_multi_choice,
                InteractionType.FREE_TEXT: self._send_free_text,
                InteractionType.POLL: self._send_poll,
                InteractionType.FORM: self._send_form,
            }.get(interaction.interaction_type)

            if not handler:
                self.logger.error(
                    "Unsupported interaction type: %s",
                    interaction.interaction_type,
                )
                return False

            await handler(interaction, chat_id)

            # Store interaction metadata in Redis for response handling
            await self._store_interaction_meta(interaction, recipient)

            self.logger.info(
                "Sent %s interaction %s... to chat %s",
                interaction.interaction_type.value,
                interaction.interaction_id[:8],
                chat_id,
            )
            return True

        except Exception:
            self.logger.exception(
                "Failed to send interaction to %s", chat_id
            )
            return False

    async def send_notification(self, recipient: str, message: str) -> None:
        """Send a simple text notification."""
        try:
            await self.bot.send_message(
                chat_id=int(recipient),
                text=message,
                parse_mode=self.parse_mode,
            )
        except Exception:
            self.logger.exception(
                "Failed to send notification to %s", recipient
            )

    async def cancel_interaction(
        self, interaction_id: str, recipient: str
    ) -> None:
        """Cancel/withdraw an interaction by removing its keyboard."""
        try:
            msg_key = f"hitl:msg:{interaction_id}:{recipient}"
            msg_id_raw = await self.redis.get(msg_key)
            if msg_id_raw:
                msg_id = int(msg_id_raw)
                try:
                    await self.bot.edit_message_reply_markup(
                        chat_id=int(recipient),
                        message_id=msg_id,
                        reply_markup=None,
                    )
                    await self.bot.edit_message_text(
                        chat_id=int(recipient),
                        message_id=msg_id,
                        text="⚠️ _This interaction has been cancelled._",
                        parse_mode=self.parse_mode,
                    )
                except Exception:
                    pass
                await self.redis.delete(msg_key)
        except Exception:
            self.logger.exception("Failed to cancel interaction")

        # Clean up awaiting text if applicable
        chat_id = int(recipient)
        if self._awaiting_text.get(chat_id) == interaction_id:
            del self._awaiting_text[chat_id]

    # ─── Sending Interactions ─────────────────────────────────────────────

    async def _send_approval(
        self, interaction: HumanInteraction, chat_id: int
    ) -> None:
        """Send approval interaction with Yes/No buttons."""
        token_yes = await self._create_token(
            interaction.interaction_id, str(chat_id), action="yes"
        )
        token_no = await self._create_token(
            interaction.interaction_id, str(chat_id), action="no"
        )
        cancel_row = await self._build_cancel_row(
            interaction.interaction_id, chat_id
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Approve",
                        callback_data=f"hitl:{token_yes}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Reject",
                        callback_data=f"hitl:{token_no}",
                    ),
                ],
                cancel_row,
            ]
        )

        text = self._format_message(interaction)
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=self.parse_mode,
        )
        await self._store_message_id(
            interaction.interaction_id, chat_id, msg.message_id
        )
        self._track_pending(chat_id, interaction.interaction_id)

    async def _build_cancel_row(
        self, interaction_id: str, chat_id: int
    ) -> List["InlineKeyboardButton"]:
        """Build a one-button row with ✕ Cancel for any interactive prompt."""
        token = await self._create_token(
            interaction_id, str(chat_id), action="user_cancel"
        )
        return [
            InlineKeyboardButton(
                text="✕ Cancel",
                callback_data=f"hitl:{token}",
            )
        ]

    async def _send_single_choice(
        self, interaction: HumanInteraction, chat_id: int
    ) -> None:
        """Send single-choice interaction with one button per option."""
        options = interaction.options or []
        buttons = []

        for opt in options:
            token = await self._create_token(
                interaction.interaction_id,
                str(chat_id),
                action=f"pick:{opt.key}",
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"📌 {opt.label}",
                        callback_data=f"hitl:{token}",
                    )
                ]
            )

        buttons.append(
            await self._build_cancel_row(interaction.interaction_id, chat_id)
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        text = self._format_message(interaction)
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=self.parse_mode,
        )
        await self._store_message_id(
            interaction.interaction_id, chat_id, msg.message_id
        )
        self._track_pending(chat_id, interaction.interaction_id)

    async def _send_multi_choice(
        self, interaction: HumanInteraction, chat_id: int
    ) -> None:
        """Send multi-choice interaction with toggle buttons + Done.

        Each option button toggles selection. The Done button submits
        the current selection. Button text updates to show ✅/⬜ state.
        """
        options = interaction.options or []

        # Create a master token for this multi-choice session
        master_token = await self._create_token(
            interaction.interaction_id,
            str(chat_id),
            action="multi_master",
            extra={"options": [o.key for o in options]},
        )

        # Initialize empty selections
        self._multi_selections[master_token] = set()

        # Build initial keyboard (all unchecked)
        keyboard = self._build_multi_keyboard(
            options, master_token, selected=set()
        )

        text = self._format_message(interaction)
        text += "\n\n_Tap to toggle, then press Done_"

        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=self.parse_mode,
        )
        await self._store_message_id(
            interaction.interaction_id, chat_id, msg.message_id
        )
        self._track_pending(chat_id, interaction.interaction_id)

    def _build_multi_keyboard(
        self,
        options: List[ChoiceOption],
        master_token: str,
        selected: Set[str],
    ) -> InlineKeyboardMarkup:
        """Build the inline keyboard for multi-choice with toggle state."""
        buttons = []
        for opt in options:
            prefix = "✅" if opt.key in selected else "⬜"
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{prefix} {opt.label}",
                        callback_data=f"hitl:{master_token}:toggle:{opt.key}",
                    )
                ]
            )

        # Done button
        count = len(selected)
        done_text = f"✅ Done ({count} selected)" if count else "✅ Done"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=done_text,
                    callback_data=f"hitl:{master_token}:done",
                )
            ]
        )

        # Cancel button — same master_token, disambiguated by sub-action
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✕ Cancel",
                    callback_data=f"hitl:{master_token}:user_cancel",
                )
            ]
        )

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    async def _send_free_text(
        self, interaction: HumanInteraction, chat_id: int
    ) -> None:
        """Send free-text interaction.

        Simply sends the question as a message and waits for the human
        to reply with a text message. The next text message from this
        chat is captured as the response.
        """
        text = self._format_message(interaction)
        text += "\n\n_Reply with your answer, or send /cancel to abort._"

        # Attach a small inline keyboard with just a Cancel button so the
        # user doesn't have to switch to typing a command.
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                await self._build_cancel_row(
                    interaction.interaction_id, chat_id
                )
            ]
        )

        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=self.parse_mode,
            reply_markup=keyboard,
        )
        await self._store_message_id(
            interaction.interaction_id, chat_id, msg.message_id
        )

        # Register that we're waiting for a text reply from this chat
        self._awaiting_text[chat_id] = interaction.interaction_id
        self._track_pending(chat_id, interaction.interaction_id)

    async def _send_poll(
        self, interaction: HumanInteraction, chat_id: int
    ) -> None:
        """Send a Telegram native poll.

        Best for consensus/voting scenarios where multiple humans
        vote in a group chat. For private chats, falls back to
        single_choice behavior.
        """
        options = interaction.options or []
        if not options:
            return await self._send_free_text(interaction, chat_id)

        poll_options = [opt.label for opt in options]

        msg = await self.bot.send_poll(
            chat_id=chat_id,
            question=interaction.question[:300],  # Telegram limit
            options=poll_options,
            is_anonymous=False,
        )
        await self._store_message_id(
            interaction.interaction_id, chat_id, msg.message_id
        )
        self._track_pending(chat_id, interaction.interaction_id)

        # Store mapping of poll option index → key
        await self.redis.set(
            f"hitl:poll:{msg.poll.id}",
            json.dumps(
                {
                    "interaction_id": interaction.interaction_id,
                    "options": {
                        str(i): opt.key for i, opt in enumerate(options)
                    },
                }
            ),
            ex=self.token_ttl,
        )

    async def _send_form(
        self, interaction: HumanInteraction, chat_id: int
    ) -> None:
        """Send form interaction.

        Telegram doesn't have native forms, so we present the fields
        as a formatted message and ask the human to reply with values.
        For simple forms, this works well enough. Complex forms should
        use the HTTP channel instead.
        """
        text = self._format_message(interaction)

        if interaction.form_schema and "properties" in interaction.form_schema:
            props = interaction.form_schema["properties"]
            required = interaction.form_schema.get("required", [])

            text += "\n\n*Please provide the following:*\n"
            for field_name, field_def in props.items():
                desc = field_def.get("description", field_name)
                req = " \\*" if field_name in required else ""
                default = field_def.get("default", "")
                default_hint = f" (default: {default})" if default else ""
                text += f"• `{field_name}`: {desc}{req}{default_hint}\n"

            text += "\n_Reply with values as:_\n"
            text += "`field1: value1`\n`field2: value2`"

        text += "\n\n_Send /cancel to abort this form._"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                await self._build_cancel_row(
                    interaction.interaction_id, chat_id
                )
            ]
        )
        msg = await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=self.parse_mode,
            reply_markup=keyboard,
        )
        await self._store_message_id(
            interaction.interaction_id, chat_id, msg.message_id
        )
        self._awaiting_text[chat_id] = interaction.interaction_id
        self._track_pending(chat_id, interaction.interaction_id)

    # ─── Response Handling ────────────────────────────────────────────────

    async def _handle_callback(self, callback_query: CallbackQuery) -> None:
        """Handle inline button presses.

        Callback data format: ``hitl:{token}`` or ``hitl:{token}:{action}:{data}``
        """
        data = callback_query.data
        parts = data.split(":", maxsplit=3)  # hitl:token[:action[:data]]

        if len(parts) < 2:
            return

        token = parts[1]
        sub_action = parts[2] if len(parts) > 2 else None
        sub_data = parts[3] if len(parts) > 3 else None

        telegram_user_id = str(callback_query.from_user.id)

        # ── Multi-choice toggle/done/cancel (master token path) ──
        if sub_action == "toggle" and sub_data:
            await self._handle_multi_toggle(
                callback_query, token, sub_data
            )
            return
        if sub_action == "done":
            await self._handle_multi_done(callback_query, token)
            return
        if sub_action == "user_cancel":
            await self._handle_callback_cancel(
                callback_query, token, telegram_user_id
            )
            return

        # ── Standard token validation (approval, single_choice, cancel) ──
        token_data = await self._validate_token(token, telegram_user_id)
        if not token_data:
            await callback_query.answer(
                "⛔ Not authorized or link expired", show_alert=True
            )
            return

        interaction_id = token_data["interaction_id"]
        action = token_data.get("action", "")

        # Parse the action
        if action == "user_cancel":
            await self._cancel_by_interaction(
                callback_query, interaction_id, token=token
            )
            return
        if action in ("yes", "no"):
            value: Any = action == "yes"
            response_type = InteractionType.APPROVAL
        elif action.startswith("pick:"):
            value = action.split(":", 1)[1]
            response_type = InteractionType.SINGLE_CHOICE
        else:
            await callback_query.answer("Unknown action", show_alert=True)
            return

        response = HumanResponse(
            interaction_id=interaction_id,
            respondent=telegram_user_id,
            response_type=response_type,
            value=value,
            timestamp=datetime.utcnow().isoformat(),
            metadata={
                "channel": "telegram",
                "chat_id": callback_query.message.chat.id,
                "message_id": callback_query.message.message_id,
            },
        )

        # Acknowledge the button press
        if value is True:
            label = "✅ Approved"
        elif value is False:
            label = "❌ Rejected"
        else:
            label = f"Selected: {value}"
        await callback_query.answer(label)

        # Update message to show it's been answered
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
            await callback_query.message.edit_text(
                callback_query.message.text + f"\n\n✅ _Answered: {label}_",
                parse_mode=self.parse_mode,
            )
        except Exception:
            pass  # Message edit can fail if too old

        # Invalidate the token (single-use)
        await self._invalidate_token(token)
        self._untrack_pending(callback_query.message.chat.id, interaction_id)

        # Dispatch to manager
        if self._response_callback:
            await self._response_callback(response)

    async def _handle_multi_toggle(
        self,
        callback_query: CallbackQuery,
        master_token: str,
        option_key: str,
    ) -> None:
        """Toggle an option in a multi-choice interaction."""
        if master_token not in self._multi_selections:
            await callback_query.answer("Session expired", show_alert=True)
            return

        selected = self._multi_selections[master_token]

        if option_key in selected:
            selected.discard(option_key)
            await callback_query.answer("❌ Deselected")
        else:
            selected.add(option_key)
            await callback_query.answer("✅ Selected")

        # Rebuild the keyboard with updated state
        token_data = await self._get_token_data(master_token)
        if not token_data:
            return

        option_keys = token_data.get("extra", {}).get("options", [])
        options = [ChoiceOption(key=k, label=k) for k in option_keys]

        # Reconstruct options with labels from stored interaction
        interaction_meta = await self._get_interaction_meta(
            token_data["interaction_id"]
        )
        if interaction_meta and "options" in interaction_meta:
            stored_options = interaction_meta["options"]
            options = [
                ChoiceOption(key=o["key"], label=o.get("label", o["key"]))
                for o in stored_options
            ]

        keyboard = self._build_multi_keyboard(options, master_token, selected)

        try:
            await callback_query.message.edit_reply_markup(
                reply_markup=keyboard
            )
        except Exception:
            pass

    async def _handle_multi_done(
        self,
        callback_query: CallbackQuery,
        master_token: str,
    ) -> None:
        """Submit multi-choice selection."""
        if master_token not in self._multi_selections:
            await callback_query.answer("Session expired", show_alert=True)
            return

        selected = list(self._multi_selections.pop(master_token))
        telegram_user_id = str(callback_query.from_user.id)

        token_data = await self._get_token_data(master_token)
        if not token_data:
            await callback_query.answer("Token expired", show_alert=True)
            return

        # Verify identity
        if token_data["human_id"] != telegram_user_id:
            await callback_query.answer("⛔ Not authorized", show_alert=True)
            return

        interaction_id = token_data["interaction_id"]

        response = HumanResponse(
            interaction_id=interaction_id,
            respondent=telegram_user_id,
            response_type=InteractionType.MULTI_CHOICE,
            value=selected,
            timestamp=datetime.utcnow().isoformat(),
            metadata={
                "channel": "telegram",
                "chat_id": callback_query.message.chat.id,
            },
        )

        count = len(selected)
        await callback_query.answer(f"✅ Submitted {count} selection(s)")

        try:
            sel_text = ", ".join(selected) if selected else "none"
            await callback_query.message.edit_reply_markup(reply_markup=None)
            await callback_query.message.edit_text(
                callback_query.message.text
                + f"\n\n✅ _Selected: {sel_text}_",
                parse_mode=self.parse_mode,
            )
        except Exception:
            pass

        await self._invalidate_token(master_token)
        self._untrack_pending(callback_query.message.chat.id, interaction_id)

        if self._response_callback:
            await self._response_callback(response)

    async def _handle_text_reply(self, message: Message) -> None:
        """Handle free-text replies from humans.

        Only processes messages from chats where we're actively
        waiting for a text response.
        """
        chat_id = message.chat.id

        if chat_id not in self._awaiting_text:
            return  # Not waiting for input from this chat — ignore

        interaction_id = self._awaiting_text.pop(chat_id)
        telegram_user_id = str(message.from_user.id)

        # Check if this is a form response (key: value format)
        text = message.text.strip()
        interaction_meta = await self._get_interaction_meta(interaction_id)

        value: Any = text
        response_type = InteractionType.FREE_TEXT

        if interaction_meta and interaction_meta.get("type") == "form":
            parsed = self._parse_form_response(text)
            if parsed:
                value = parsed
                response_type = InteractionType.FORM

        response = HumanResponse(
            interaction_id=interaction_id,
            respondent=telegram_user_id,
            response_type=response_type,
            value=value,
            timestamp=datetime.utcnow().isoformat(),
            metadata={
                "channel": "telegram",
                "chat_id": chat_id,
                "message_id": message.message_id,
            },
        )

        # Confirm receipt
        await message.reply("✅ Got it, processing your response...")
        self._untrack_pending(chat_id, interaction_id)

        if self._response_callback:
            await self._response_callback(response)

    # ─── User-initiated cancellation ──────────────────────────────────────

    async def _handle_cancel_command(self, message: "Message") -> None:
        """Cancel every pending interaction for this chat on /cancel."""
        chat_id = message.chat.id
        pending = self._pending_by_chat.pop(chat_id, set())
        # Also clear any awaiting-text marker so a post-cancel message
        # falls through to the wrapper as a regular query.
        self._awaiting_text.pop(chat_id, None)

        if not pending:
            return  # Filter should prevent this, but be defensive.

        cancelled = 0
        for interaction_id in pending:
            await self.cancel_interaction(interaction_id, str(chat_id))
            if self._cancel_callback:
                try:
                    if await self._cancel_callback(interaction_id):
                        cancelled += 1
                except Exception:
                    self.logger.exception(
                        "cancel callback failed for %s", interaction_id
                    )
            else:
                cancelled += 1

        await message.reply(
            f"🛑 Cancelled {cancelled} pending interaction(s)."
        )

    async def _handle_callback_cancel(
        self,
        callback_query: "CallbackQuery",
        master_token: str,
        telegram_user_id: str,
    ) -> None:
        """Handle ✕ Cancel button on a multi-choice prompt (master token path)."""
        token_data = await self._get_token_data(master_token)
        if not token_data:
            await callback_query.answer("Session expired", show_alert=True)
            return
        if token_data.get("human_id") != telegram_user_id:
            await callback_query.answer("⛔ Not authorized", show_alert=True)
            return
        await self._cancel_by_interaction(
            callback_query,
            token_data["interaction_id"],
            token=master_token,
        )

    async def _cancel_by_interaction(
        self,
        callback_query: "CallbackQuery",
        interaction_id: str,
        *,
        token: Optional[str] = None,
    ) -> None:
        """Shared cancellation path used by per-interaction cancel tokens."""
        chat_id = callback_query.message.chat.id
        # Edit the original message to reflect the cancel
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
            await callback_query.message.edit_text(
                (callback_query.message.text or "")
                + "\n\n🛑 _Cancelled by user._",
                parse_mode=self.parse_mode,
            )
        except Exception:
            pass

        await callback_query.answer("🛑 Cancelled")
        if token:
            await self._invalidate_token(token)

        # Clean up multi-choice in-memory state if applicable
        self._multi_selections.pop(token or "", None)

        # Clean up awaiting-text for this chat if it was the target
        if self._awaiting_text.get(chat_id) == interaction_id:
            self._awaiting_text.pop(chat_id, None)

        self._untrack_pending(chat_id, interaction_id)

        # Dispatch to manager to resolve the pending future as CANCELLED
        if self._cancel_callback:
            try:
                await self._cancel_callback(interaction_id)
            except Exception:
                self.logger.exception(
                    "cancel callback failed for %s", interaction_id
                )

    @staticmethod
    def _parse_form_response(text: str) -> Optional[Dict[str, str]]:
        """Try to parse a text reply as form field:value pairs.

        Accepts formats:
            field1: value1
            field2: value2
        """
        lines = text.strip().split("\n")
        result: Dict[str, str] = {}
        for line in lines:
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().lower().replace(" ", "_")
                val = val.strip()
                if key and val:
                    result[key] = val

        return result if result else None

    # ─── Token Management (Security) ─────────────────────────────────────

    async def _create_token(
        self,
        interaction_id: str,
        human_id: str,
        action: str,
        extra: Optional[dict] = None,
    ) -> str:
        """Create a secure, single-use callback token.

        The token is bound to a specific interaction + human + action.
        Stored in Redis with TTL for automatic cleanup.
        """
        token = secrets.token_urlsafe(16)
        data: Dict[str, Any] = {
            "interaction_id": interaction_id,
            "human_id": human_id,
            "action": action,
            "created_at": datetime.utcnow().isoformat(),
        }
        if extra:
            data["extra"] = extra

        await self.redis.set(
            f"hitl:token:{token}", json.dumps(data), ex=self.token_ttl
        )
        return token

    async def _validate_token(
        self, token: str, telegram_user_id: str
    ) -> Optional[dict]:
        """Validate a callback token and verify the respondent."""
        raw = await self.redis.get(f"hitl:token:{token}")
        if not raw:
            return None

        data = json.loads(raw)
        if data.get("human_id") != telegram_user_id:
            self.logger.warning(
                "Unauthorized callback: token belongs to %s, "
                "but received from %s",
                data.get("human_id"),
                telegram_user_id,
            )
            return None

        return data

    async def _get_token_data(self, token: str) -> Optional[dict]:
        """Get token data without identity validation."""
        raw = await self.redis.get(f"hitl:token:{token}")
        if not raw:
            return None
        return json.loads(raw)

    async def _invalidate_token(self, token: str) -> None:
        """Delete a used token."""
        await self.redis.delete(f"hitl:token:{token}")

    # ─── Interaction Metadata (Redis) ─────────────────────────────────────

    async def _store_interaction_meta(
        self, interaction: HumanInteraction, recipient: str
    ) -> None:
        """Store interaction metadata for response handling."""
        meta: Dict[str, Any] = {
            "type": interaction.interaction_type.value,
            "source_agent": interaction.source_agent,
            "target_humans": interaction.target_humans,
        }
        if interaction.options:
            meta["options"] = [o.model_dump() for o in interaction.options]
        if interaction.form_schema:
            meta["form_schema"] = interaction.form_schema

        await self.redis.set(
            f"hitl:meta:{interaction.interaction_id}",
            json.dumps(meta),
            ex=self.token_ttl,
        )

    async def _get_interaction_meta(
        self, interaction_id: str
    ) -> Optional[dict]:
        """Retrieve stored interaction metadata."""
        raw = await self.redis.get(f"hitl:meta:{interaction_id}")
        if not raw:
            return None
        return json.loads(raw)

    async def _store_message_id(
        self, interaction_id: str, chat_id: int, message_id: int
    ) -> None:
        """Store the Telegram message ID for later editing/cancellation."""
        await self.redis.set(
            f"hitl:msg:{interaction_id}:{chat_id}",
            str(message_id),
            ex=self.token_ttl,
        )

    # ─── Message Formatting ───────────────────────────────────────────────

    def _format_message(self, interaction: HumanInteraction) -> str:
        """Format an interaction into a Telegram message."""
        source = (
            interaction.source_agent
            or interaction.source_flow
            or "Agent"
        )

        parts = [f"🤖 *{self._escape_md(source)}*\n"]

        if interaction.context:
            parts.append(f"_{self._escape_md(interaction.context)}_\n")

        parts.append(f"\n{self._escape_md(interaction.question)}")

        # Add options for choice types
        if (
            interaction.interaction_type
            in (InteractionType.SINGLE_CHOICE, InteractionType.MULTI_CHOICE)
            and interaction.options
        ):
            parts.append("\n")
            for opt in interaction.options:
                desc = f" — {opt.description}" if opt.description else ""
                parts.append(
                    f"  `{opt.key}` {self._escape_md(opt.label)}"
                    f"{self._escape_md(desc)}"
                )

        return "\n".join(parts)

    @staticmethod
    def _escape_md(text: str) -> str:
        """Escape special Markdown characters for Telegram."""
        if not text:
            return ""
        for char in (
            "_", "*", "[", "]", "(", ")", "~", "`", ">",
            "#", "+", "-", "=", "|", "{", "}", ".", "!",
        ):
            text = text.replace(char, f"\\{char}")
        return text
