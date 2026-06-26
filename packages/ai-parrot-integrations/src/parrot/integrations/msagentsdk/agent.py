"""
Bridge between ai-parrot AbstractBot and the Microsoft 365 Agents SDK protocol.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from navconfig.logging import logging

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.auth.context import UserContext
    from .auth import BFTokenServiceResolver


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

    Identity extraction prefers the Entra ``aad_object_id`` (stable across
    sessions and surfaces) over the channel-level ``from_property.id``, so
    the Bot Framework Token Service can key per-user tokens correctly.

    Attributes:
        parrot_agent: The ai-parrot bot instance to delegate to.
        welcome_message: Text sent when a new member joins a conversation.
        _resolver: Optional credential resolver for per-user token acquisition.
        _audit_ledger: Optional audit ledger for credential usage recording.
        logger: Logger instance scoped to this bridge.
    """

    def __init__(
        self,
        parrot_agent: AbstractBot,
        welcome_message: Optional[str] = None,
        resolver: Optional["BFTokenServiceResolver"] = None,
        audit_ledger: Optional[Any] = None,
    ) -> None:
        """Initialise the bridge.

        Args:
            parrot_agent: Any ``AbstractBot`` subclass that implements
                ``ask(question, session_id, user_id) -> AIMessage``.
            welcome_message: Message sent to new conversation members.
                Defaults to a generic greeting if not provided.
            resolver: Optional :class:`BFTokenServiceResolver` for per-user
                token acquisition from the Bot Framework Token Service.
                When ``None``, user-token acquisition is disabled.
            audit_ledger: Optional :class:`AuditLedger` for recording
                per-invocation credential usage. When ``None``, audit logging
                is disabled.
        """
        self.parrot_agent = parrot_agent
        self.welcome_message = welcome_message or "Hello! I'm ready to help."
        self._resolver = resolver
        self._audit_ledger = audit_ledger
        self.logger = logging.getLogger(
            f"ParrotM365Agent.{type(parrot_agent).__name__}"
        )

    async def on_turn(self, context) -> None:
        """Handle an incoming Activity from the Microsoft 365 Agents SDK.

        Routes activities by type:
        - ``message`` → ``_handle_message()``
        - ``conversationUpdate`` → ``_handle_conversation_update()``
        - ``invoke`` → ``_handle_signin_verify()`` or
          ``_handle_signin_exchange()`` depending on the invoke name.
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
        elif activity_type in ("invoke",):
            name = getattr(activity, "name", None) or ""
            if name == "signin/verifyState":
                await self._handle_signin_verify(context)
            elif name == "signin/tokenExchange":
                await self._handle_signin_exchange(context)
            else:
                self.logger.debug("Ignoring invoke type: %s", name)
        else:
            self.logger.debug("Ignoring activity type: %s", activity_type)

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    def _extract_user_id(self, activity: Any) -> str:
        """Extract canonical user identity from an Activity.

        Prefers ``aad_object_id`` (Entra identity) from ``from_property`` as
        the stable canonical key for the Bot Framework Token Service. Falls
        back to the channel-level ``from_property.id`` when the Entra id is
        not present (e.g. anonymous / non-Teams channels).

        Args:
            activity: The incoming Activity object.

        Returns:
            A non-empty string user identifier.
        """
        from_prop = getattr(activity, "from_property", None)
        if from_prop is None:
            return "anonymous"
        # Try aad_object_id (Entra identity — preferred canonical key)
        aad_id = getattr(from_prop, "aad_object_id", None)
        if not aad_id:
            # Some SDK versions expose it as camelCase
            aad_id = getattr(from_prop, "aadObjectId", None)
        if aad_id:
            return str(aad_id)
        # Fall back to the channel-level user identifier
        channel_id = getattr(from_prop, "id", None)
        return channel_id or "anonymous"

    def _build_user_context(self, activity: Any) -> "UserContext":
        """Build a :class:`UserContext` from the Activity's sender identity.

        Args:
            activity: The incoming Activity object.

        Returns:
            A :class:`UserContext` with ``channel="msagentsdk"`` and
            ``user_id`` derived from :meth:`_extract_user_id`.
        """
        from parrot.auth.context import UserContext

        user_id = self._extract_user_id(activity)
        display_name: Optional[str] = None
        from_prop = getattr(activity, "from_property", None)
        if from_prop is not None:
            display_name = getattr(from_prop, "name", None)
        session_id: Optional[str] = (
            activity.conversation.id if getattr(activity, "conversation", None) else None
        )
        return UserContext(
            channel="msagentsdk",
            user_id=user_id,
            display_name=display_name,
            session_id=session_id,
        )

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _handle_message(self, context) -> None:
        """Route a ``message`` activity to the parrot agent and reply.

        Extracts the canonical user identity (``aad_object_id`` preferred),
        builds a :class:`PermissionContext`, sets ``_pctx_var``, and passes a
        :class:`RequestContext` to ``ask()`` so downstream tools can access
        the per-user identity.

        If a tool raises :class:`CredentialRequired`, emits a native OAuthCard
        sign-in activity instead of an error. Never falls back to service
        identity for a per-user tool.

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

        user_id: str = self._extract_user_id(activity)
        session_id: Optional[str] = (
            activity.conversation.id if getattr(activity, "conversation", None) else None
        )

        self.logger.info(
            "Message from user=%s session=%s", user_id, session_id
        )

        # Build permission context and set ContextVar for downstream tools
        from parrot.auth.permission import UserSession, PermissionContext
        from parrot.auth.context import _pctx_var
        from parrot.utils.helpers import RequestContext
        from .auth import _resolver_var

        user_session = UserSession(
            user_id=user_id,
            tenant_id="msagentsdk",
            roles=frozenset(),
        )
        pctx = PermissionContext(
            session=user_session,
            channel="msagentsdk",
        )
        token = _pctx_var.set(pctx)
        resolver_token = _resolver_var.set(
            (self._resolver, context) if self._resolver else None
        )
        request_ctx = RequestContext(user_id=user_id, session_id=session_id)

        try:
            response = await self.parrot_agent.ask(
                question=text.strip(),
                session_id=session_id,
                user_id=user_id,
                ctx=request_ctx,
            )
            await self._send_text(context, str(response.content))
        except Exception as exc:  # noqa: BLE001
            # Check for CredentialRequired (lazy import — avoids hard dependency
            # on auth module when OAuth is not configured)
            try:
                from .auth import CredentialRequired
            except ImportError:
                CredentialRequired = None  # type: ignore[assignment,misc]

            if CredentialRequired is not None and isinstance(exc, CredentialRequired):
                self.logger.info(
                    "CredentialRequired for tool=%s connection=%s — emitting OAuthCard",
                    exc.tool,
                    exc.connection_name,
                )
                await self._emit_oauth_card(context, exc.connection_name, exc.tool)
            else:
                self.logger.error(
                    "Error processing message from user=%s: %s",
                    user_id,
                    exc,
                    exc_info=True,
                )
                await self._send_text(
                    context, "Sorry, I encountered an error. Please try again."
                )
        finally:
            _resolver_var.reset(resolver_token)
            _pctx_var.reset(token)

    # ------------------------------------------------------------------
    # Invoke handlers (sign-in round-trip)
    # ------------------------------------------------------------------

    async def _handle_signin_verify(self, context) -> None:
        """Handle a ``signin/verifyState`` invoke activity.

        The Bot Framework Token Service sends this activity after the user
        completes the OAuth sign-in. The token is already stored in the token
        service at this point; we just need to acknowledge the invoke with a
        200 response.

        Args:
            context: ``TurnContext`` carrying the ``invoke`` Activity.
        """
        activity = context.activity
        value = getattr(activity, "value", None) or {}
        state = (
            value.get("state")
            if isinstance(value, dict)
            else getattr(value, "state", None)
        )
        self.logger.info(
            "signin/verifyState received: user=%s state_present=%s",
            self._extract_user_id(activity),
            bool(state),
        )
        await self._send_invoke_response(context, status_code=200)

    async def _handle_signin_exchange(self, context) -> None:
        """Handle a ``signin/tokenExchange`` invoke activity.

        The Bot Framework Token Service sends this activity to complete a Teams
        SSO token exchange. The service performs the exchange server-side; we
        acknowledge with a 200 response.

        Args:
            context: ``TurnContext`` carrying the ``invoke`` Activity.
        """
        activity = context.activity
        value = getattr(activity, "value", None) or {}
        connection_name = (
            value.get("connectionName")
            if isinstance(value, dict)
            else getattr(value, "connection_name", None)
        )
        self.logger.info(
            "signin/tokenExchange received: user=%s connection=%s",
            self._extract_user_id(activity),
            connection_name,
        )
        await self._send_invoke_response(context, status_code=200)

    @staticmethod
    async def _send_invoke_response(context, status_code: int = 200) -> None:
        """Send an invoke response activity.

        Args:
            context: ``TurnContext`` used to emit the response.
            status_code: HTTP-style status code for the invoke response.
        """
        from microsoft_agents.activity import Activity

        # ActivityTypes.invoke_response is not available in all SDK versions;
        # fall back to the raw string which Bot Framework always recognises.
        try:
            from microsoft_agents.activity import ActivityTypes
            invoke_response_type = ActivityTypes.invoke_response
        except AttributeError:
            invoke_response_type = "invokeResponse"

        response = Activity(type=invoke_response_type)
        response.value = {"status": status_code}
        await context.send_activity(response)

    # ------------------------------------------------------------------
    # OAuth sign-in card
    # ------------------------------------------------------------------

    async def _emit_oauth_card(
        self,
        context,
        connection_name: str,
        tool: str,
    ) -> None:
        """Emit a native OAuthCard sign-in activity.

        The OAuthCard triggers the Bot Framework Token Service's hosted OAuth
        flow. The token is NEVER included in the card — the token service
        handles credential exchange server-side.

        Args:
            context: ``TurnContext`` to send the reply through.
            connection_name: Azure Bot OAuth connection name (e.g. ``"graph_sso"``).
            tool: Tool name requesting credentials (used in card text only;
                never exposes a secret).
        """
        from microsoft_agents.activity import Activity, ActivityTypes

        signin_text = f"Please sign in to authorize access for {tool}."
        oauth_card_attachment = {
            "contentType": "application/vnd.microsoft.card.oauth",
            "content": {
                "text": signin_text,
                "connectionName": connection_name,
            },
        }
        reply = Activity(
            type=ActivityTypes.message,
            attachments=[oauth_card_attachment],
        )
        await context.send_activity(reply)
        self.logger.info(
            "OAuthCard emitted for tool=%s connection=%s", tool, connection_name
        )

    # ------------------------------------------------------------------
    # Conversation update
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

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
