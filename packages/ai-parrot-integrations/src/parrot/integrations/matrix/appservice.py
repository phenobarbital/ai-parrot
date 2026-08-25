"""Matrix Application Service for AI-Parrot.

Wraps mautrix.appservice.AppService to provide:
- Virtual MXIDs for each registered agent
- Event routing from homeserver push to agents
- HookEvent emission compatible with AutonomousOrchestrator
- Lifecycle management (start/stop)
"""
from __future__ import annotations
import inspect
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from navconfig.logging import logging

try:
    from mautrix.appservice import AppService as MautrixAppService
    from mautrix.appservice import IntentAPI
    from mautrix.types import (
        Event,
        EventType,
        RoomID,
        UserID,
        StateEvent,
    )
    HAS_MAUTRIX = True
except ImportError:
    HAS_MAUTRIX = False

from .models import MatrixAppServiceConfig
from .events import ParrotEventType


# Type alias for event handler callbacks
EventCallback = Callable[[str, str, str, Any], Coroutine[Any, Any, None]]


class MatrixAppService:
    """Matrix Application Service for AI-Parrot.

    Provides each registered agent with a virtual MXID and receives
    events from the homeserver via HTTP push (no polling).

    Usage::

        config = MatrixAppServiceConfig(
            as_token="...",
            hs_token="...",
            homeserver="http://localhost:8008",
            server_name="parrot.local",
            agent_mxid_map={"FinanceAgent": "parrot-finance"},
        )
        appservice = MatrixAppService(config)
        appservice.set_event_callback(my_handler)
        await appservice.start()

        # Each agent gets its own Matrix presence
        await appservice.register_agent("FinanceAgent", "Finance Agent")

        # Send a message as a specific agent
        await appservice.send_as_agent(
            "FinanceAgent", "!room:server", "Revenue is $1M"
        )
    """

    def __init__(self, config: MatrixAppServiceConfig) -> None:
        if not HAS_MAUTRIX:
            raise ImportError(
                "mautrix is required for Matrix integration. "
                "Install with: uv pip install 'ai-parrot[matrix]'"
            )
        self._config = config
        self._appservice: Optional[MautrixAppService] = None
        self._registered_agents: Dict[str, str] = {}  # name → mxid
        self._agent_rooms: Dict[str, Set[str]] = {}  # mxid → room_ids
        self._event_callback: Optional[EventCallback] = None
        self._custom_event_callback: Optional[Callable] = None  # for m.parrot.* events
        self.logger = logging.getLogger("parrot.matrix.appservice")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Application Service HTTP server."""
        self._appservice = MautrixAppService(
            server=self._config.homeserver,
            domain=self._config.server_name,
            as_token=self._config.as_token,
            hs_token=self._config.hs_token,
            bot_localpart=self._config.bot_localpart,
            id=self._config.as_id,
            log=self.logger,
            query_user=self._query_user,
            query_alias=self._query_alias,
        )

        # Register event handler for all room events
        self._appservice.matrix_event_handler(self._handle_event)

        await self._appservice.start(
            host=self._config.listen_host,
            port=self._config.listen_port,
        )

        self._appservice.ready = True
        self.logger.info(
            f"Matrix AppService started on "
            f"{self._config.listen_host}:{self._config.listen_port} "
            f"(bot: {self._config.bot_mxid})"
        )

        # Auto-join configured rooms
        for room_id in self._config.auto_join_rooms:
            try:
                await self.bot_intent.ensure_joined(RoomID(room_id))
                self.logger.info("Bot joined room %s", room_id)
            except Exception as exc:
                self.logger.warning(
                    f"Failed to join room {room_id}: {exc}"
                )

    async def stop(self) -> None:
        """Stop the Application Service HTTP server."""
        if self._appservice:
            await self._appservice.stop()
            self._appservice = None
        self._registered_agents.clear()
        self._agent_rooms.clear()
        self.logger.info("Matrix AppService stopped")

    @property
    def running(self) -> bool:
        """Whether the AS is currently running."""
        return self._appservice is not None

    @property
    def bot_intent(self) -> IntentAPI:
        """Get the IntentAPI for the bot user."""
        if not self._appservice:
            raise RuntimeError("AppService not started")
        return self._appservice.intent

    # ------------------------------------------------------------------
    # Agent Management
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        agent_name: str,
        displayname: Optional[str] = None,
    ) -> str:
        """Register an agent as a virtual Matrix user.

        Args:
            agent_name: Agent name (used for MXID generation).
            displayname: Display name for the virtual user.

        Returns:
            The full MXID of the virtual user.
        """
        mxid = self._config.agent_mxid(agent_name)
        intent = self._get_intent(mxid)

        # Ensure the user exists (created on first use by AS)
        await intent.ensure_registered()

        # Set display name
        display = displayname or agent_name
        await intent.set_displayname(display)

        self._registered_agents[agent_name] = mxid
        self._agent_rooms.setdefault(mxid, set())

        self.logger.info(
            f"Registered agent '{agent_name}' as {mxid} "
            f"(displayname: {display})"
        )
        return mxid

    async def unregister_agent(self, agent_name: str) -> None:
        """Remove a virtual agent (leaves rooms, clears state)."""
        mxid = self._registered_agents.pop(agent_name, None)
        if not mxid:
            return

        # Leave all rooms
        rooms = self._agent_rooms.pop(mxid, set())
        intent = self._get_intent(mxid)
        for room_id in rooms:
            try:
                await intent.leave_room(RoomID(room_id))
            except Exception:
                pass

        self.logger.info("Unregistered agent '%s' (%s)", agent_name, mxid)

    async def ensure_agent_in_room(
        self,
        agent_name: str,
        room_id: str,
    ) -> None:
        """Join a virtual agent to a room.

        Args:
            agent_name: Name of a registered agent.
            room_id: Room to join.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(
                f"Agent '{agent_name}' not registered. "
                f"Call register_agent() first."
            )

        intent = self._get_intent(mxid)

        # Bot invites, then agent joins
        try:
            await self.bot_intent.invite_user(
                RoomID(room_id), UserID(mxid)
            )
        except Exception:
            pass  # Already invited or member

        await intent.ensure_joined(RoomID(room_id))
        self._agent_rooms.setdefault(mxid, set()).add(room_id)

        self.logger.info(
            f"Agent '{agent_name}' joined room {room_id}"
        )

    def list_agents(self) -> Dict[str, str]:
        """Return mapping of registered agent_name → mxid."""
        return dict(self._registered_agents)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_as_agent(
        self,
        agent_name: str,
        room_id: str,
        message: str,
    ) -> str:
        """Send a message to a room as a specific agent.

        Args:
            agent_name: Name of the registered agent.
            room_id: Target room.
            message: Message text.

        Returns:
            Event ID of the sent message.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(f"Agent '{agent_name}' not registered")

        intent = self._get_intent(mxid)
        event_id = await intent.send_text(RoomID(room_id), message)
        return str(event_id)

    async def send_formatted_as_agent(
        self,
        agent_name: str,
        room_id: str,
        body: str,
        formatted_body: str,
    ) -> str:
        """Send a formatted HTML message as a specific virtual agent.

        Sends a ``m.text`` event with both a plain-text ``body`` and an HTML
        ``formatted_body``, using the ``org.matrix.custom.html`` format. Matrix
        clients that support rich text will render the HTML; others fall back
        to the plain-text body.

        Args:
            agent_name: Name of the registered agent.
            room_id: Target room.
            body: Plain-text message body (shown in non-HTML clients).
            formatted_body: HTML-formatted message body (shown in rich clients).

        Returns:
            Event ID of the sent message.

        Raises:
            ValueError: If the agent is not registered.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(f"Agent '{agent_name}' not registered")

        intent = self._get_intent(mxid)
        from mautrix.types import (  # type: ignore
            Format,
            MessageType,
            TextMessageEventContent,
        )

        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=body,
            format=Format.HTML,
            formatted_body=formatted_body,
        )
        event_id = await intent.send_message(RoomID(room_id), content)
        return str(event_id)

    async def send_as_bot(self, room_id: str, message: str) -> str:
        """Send a message as the bot user."""
        event_id = await self.bot_intent.send_text(
            RoomID(room_id), message
        )
        return str(event_id)

    async def send_custom_event_as_agent(
        self,
        agent_name: str,
        room_id: str,
        event_type: str,
        content: dict,
    ) -> Optional[str]:
        """Send a custom Matrix event as a specific virtual agent.

        Args:
            agent_name: The registered agent name.
            room_id: The Matrix room ID.
            event_type: The Matrix event type string.
            content: The event content dict.

        Returns:
            The event ID if sent successfully, None otherwise.
        """
        from mautrix.types import EventType as MxEventType, RoomID  # type: ignore

        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            self.logger.warning(
                "send_custom_event_as_agent: unknown agent %s", agent_name
            )
            return None
        intent = self._get_intent(mxid)
        custom_type = MxEventType.find(
            event_type, t_class=MxEventType.Class.MESSAGE
        )
        event_id = await intent.send_message_event(RoomID(room_id), custom_type, content)
        return str(event_id)

    async def send_reply_as_agent(
        self,
        agent_name: str,
        room_id: str,
        message: str,
        reply_to_event_id: str,
    ) -> str:
        """Send a reply-to message as a specific virtual agent.

        Sets the ``m.in_reply_to`` relation so Matrix clients render the
        message as a threaded reply to the referenced event.

        Args:
            agent_name: Name of the registered agent.
            room_id: Target room.
            message: Reply text.
            reply_to_event_id: Event ID of the message being replied to.

        Returns:
            Event ID of the sent reply.

        Raises:
            ValueError: If the agent is not registered.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(f"Agent '{agent_name}' not registered")

        intent = self._get_intent(mxid)
        from mautrix.types import (  # type: ignore
            MessageType,
            TextMessageEventContent,
        )

        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=message,
        )
        content["m.relates_to"] = {
            "m.in_reply_to": {"event_id": reply_to_event_id}
        }
        event_id = await intent.send_message(RoomID(room_id), content)
        return str(event_id)

    async def send_reply_as_bot(
        self,
        room_id: str,
        message: str,
        reply_to_event_id: str,
    ) -> str:
        """Send a reply-to message as the bot user.

        Sets the ``m.in_reply_to`` relation so Matrix clients render the
        message as a threaded reply to the referenced event.

        Args:
            room_id: Target room.
            message: Reply text.
            reply_to_event_id: Event ID of the message being replied to.

        Returns:
            Event ID of the sent reply.
        """
        from mautrix.types import (  # type: ignore
            MessageType,
            TextMessageEventContent,
        )

        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=message,
        )
        content["m.relates_to"] = {
            "m.in_reply_to": {"event_id": reply_to_event_id}
        }
        event_id = await self.bot_intent.send_message(RoomID(room_id), content)
        return str(event_id)

    # ------------------------------------------------------------------
    # Room primitives (FEAT-463)
    # ------------------------------------------------------------------

    async def create_room_as_bot(
        self,
        *,
        name: Optional[str] = None,
        alias_localpart: Optional[str] = None,
        topic: Optional[str] = None,
        is_direct: bool = False,
        preset: str = "private_chat",
        visibility: str = "private",
        invitees: Optional[List[str]] = None,
        initial_state: Optional[List[dict]] = None,
    ) -> str:
        """Create a room as the AppService bot and return its room_id.

        ``preset`` / ``visibility`` are the Matrix string values (mapped to
        the corresponding mautrix enums).

        Args:
            name: Optional room name (``m.room.name``).
            alias_localpart: Optional alias local part; a room alias
                ``#<alias_localpart>:<server_name>`` is created and mapped
                to the new room.
            topic: Optional room topic (``m.room.topic``).
            is_direct: Whether to flag the room as a direct message.
            preset: Matrix room creation preset string (``private_chat``,
                ``trusted_private_chat``, or ``public_chat``).
            visibility: Room directory visibility (``private`` or ``public``).
            invitees: Optional list of MXIDs to invite at creation time.
            initial_state: Optional list of initial state event dicts.

        Returns:
            The newly created room's id.

        Raises:
            RuntimeError: If the AppService has not been started.
        """
        from mautrix.types import RoomCreatePreset, RoomDirectoryVisibility, UserID

        room_id = await self.bot_intent.create_room(
            alias_localpart=alias_localpart,
            name=name,
            topic=topic,
            is_direct=is_direct,
            preset=RoomCreatePreset(preset),
            visibility=RoomDirectoryVisibility(visibility),
            invitees=[UserID(u) for u in invitees or []],
            initial_state=initial_state,
        )
        self.logger.info(
            "Created room %s (alias=%s, direct=%s)", room_id, alias_localpart, is_direct
        )
        return str(room_id)

    async def set_room_state_as_bot(
        self,
        room_id: str,
        event_type: str,
        content: dict,
        state_key: str = "",
    ) -> str:
        """Send a state event to a room as the AppService bot.

        Args:
            room_id: Target room id.
            event_type: The Matrix state event type string.
            content: The state event content dict.
            state_key: The state key (default ``""``).

        Returns:
            The id of the state event that was sent.
        """
        from mautrix.types import EventType as MxEventType, RoomID

        et = MxEventType.find(event_type, t_class=MxEventType.Class.STATE)
        event_id = await self.bot_intent.send_state_event(
            RoomID(room_id), et, content, state_key=state_key
        )
        return str(event_id)

    async def get_room_state_as_bot(
        self,
        room_id: str,
        event_type: str,
        state_key: str = "",
    ) -> Optional[dict]:
        """Fetch a state event from a room as the AppService bot.

        Args:
            room_id: Target room id.
            event_type: The Matrix state event type string.
            state_key: The state key (default ``""``).

        Returns:
            The state event content dict, or ``None`` if it does not exist.
        """
        from mautrix.types import EventType as MxEventType, RoomID

        et = MxEventType.find(event_type, t_class=MxEventType.Class.STATE)
        try:
            content = await self.bot_intent.get_state_event(
                RoomID(room_id), et, state_key=state_key
            )
        except Exception as exc:
            self.logger.debug(
                "get_room_state_as_bot: no state %s in %s (%s)", event_type, room_id, exc
            )
            return None
        if content is None:
            return None
        if hasattr(content, "serialize"):
            return content.serialize()
        return dict(content)

    async def resolve_alias(self, alias: str) -> Optional[str]:
        """Resolve a room alias to a room id.

        Args:
            alias: A full room alias, e.g. ``#general:parrot.local``.

        Returns:
            The resolved room id, or ``None`` if the alias does not exist.
        """
        from mautrix.types import RoomAlias

        try:
            info = await self.bot_intent.resolve_room_alias(RoomAlias(alias))
        except Exception as exc:
            self.logger.debug("resolve_alias: %s not found (%s)", alias, exc)
            return None
        if not info or not info.room_id:
            return None
        return str(info.room_id)

    async def leave_as_agent(
        self,
        agent_name: str,
        room_id: str,
        reason: Optional[str] = None,
    ) -> None:
        """Leave a room as a specific registered agent.

        Args:
            agent_name: Name of a registered agent.
            room_id: Room to leave.
            reason: Optional leave reason.

        Raises:
            ValueError: If the agent is not registered.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(f"Agent '{agent_name}' not registered")

        intent = self._get_intent(mxid)
        await intent.leave_room(RoomID(room_id), reason=reason)
        self._agent_rooms.get(mxid, set()).discard(room_id)
        self.logger.info("Agent '%s' left room %s", agent_name, room_id)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback) -> None:
        """Set the callback for incoming room messages.

        The callback signature:
            async def handler(
                room_id: str,
                sender: str,
                message: str,
                raw_event: Any,
            ) -> None
        """
        self._event_callback = callback

    def set_custom_event_callback(self, callback: Callable) -> None:
        """Set the callback for incoming custom ``m.parrot.*`` events.

        The callback is invoked for ``m.parrot.task``, ``m.parrot.result``
        and ``m.parrot.feedback`` events with signature:
            async def handler(event_type: str, content: dict, room_id: str, sender: str) -> None

        For backward compatibility, a legacy 2-arg callback
        (``async def handler(event_type: str, content: dict) -> None``, as
        used by ``HybridDelegator.on_custom_event``) is automatically
        wrapped in an adapter that drops ``room_id``/``sender``.

        Args:
            callback: Async callable accepting either
                ``(event_type, content, room_id, sender)`` or the legacy
                ``(event_type, content)``.
        """
        params = list(inspect.signature(callback).parameters.values())
        has_var_positional = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
        )
        positional_params = [
            p
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        if not has_var_positional and len(positional_params) <= 2:

            async def _adapter(event_type, content, room_id, sender):
                await callback(event_type, content)

            self._custom_event_callback = _adapter
        else:
            self._custom_event_callback = callback

    async def _handle_event(self, event: Event) -> None:
        """Process events pushed by the homeserver."""
        try:
            event_type_str = str(event.type)

            # Route custom m.parrot.* events to the custom callback
            if event_type_str in (
                ParrotEventType.TASK,
                ParrotEventType.RESULT,
                ParrotEventType.FEEDBACK,
            ):
                if self._custom_event_callback:
                    content_dict: Dict[str, Any] = {}
                    if hasattr(event, "content") and event.content is not None:
                        try:
                            content_dict = dict(event.content)
                        except Exception:
                            content_dict = {}
                    await self._custom_event_callback(
                        event_type_str,
                        content_dict,
                        str(event.room_id),
                        str(event.sender),
                    )
                return

            # Only handle room messages
            if event.type != EventType.ROOM_MESSAGE:
                return

            room_id = str(event.room_id)
            sender = str(event.sender)
            body = ""

            if hasattr(event, "content") and hasattr(event.content, "body"):
                body = event.content.body or ""

            # Ignore messages from our own virtual users
            if sender in self._registered_agents.values():
                return
            if sender == self._config.bot_mxid:
                return

            # Ignore edits
            if hasattr(event.content, "relates_to") and event.content.relates_to:
                if hasattr(event.content.relates_to, "rel_type"):
                    if str(event.content.relates_to.rel_type) == "m.replace":
                        return

            if not body:
                return

            if self._event_callback:
                await self._event_callback(room_id, sender, body, event)

        except Exception as exc:
            self.logger.error(
                f"Error handling event: {exc}", exc_info=True
            )

    async def _query_user(self, user_id: str) -> Optional[dict]:
        """Respond to homeserver user existence queries."""
        # Accept any user in our namespace
        user = UserID(user_id) if isinstance(user_id, str) else user_id
        localpart = str(user).split(":")[0].lstrip("@")

        import re
        if re.match(self._config.namespace_regex, localpart):
            return {}
        return None

    async def _query_alias(self, alias: str) -> Optional[dict]:
        """Respond to room alias queries (not used yet)."""
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_intent(self, mxid: str) -> IntentAPI:
        """Get IntentAPI for a virtual user."""
        if not self._appservice:
            raise RuntimeError("AppService not started")
        return self._appservice.intent.user(UserID(mxid))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "MatrixAppService":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()
