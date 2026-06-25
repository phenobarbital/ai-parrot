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

        if activity_type == ActivityTypes.message:
            await self._handle_message(context)
        elif activity_type == ActivityTypes.conversation_update:
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

        response = await self.parrot_agent.ask(
            question=text.strip(),
            session_id=session_id,
            user_id=user_id,
        )
        await context.send_activity(str(response.content))

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
                await context.send_activity(self.welcome_message)
