"""
Bridge between ai-parrot AbstractBot and the Microsoft 365 Agents SDK protocol.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot


class ParrotM365Agent:
    """Bridges ai-parrot AbstractBot to the Microsoft 365 Agent protocol.

    Implements the ``Agent`` protocol from ``microsoft_agents.hosting.core``
    (a single ``on_turn(context: TurnContext)`` coroutine). This class is
    intentionally thin: it extracts the message text, sender identity, and
    conversation ID from the inbound Activity envelope, delegates to
    ``parrot_agent.ask()``, and sends the reply back via
    ``context.send_activity()``.

    All ``microsoft_agents.*`` imports are lazy (inside methods) so the
    package can be imported without the SDK installed.

    Attributes:
        parrot_agent: The ai-parrot bot instance to delegate to.
        welcome_message: Text sent when a new member joins a conversation.
        logger: Logger instance scoped to this bridge.
    """

    def __init__(
        self,
        parrot_agent: AbstractBot,
        welcome_message: Optional[str] = None,
    ) -> None:
        """Initialise the bridge.

        Args:
            parrot_agent: Any ``AbstractBot`` subclass that implements
                ``ask(question, session_id, user_id) -> AIMessage``.
            welcome_message: Message sent to new conversation members.
                Defaults to a generic greeting if not provided.
        """
        self.parrot_agent = parrot_agent
        self.welcome_message = welcome_message or "Hello! I'm ready to help."
        self.logger = logging.getLogger(
            f"ParrotM365Agent.{type(parrot_agent).__name__}"
        )

    async def on_turn(self, context) -> None:
        """Handle an incoming Activity from the Microsoft 365 Agents SDK.

        Routes activities by type:
        - ``message`` → ``_handle_message()``
        - ``conversationUpdate`` → ``_handle_conversation_update()``
        - Other types → logged at DEBUG and ignored.

        Args:
            context: ``TurnContext`` from the MS Agent SDK (not type-annotated
                here to keep the import lazy).
        """
        from microsoft_agents.activity import ActivityTypes

        activity = context.activity
        activity_type = activity.type

        if activity_type in (ActivityTypes.message, "message"):
            await self._handle_message(context)
        elif activity_type in (ActivityTypes.conversation_update, "conversationUpdate"):
            await self._handle_conversation_update(context)
        else:
            self.logger.debug("Ignoring activity type: %s", activity_type)

    async def _handle_message(self, context) -> None:
        """Route a ``message`` activity to the parrot agent and reply.

        If the message text is empty or whitespace-only the method returns
        immediately without calling ``ask()`` to avoid unnecessary LLM calls.

        Args:
            context: ``TurnContext`` carrying the inbound message Activity.
        """
        activity = context.activity
        text: Optional[str] = activity.text

        if not text or not text.strip():
            self.logger.debug("Received empty message — skipping ask()")
            return

        user_id: Optional[str] = (
            activity.from_property.id if activity.from_property else None
        )
        session_id: Optional[str] = (
            activity.conversation.id if activity.conversation else None
        )

        self.logger.info(
            "Message from user=%s session=%s", user_id, session_id
        )

        try:
            response = await self.parrot_agent.ask(
                question=text.strip(),
                session_id=session_id,
                user_id=user_id,
            )
            await self._send_text(context, str(response.content))
        except Exception as exc:
            self.logger.error(
                "Error processing message from user=%s: %s", user_id, exc, exc_info=True
            )
            await self._send_text(context, "Sorry, I encountered an error. Please try again.")

    async def _handle_conversation_update(self, context) -> None:
        """Send a welcome message when new members join a conversation.

        Only sends the welcome message to members that are NOT the bot
        itself (identified by comparing member IDs to ``recipient.id``).

        Args:
            context: ``TurnContext`` carrying the ``conversationUpdate`` Activity.
        """
        activity = context.activity
        if not activity.members_added:
            return

        bot_id: Optional[str] = (
            activity.recipient.id if activity.recipient else None
        )
        for member in activity.members_added:
            if member.id != bot_id:
                await self._send_text(context, self.welcome_message)

    @staticmethod
    async def _send_text(context, text: str) -> None:
        """Send a reply as plain text to avoid channel markdown parsing.

        The Bot Framework defaults an outbound ``message`` Activity's
        ``textFormat`` to ``markdown``. Channels such as Telegram then try
        to render the text as MarkdownV2, where characters like ``-``,
        ``.``, ``!`` and ``(`` are reserved and must be escaped — an
        unescaped one makes the channel reject the message with a 400
        ("can't parse entities"). Sending as ``plain`` tells the channel to
        deliver the text verbatim, so agent replies are never mangled or
        rejected because of incidental markdown characters.

        Args:
            context: ``TurnContext`` used to emit the reply.
            text: The message body to send verbatim.
        """
        from microsoft_agents.activity import Activity, ActivityTypes, TextFormatTypes

        await context.send_activity(
            Activity(
                type=ActivityTypes.message,
                text=text,
                text_format=TextFormatTypes.plain,
            )
        )
