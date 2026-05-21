"""WebHumanChannel — delivers HITL interactions over WebSocket.

Implements :class:`HumanChannel` using the existing
:class:`~parrot.handlers.user.UserSocketManager` infrastructure to push
``hitl:question`` payloads to the browser over the channel named after
the user's session ID.

The HTTP POST endpoint (:class:`~parrot.handlers.web_hitl.HITLResponseHandler`)
reaches the manager *directly* via ``manager.receive_response()``, so this
channel stores the response callback (required by the ``HumanChannel``
contract) but does not invoke it itself.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, Optional

from .base import HumanChannel, ESCALATE_OPTION_KEY
from ..models import HumanInteraction, HumanResponse, InteractionType

if TYPE_CHECKING:
    from ...handlers.user import UserSocketManager


class WebHumanChannel(HumanChannel):
    """Human channel that delivers interactions via WebSocket.

    Translates :class:`~parrot.human.models.HumanInteraction` objects into
    JSON payloads of type ``hitl:question`` and publishes them to the
    WebSocket channel identified by the ``recipient`` argument (which is
    typically the user's ``session_id``).

    Args:
        socket_manager: The :class:`~parrot.handlers.user.UserSocketManager`
            instance used to publish messages to WebSocket channels.

    Attributes:
        channel_type: Identifier for this channel type, fixed to ``"web"``.
    """

    channel_type: str = "web"
    render_reject_button: bool = True

    def __init__(self, socket_manager: "UserSocketManager") -> None:
        """Initialise the WebHumanChannel.

        Args:
            socket_manager: Shared :class:`~parrot.handlers.user.UserSocketManager`
                attached to ``app['user_socket_manager']``.
        """
        self.socket_manager = socket_manager
        self._response_callback: Optional[Callable[[HumanResponse], Awaitable[None]]] = None
        self.logger = logging.getLogger(__name__)

    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        """Serialize an interaction and push it to the user's WebSocket channel.

        Builds a ``hitl:question`` JSON payload from *interaction* and calls
        ``socket_manager.notify_channel(recipient, payload)``.

        Args:
            interaction: The interaction to deliver.
            recipient: WebSocket channel name — typically the user's session ID.

        Returns:
            ``True`` if the message was delivered (at least one subscriber
            received it), ``False`` if the channel had no subscribers.
        """
        payload = self._build_question_payload(interaction)
        self.logger.info(
            "WebHumanChannel: sending %s interaction %s to channel %s",
            interaction.interaction_type.value,
            interaction.interaction_id,
            recipient,
        )
        result = await self.socket_manager.notify_channel(recipient, payload)
        if not result:
            self.logger.warning(
                "WebHumanChannel: no subscribers on channel %s; "
                "interaction %s may not be delivered.",
                recipient,
                interaction.interaction_id,
            )
        return result

    async def register_response_handler(
        self,
        callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None:
        """Store the response callback registered by the manager.

        The web channel does not invoke this callback itself — the
        :class:`~parrot.handlers.web_hitl.HITLResponseHandler` calls
        ``manager.receive_response()`` directly. The callback is stored
        to satisfy the :class:`HumanChannel` contract.

        Args:
            callback: Async callable invoked with a :class:`~parrot.human.models.HumanResponse`
                when a human responds.
        """
        self._response_callback = callback
        self.logger.debug("WebHumanChannel: response handler registered.")

    async def send_notification(
        self,
        recipient: str,
        message: str,
    ) -> None:
        """Send a plain notification message to a WebSocket channel.

        Args:
            recipient: WebSocket channel name to publish to.
            message: Plain-text notification string.
        """
        payload: Dict[str, Any] = {
            "type": "hitl:notification",
            "recipient": recipient,
            "message": message,
        }
        self.logger.info(
            "WebHumanChannel: sending notification to channel %s", recipient
        )
        await self.socket_manager.notify_channel(recipient, payload)

    async def cancel_interaction(
        self,
        interaction_id: str,
        recipient: str,
    ) -> bool:
        """Emit a cancellation payload to the user's WebSocket channel.

        Args:
            interaction_id: UUID of the interaction being cancelled.
            recipient: WebSocket channel name to publish to.

        Returns:
            ``True`` when the socket manager accepted the publish,
            ``False`` if it raised.
        """
        payload: Dict[str, Any] = {
            "type": "hitl:cancel",
            "interaction_id": interaction_id,
            "reason": "interaction_cancelled",
        }
        self.logger.info(
            "WebHumanChannel: cancelling interaction %s on channel %s",
            interaction_id,
            recipient,
        )
        try:
            await self.socket_manager.notify_channel(recipient, payload)
            return True
        except Exception:
            self.logger.exception(
                "WebHumanChannel: failed to publish cancel for %s",
                interaction_id,
            )
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_question_payload(self, interaction: HumanInteraction) -> Dict[str, Any]:
        """Build the ``hitl:question`` wire payload from a HumanInteraction.

        Args:
            interaction: The interaction to serialise.

        Returns:
            A dict ready to be JSON-serialised and pushed over the WebSocket.
        """
        # Compute ISO-8601 deadline from the interaction timeout
        now = datetime.now(tz=timezone.utc)
        deadline = (
            now + timedelta(seconds=interaction.timeout)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        payload: Dict[str, Any] = {
            "type": "hitl:question",
            "interaction_id": interaction.interaction_id,
            "interaction_type": interaction.interaction_type.value,
            "question": interaction.question,
            "context": interaction.context,
            "options": None,
            "form_schema": None,
            "default_response": interaction.default_response,
            "timeout": interaction.timeout,
            "source_agent": interaction.source_agent,
            "deadline": deadline,
        }

        # Populate options for choice-based types
        if interaction.options is not None:
            payload["options"] = [
                {
                    "key": opt.key,
                    "label": opt.label,
                    "description": opt.description,
                }
                for opt in interaction.options
            ]
        else:
            payload["options"] = []

        # Append the escalate affordance for policy-bound interactions
        if interaction.policy is not None and self.render_reject_button:
            if payload["options"] is None:
                payload["options"] = []
            payload["options"].append(
                {
                    "key": ESCALATE_OPTION_KEY,
                    "label": "↑ Escalar",
                    "description": None,
                }
            )

        # Include form_schema for FORM type
        if interaction.interaction_type == InteractionType.FORM:
            payload["form_schema"] = interaction.form_schema

        self.logger.debug(
            "WebHumanChannel: built payload for interaction %s (type=%s)",
            interaction.interaction_id,
            interaction.interaction_type.value,
        )
        return payload
