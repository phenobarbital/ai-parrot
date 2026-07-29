"""
VoiceChatHandler - WebSocket Handler with Authentication

Enhanced WebSocket handler for voice chat with:
- JWT authentication via Sec-WebSocket-Protocol (pre-connection)
- JWT authentication via message type (post-connection)
- Configurable route setup via setup_routes()
- Heartbeat/ping mechanism

This handler ONLY handles WebSocket transport.
It does NOT know about Google/Gemini - all voice logic
is encapsulated in VoiceBot/GeminiLiveClient.
"""
from __future__ import annotations
import asyncio
import base64
import contextlib
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
    Union,
)
from aiohttp import web, WSMsgType
from navconfig.logging import logging

if TYPE_CHECKING:
    # Type-check-only import — VoiceProvider itself has no optional runtime
    # dependencies, but this keeps the module-scope import list minimal and
    # matches the lazy-import style used for NovaClient/GeminiLiveClient
    # in resolve_voice_client_class() below.
    from parrot.voice.models import VoiceProvider

# Type hints for optional imports
try:
    from parrot.bots.voice import VoiceBot, create_voice_bot
    from parrot.models.voice import VoiceConfig
except ImportError:
    VoiceBot = Any
    VoiceConfig = Any
    create_voice_bot = None


# =============================================================================
# Authentication
# =============================================================================
# AuthenticatedUser and TokenValidator are shared WebSocket auth infrastructure
# and now live in the dependency-light parrot.core.ws_auth module, so any WS
# service can authenticate without pulling in the VoiceBot / Gemini Live stack.
# Re-exported here for backward compatibility.
from parrot.core.ws_auth import AuthenticatedUser, TokenValidator  # noqa: E402,F401


# =============================================================================
# Provider Resolution (FEAT-302, TASK-1749)
# =============================================================================
# VoiceChatHandler is transport-only (WebSocket) — voice-provider client
# construction has historically been hardcoded to GeminiLiveClient inside
# VoiceBot._resolve_llm_config() (parrot.bots.voice, core ai-parrot). This
# helper is additive: it lets callers resolve the AbstractClient subclass
# for a given VoiceProvider without requiring changes to VoiceBot's
# existing (GeminiLiveClient-only) resolution path. Full end-to-end
# provider-aware VoiceBot wiring is out of scope here — see spec Module 8.

def resolve_voice_client_class(provider: "VoiceProvider"):
    """Resolve the ``AbstractClient`` subclass for a given ``VoiceProvider``.

    Recognizes ``VoiceProvider.NOVA`` and returns
    :class:`~parrot.clients.nova.NovaClient` (lazily imported — the
    Pre-Alpha ``aws_sdk_bedrock_runtime`` extra is optional and is only
    required at first ``stream_voice()`` call, not at import time). Every
    other currently-declared provider resolves to
    :class:`~parrot.clients.live.GeminiLiveClient`, the only fully-wired
    voice client at this time (``OPENAI_REALTIME`` / ``WHISPER_TTS`` are
    declared in the enum but not yet backed by dedicated client classes).

    Args:
        provider: The ``VoiceProvider`` enum member to resolve.

    Returns:
        The ``AbstractClient`` subclass to instantiate for *provider*.

    Raises:
        ImportError: When ``NOVA`` is requested and
            ``aws_sdk_bedrock_runtime`` (Pre-Alpha, Python >= 3.12 only) is
            not installed and ``stream_voice()`` is called — importing
            :class:`NovaClient` itself never requires it.
    """
    from parrot.voice.models import VoiceProvider as _VoiceProvider

    if provider == _VoiceProvider.NOVA:
        from parrot.clients.nova import NovaClient
        return NovaClient

    from parrot.clients.live import GeminiLiveClient
    return GeminiLiveClient


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class BotConfig:
    """Configuration for VoiceBot creation."""
    name: str = "Voice Assistant"
    voice_name: str = "Puck"
    language: str = "en-US"
    system_prompt: Optional[str] = None
    tools: Optional[List[Any]] = None
    voice_config: Optional[VoiceConfig] = None

    # Additional client configuration
    api_key: Optional[str] = None
    vertexai: bool = False
    project: Optional[str] = None
    location: Optional[str] = None
    credentials_file: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        for key, value in asdict(self).items():
            if value is not None:
                result[key] = value
        return result

    def merge_with(self, overrides: Dict[str, Any]) -> 'BotConfig':
        """Create new BotConfig with overrides applied."""
        current = asdict(self)
        current.update(overrides)
        return BotConfig(**{k: v for k, v in current.items() if k in BotConfig.__dataclass_fields__})

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BotConfig':
        """Create BotConfig from dictionary."""
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


# =============================================================================
# Connection State
# =============================================================================

@dataclass
class WebSocketConnection:
    """Represents an active WebSocket connection with auth state."""
    ws: web.WebSocketResponse
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)

    # Authentication state
    authenticated: bool = False
    user: Optional[AuthenticatedUser] = None

    # Legacy user_id support (will use user.user_id if authenticated)
    _user_id: Optional[str] = None

    @property
    def user_id(self) -> Optional[str]:
        """Get user ID from authenticated user or legacy field."""
        if self.user:
            return self.user.user_id
        return self._user_id

    @user_id.setter
    def user_id(self, value: Optional[str]):
        self._user_id = value

    # Bot associated with this connection
    bot: Optional[VoiceBot] = None

    # Streaming mode configuration
    # "streaming" = real-time bidirectional (default)
    # "buffered" = collect complete audio, process, return complete response
    streaming_mode: str = "streaming"

    # Recording state
    is_recording: bool = False
    recording_start_time: Optional[datetime] = None
    session_active: bool = False
    stop_audio_sending: bool = False
    gemini_responding: bool = False

    # Audio buffer for non-streaming mode
    audio_buffer: bytes = b""

    # Audio queue for streaming mode
    audio_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # Voice session task
    voice_task: Optional[asyncio.Task] = None

    # Shutdown event
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Configuration
    config: Optional[BotConfig] = None

    # STT-only mode (FEAT-257): when True, Gemini transcribes input but does not
    # generate a model response.  response_chunk / model audio frames are suppressed.
    stt_only: bool = False

    # Ping tracking
    last_ping: Optional[datetime] = None
    ping_count: int = 0

    # Avatar session (FEAT-245): optional LiveAvatar LITE mouth driven by Gemini audio.
    # Type is Optional[Any] to avoid importing the liveavatar stack at module level
    # (lazy import so /ws/voice works without the ai-parrot-integrations[liveavatar] extra).
    avatar_session: Optional[Any] = None


# =============================================================================
# Main Handler
# =============================================================================

class VoiceChatHandler:
    """
    WebSocket handler for voice chat with authentication support.

    Features:
    - Pre-connection auth via Sec-WebSocket-Protocol header
    - Post-connection auth via 'auth' message type
    - Configurable route setup
    - Heartbeat/ping mechanism

    Authentication Methods:

    1. Sec-WebSocket-Protocol (recommended for browsers):
       ```javascript
       // Frontend
       const ws = new WebSocket(url, ["jwt", token]);
       ```

    2. Query parameter:
       ```javascript
       const ws = new WebSocket(`${url}?token=${token}`);
       ```

    3. Post-connection message:
       ```javascript
       ws.send(JSON.stringify({type: "auth", token: "..."}));
       ```

    Usage:
        handler = VoiceChatHandler(
            bot_factory=lambda: create_voice_bot(name="Assistant"),
            require_auth=True,
        )

        # Option 1: Setup routes
        handler.setup_routes(app, prefix="/api/v1")

        # Option 2: Direct route
        app.router.add_get('/ws/voice', handler.handle_websocket)
    """

    def __init__(
        self,
        bot_factory: Optional[Callable[[], VoiceBot]] = None,
        default_config: Optional[Union[BotConfig, Dict[str, Any]]] = None,
        *,
        # Authentication options
        require_auth: bool = False,
        token_validator: Optional[TokenValidator] = None,
        secret_key: Optional[str] = None,
        auth_timeout: float = 30.0,
        # Route options
        ws_route: str = "/ws/voice",
        health_route: str = "/health",
    ):
        """
        Initialize handler.

        Args:
            bot_factory: Factory for creating VoiceBot instances
            default_config: Default bot configuration
            require_auth: Require authentication before session start
            token_validator: Custom token validator
            secret_key: JWT secret key (if not using navigator_auth)
            auth_timeout: Timeout for post-connection auth (seconds)
            ws_route: WebSocket route path
            health_route: Health check route path
        """
        self.bot_factory = bot_factory or self._default_bot_factory

        if isinstance(default_config, BotConfig):
            self.default_config = default_config
        elif isinstance(default_config, dict):
            self.default_config = BotConfig.from_dict(default_config)
        else:
            self.default_config = BotConfig()

        self._current_config: Optional[BotConfig] = None
        self.connections: Dict[str, WebSocketConnection] = {}

        # Authentication
        self.require_auth = require_auth
        self.token_validator = token_validator or TokenValidator(
            secret_key=secret_key,
            allow_anonymous=not require_auth,
        )
        self.auth_timeout = auth_timeout

        # Routes
        self.ws_route = ws_route
        self.health_route = health_route

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _default_bot_factory(self) -> VoiceBot:
        """Default factory for bots."""
        config = self._current_config or self.default_config
        if create_voice_bot is None:
            raise ImportError("VoiceBot not available")
        return create_voice_bot(**config.as_dict())

    @staticmethod
    def resolve_provider_client(provider: "VoiceProvider"):
        """Resolve the ``AbstractClient`` subclass for *provider* (FEAT-302).

        Thin wrapper around the module-level
        :func:`resolve_voice_client_class` — recognizes
        ``VoiceProvider.NOVA`` and returns
        :class:`~parrot.clients.nova.NovaClient`.
        """
        return resolve_voice_client_class(provider)

    # =========================================================================
    # Route Setup
    # =========================================================================

    def setup_routes(
        self,
        app: web.Application,
        prefix: str = "",
        *,
        include_health: bool = True,
        include_static: bool = True,
        static_dir: Optional[str] = None,
    ) -> None:
        """
        Register routes on an aiohttp application.

        Args:
            app: aiohttp Application
            prefix: URL prefix for all routes (e.g., "/api/v1")
            include_health: Include health check endpoint
            include_static: Include static file serving
            static_dir: Directory for static files
        """
        # Normalize prefix
        prefix = prefix.rstrip("/")

        # WebSocket route
        ws_path = f"{prefix}{self.ws_route}"
        app.router.add_get(ws_path, self.handle_websocket)
        self.logger.info("WebSocket route registered: %s", ws_path)

        # Health check
        if include_health:
            health_path = f"{prefix}{self.health_route}"
            app.router.add_get(health_path, self._handle_health)
            self.logger.info("Health route registered: %s", health_path)

        # Static files
        if include_static and static_dir:
            from pathlib import Path
            static_path = Path(static_dir)
            if static_path.exists():
                app.router.add_static(f"{prefix}/static", static_path)
                self.logger.info("Static route registered: %s/static", prefix)

        # Store reference in app
        app["voice_handler"] = self

        # Cleanup on shutdown
        app.on_cleanup.append(self._cleanup_all_connections)

        self.logger.info(
            f"VoiceChatHandler mounted at {prefix or '/'} "
            f"(auth={'required' if self.require_auth else 'optional'})"
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "active_connections": len(self.connections),
            "authenticated_connections": sum(
                1 for c in self.connections.values() if c.authenticated
            ),
            "timestamp": datetime.now().isoformat(),
        })

    async def _cleanup_all_connections(self, app: web.Application) -> None:
        """Cleanup all connections on app shutdown."""
        for connection in list(self.connections.values()):
            await self._cleanup_connection(connection)

    # =========================================================================
    # Authentication
    # =========================================================================

    async def _authenticate_from_protocol(
        self,
        request: web.Request
    ) -> tuple[Optional[str], Optional[AuthenticatedUser]]:
        """
        Extract and validate JWT from Sec-WebSocket-Protocol header.

        The browser sends: new WebSocket(url, ["jwt", token])
        Header received: Sec-WebSocket-Protocol: jwt, <token>

        Returns:
            Tuple of (selected_protocol, authenticated_user)
        """
        protocol_header = request.headers.get("Sec-WebSocket-Protocol")
        if not protocol_header:
            return None, None

        parts = [p.strip() for p in protocol_header.split(",")]

        # Check if using JWT protocol
        if "jwt" not in parts:
            return None, None

        # Find token (the part that isn't 'jwt')
        parts_copy = parts.copy()
        parts_copy.remove("jwt")

        if not parts_copy:
            return None, None

        token = parts_copy[0]
        user = await self.token_validator.validate(token)

        if user:
            return "jwt", user
        return None, None

    async def _authenticate_from_query(
        self,
        request: web.Request
    ) -> Optional[AuthenticatedUser]:
        """Extract and validate JWT from query parameter."""
        token = request.query.get("token")
        if token:
            return await self.token_validator.validate(token)
        return None

    # =========================================================================
    # WebSocket Handler
    # =========================================================================

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Main WebSocket handler.

        Protocol:

        Client -> Server:
        - {"type": "auth", "token": "<jwt>"}
        - {"type": "start_session", "config": {...}}
        - {"type": "audio_data", "data": "<base64>"}
        - {"type": "start_recording"}
        - {"type": "stop_recording"}
        - {"type": "send_text", "text": "..."}
        - {"type": "end_session"}
        - {"type": "ping"}

        Server -> Client:
        - {"type": "connected", "session_id": "...", "authenticated": bool}
        - {"type": "auth_success", "user": {...}}
        - {"type": "auth_error", "message": "..."}
        - {"type": "session_started", "session_id": "..."}
        - {"type": "voice_response", ...}
        - {"type": "pong", "timestamp": "...", "ping_count": N}
        - {"type": "error", "message": "..."}
        """
        # Try pre-connection authentication
        selected_protocol, pre_auth_user = await self._authenticate_from_protocol(request)

        # Also try query param auth
        if not pre_auth_user:
            pre_auth_user = await self._authenticate_from_query(request)

        # Prepare WebSocket response
        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024,  # 10MB for audio
            protocols=[selected_protocol] if selected_protocol else None,
        )
        await ws.prepare(request)

        session_id = str(uuid.uuid4())

        connection = WebSocketConnection(
            ws=ws,
            session_id=session_id,
            authenticated=pre_auth_user is not None,
            user=pre_auth_user,
            _user_id=request.query.get("user_id"),
        )
        self.connections[session_id] = connection

        self.logger.info(
            f"New WebSocket connection: {session_id} "
            f"(authenticated={connection.authenticated})"
        )

        try:
            # Send connection confirmation
            await self._send_message(ws, {
                "type": "connected",
                "session_id": session_id,
                "authenticated": connection.authenticated,
                "require_auth": self.require_auth and not connection.authenticated,
            })

            # If pre-authenticated, send success
            if connection.authenticated and connection.user:
                await self._send_message(ws, {
                    "type": "auth_success",
                    "user": {
                        "user_id": connection.user.user_id,
                        "username": connection.user.username,
                    }
                })

            # Process messages
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_message(connection, data)
                    except json.JSONDecodeError:
                        await self._send_error(ws, "Invalid JSON")
                    except Exception as e:
                        self.logger.error("Error handling message: %s", e)
                        await self._send_error(ws, str(e))

                elif msg.type == WSMsgType.BINARY:
                    # Direct binary audio
                    if not connection.is_recording:
                        connection.stop_audio_sending = False
                        connection.gemini_responding = False
                        connection.recording_start_time = datetime.now()
                        connection.audio_buffer = b""  # Reset buffer
                    connection.is_recording = True

                    if connection.session_active and not connection.stop_audio_sending:
                        if connection.streaming_mode == "streaming":
                            # Streaming mode: send to queue immediately
                            await connection.audio_queue.put(msg.data)
                        else:
                            # Buffered mode: accumulate audio
                            connection.audio_buffer += msg.data

                elif msg.type == WSMsgType.ERROR:
                    self.logger.error("WebSocket error: %s", ws.exception())

        except asyncio.CancelledError:
            self.logger.info("Connection cancelled: %s", session_id)

        finally:
            await self._cleanup_connection(connection)
            self.connections.pop(session_id, None)
            self.logger.info("Connection closed: %s", session_id)

        return ws

    # =========================================================================
    # Message Handlers
    # =========================================================================

    async def _handle_message(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Route message to appropriate handler."""
        msg_type = message.get("type", "")

        # Auth can always be handled
        if msg_type == "auth":
            await self._handle_auth(connection, message)
            return

        # Ping can always be handled
        if msg_type == "ping":
            await self._handle_ping(connection, message)
            return

        # Check authentication for other message types
        if self.require_auth and not connection.authenticated:
            await self._send_message(connection.ws, {
                "type": "auth_required",
                "message": "Authentication required. Send {type: 'auth', token: '...'}"
            })
            return

        handlers = {
            "start_session": self._handle_start_session,
            "end_session": self._handle_end_session,
            "reset_session": self._handle_reset_session,
            "start_recording": self._handle_start_recording,
            "stop_recording": self._handle_stop_recording,
            "audio_data": self._handle_audio_data,
            "audio_chunk": self._handle_audio_data,
            "send_text": self._handle_send_text,
            "text_message": self._handle_send_text,
            "voice_complete": self._handle_voice_complete,  # Non-streaming voice
            "voice_buffer": self._handle_voice_complete,    # Alias
        }

        if handler := handlers.get(msg_type):
            await handler(connection, message)
        else:
            self.logger.warning("Unknown message type: %s", msg_type)

    async def _handle_auth(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Handle authentication message.

        Expected message format:
        {
            "type": "auth",
            "token": "<jwt_token>"
        }

        Or with authorization header format:
        {
            "type": "auth",
            "authorization": "Bearer <jwt_token>"
        }
        """
        # Extract token from message
        token = message.get("token")

        if not token:
            # Try authorization header format
            auth_header = message.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            await self._send_message(connection.ws, {
                "type": "auth_error",
                "message": "Token not provided",
            })
            return

        # Validate token
        user = await self.token_validator.validate(token)

        if user:
            connection.authenticated = True
            connection.user = user

            await self._send_message(connection.ws, {
                "type": "auth_success",
                "message": "Authentication successful",
                "user": {
                    "user_id": user.user_id,
                    "username": user.username,
                },
            })

            self.logger.info(
                f"Session {connection.session_id} authenticated as {user.username}"
            )
        else:
            await self._send_message(connection.ws, {
                "type": "auth_error",
                "message": "Invalid or expired token",
            })

            self.logger.warning(
                f"Session {connection.session_id} authentication failed"
            )

    async def _handle_ping(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Handle ping message for connection keepalive.

        Request:
        {
            "type": "ping",
            "timestamp": "2025-01-14T12:00:00Z"  // optional client timestamp
        }

        Response:
        {
            "type": "pong",
            "timestamp": "2025-01-14T12:00:01Z",
            "client_timestamp": "2025-01-14T12:00:00Z",  // echoed if provided
            "ping_count": 42,
            "session_id": "...",
            "authenticated": true,
            "session_active": false
        }
        """
        connection.last_ping = datetime.now()
        connection.ping_count += 1

        response = {
            "type": "pong",
            "timestamp": datetime.now().isoformat(),
            "ping_count": connection.ping_count,
            "session_id": connection.session_id,
            "authenticated": connection.authenticated,
            "session_active": connection.session_active,
        }

        # Echo client timestamp if provided
        if client_ts := message.get("timestamp"):
            response["client_timestamp"] = client_ts

        await self._send_message(connection.ws, response)

    async def _handle_start_session(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Start voice session.

        Message format:
        {
            "type": "start_session",
            "config": {
                "voice_name": "Puck",
                "language": "en-US",
                "system_prompt": "...",
                ...
            },
            "streaming_mode": "streaming"  // or "buffered"
        }

        Streaming modes:
        - "streaming" (default): Real-time bidirectional audio streaming.
          Audio chunks are sent immediately to the model and responses
          stream back in real-time. Best for conversational voice.

        - "buffered": Collect complete audio, process once, return complete
          response. Useful when client prefers to record complete audio
          first (e.g., mobile apps with push-to-talk).
        """
        # Merge default config with client-provided config
        client_config = message.get("config", {})
        config = self.default_config.merge_with(client_config)
        connection.config = config

        # Set streaming mode
        streaming_mode = message.get("streaming_mode", "streaming")
        if streaming_mode not in ("streaming", "buffered"):
            streaming_mode = "streaming"
        connection.streaming_mode = streaming_mode

        # STT-only mode (FEAT-257): parse from start_session payload.
        # Default False → full-duplex (existing behavior unchanged).
        stt_only_raw = message.get("stt_only", False)
        connection.stt_only = bool(stt_only_raw)
        if connection.stt_only:
            self.logger.info(
                "VoiceChatHandler: STT-only mode enabled for session %s",
                connection.session_id,
            )

        # Clear audio buffer for buffered mode
        connection.audio_buffer = b""

        # Store config for factory
        self._current_config = config
        connection.bot = self.bot_factory()

        # The bot factory builds the VoiceBot but does NOT run the async
        # configure() flow, so conversation_memory is never set up — which
        # means ask_stream() silently skips loading/saving turns and every
        # turn starts with no memory of the previous one (Gemini Live Mode
        # had no conversational continuity).  Configure memory here, best-
        # effort: Redis for cross-turn persistence within the session, with
        # the built-in in-memory fallback if Redis is unavailable.  Keyed by
        # connection.session_id, so turns accumulate across the session and
        # survive a GoAway reconnect.
        try:
            if getattr(connection.bot, "conversation_memory", None) is None:
                if not getattr(connection.bot, "memory_type", None) or \
                        connection.bot.memory_type == "memory":
                    connection.bot.memory_type = "redis"
                connection.bot.configure_conversation_memory()
        except Exception:  # noqa: BLE001 - memory is best-effort, never block voice
            self.logger.warning(
                "VoiceChatHandler: could not configure conversation memory "
                "for session %s; continuing without cross-turn memory.",
                connection.session_id, exc_info=True,
            )

        # Start voice task only for streaming mode
        connection.shutdown_event.clear()
        connection.session_active = True
        connection.stop_audio_sending = False

        if streaming_mode == "streaming":
            connection.voice_task = asyncio.create_task(
                self._run_voice_session(connection)
            )

        # ── Avatar wiring (FEAT-245) ──────────────────────────────────────
        # Lazy-import the liveavatar stack so /ws/voice works without the
        # optional ai-parrot-integrations[liveavatar] extra.  All avatar
        # exceptions are caught and surfaced as avatar.active=false in the
        # session_started reply (graceful degradation — voice still starts).
        avatar_block: dict = {}
        avatar_requested = bool(message.get("avatar", False))
        if avatar_requested:
            try:
                from parrot.integrations.liveavatar import VoiceAvatarSession
                from parrot.integrations.liveavatar.optin import is_avatar_enabled

                tenant_id: Optional[str] = message.get("tenant_id") or None
                avatar_id_override: Optional[str] = message.get("avatar_id") or None
                agent_id: str = (
                    config.name
                    if config and config.name
                    else "voice-assistant"
                )

                if not is_avatar_enabled(
                    tenant_id=tenant_id, agent_name=agent_id
                ):
                    avatar_block = {
                        "active": False,
                        "reason": "avatar mode is not enabled for this tenant",
                    }
                    self.logger.info(
                        "VoiceChatHandler: avatar opt-in denied for tenant=%s agent=%s",
                        tenant_id,
                        agent_id,
                    )
                else:
                    session: "VoiceAvatarSession" = await VoiceAvatarSession.start(
                        agent_id=agent_id,
                        session_id=connection.session_id,
                        tenant_id=tenant_id,
                        avatar_id=avatar_id_override,
                    )
                    connection.avatar_session = session
                    avatar_block = {
                        "active": True,
                        **session.viewer_credentials,
                        "audio": "dual",
                    }
                    self.logger.info(
                        "VoiceChatHandler: avatar session started for session=%s",
                        connection.session_id,
                    )
            except ImportError as exc:
                avatar_block = {"active": False, "reason": "liveavatar stack not installed"}
                self.logger.warning(
                    "VoiceChatHandler: liveavatar import failed — voice-only: %s", exc
                )
            except Exception as exc:  # noqa: BLE001
                avatar_block = {"active": False, "reason": str(exc)[:120]}
                self.logger.warning(
                    "VoiceChatHandler: avatar start failed — voice-only: %s", exc
                )

        session_started_msg: dict = {
            "type": "session_started",
            "session_id": connection.session_id,
            "user_id": connection.user_id,
            "streaming_mode": streaming_mode,
            "stt_only": connection.stt_only,
            "config": {
                "voice_name": config.voice_name,
                "language": config.language,
                "input_format": "audio/pcm;rate=16000",
                "output_format": "audio/pcm;rate=24000",
            },
        }
        if avatar_block:
            session_started_msg["avatar"] = avatar_block

        await self._send_message(connection.ws, session_started_msg)

        await self._send_message(connection.ws, {
            "type": "ready_to_speak",
            "message": "Ready for your question"
        })

        self.logger.info(
            "Voice session started: %s (mode=%s)",
            connection.session_id,
            streaming_mode,
        )

    async def _handle_end_session(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """End voice session."""
        connection.shutdown_event.set()
        connection.session_active = False
        connection.stop_audio_sending = True

        if connection.voice_task:
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

        if connection.bot:
            await connection.bot.close()
            connection.bot = None

        # Tear down avatar session — mirrors _cleanup_connection so that an
        # explicit end_session from the client does not orphan the LiveAvatar WS.
        if connection.avatar_session is not None:
            with contextlib.suppress(Exception):
                await connection.avatar_session.aclose()
            connection.avatar_session = None

        await self._send_message(connection.ws, {
            "type": "session_ended",
            "session_id": connection.session_id,
        })

        self.logger.info("Voice session ended: %s", connection.session_id)

    async def _handle_reset_session(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Reset session - end current and start new."""
        await self._handle_end_session(connection, message)

        # Clear audio queue
        while not connection.audio_queue.empty():
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Start new session with same config
        await self._handle_start_session(connection, {
            "config": connection.config.as_dict() if connection.config else {}
        })

        self.logger.info("Voice session reset: %s", connection.session_id)

    async def _handle_start_recording(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Start audio recording."""
        connection.stop_audio_sending = False
        connection.gemini_responding = False
        connection.is_recording = True
        connection.recording_start_time = datetime.now()

        await self._send_message(connection.ws, {
            "type": "recording_started",
        })

    async def _handle_stop_recording(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Stop audio recording.

        In streaming mode: signals end of audio stream.
        In buffered mode: triggers processing of accumulated audio via ask_voice.
        """
        connection.is_recording = False
        connection.stop_audio_sending = True

        MIN_DURATION_MS = 500
        duration_ms = 0

        if connection.recording_start_time:
            duration_ms = (
                datetime.now() - connection.recording_start_time
            ).total_seconds() * 1000
            connection.recording_start_time = None

            if duration_ms < MIN_DURATION_MS:
                self.logger.info(
                    f"Recording too short ({duration_ms:.0f}ms), ignoring"
                )
                # Clear audio
                while not connection.audio_queue.empty():
                    try:
                        connection.audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                connection.audio_buffer = b""

                await self._send_message(connection.ws, {
                    "type": "recording_stopped",
                    "message": "Recording too short. Please hold longer."
                })
                return

        await self._send_message(connection.ws, {
            "type": "recording_stopped",
            "message": "Processing...",
            "duration_ms": duration_ms,
        })

        # In buffered mode, process the accumulated audio now
        if connection.streaming_mode == "buffered" and connection.audio_buffer:
            await self._handle_voice_binary_complete(
                connection,
                connection.audio_buffer
            )
            connection.audio_buffer = b""

    async def _handle_audio_data(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Receive audio chunk (base64).

        In streaming mode: queues audio for immediate processing.
        In buffered mode: accumulates audio for later processing.
        """
        if not connection.is_recording:
            connection.stop_audio_sending = False
            connection.gemini_responding = False
            connection.recording_start_time = datetime.now()
            connection.audio_buffer = b""

        connection.is_recording = True

        if not connection.session_active or connection.stop_audio_sending:
            return

        if audio_b64 := message.get("data", ""):
            audio_bytes = base64.b64decode(audio_b64)

            if connection.streaming_mode == "streaming":
                await connection.audio_queue.put(audio_bytes)
            else:
                # Buffered mode
                connection.audio_buffer += audio_bytes

    async def _handle_send_text(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Send text to bot and receive voice response (text-to-speech).

        Uses VoiceBot.ask() which converts text to speech.

        Message format:
        {
            "type": "send_text",
            "text": "Hello, how are you?",
            "streaming": true  // optional, default true
        }
        """
        text = message.get("text", "")
        if not text or not connection.bot:
            return

        streaming = message.get("streaming", True)

        try:
            if streaming:
                # Streaming mode - send chunks as they arrive
                async for response in connection.bot.ask(
                    question=text,
                    session_id=connection.session_id,
                    user_id=connection.user_id,
                ):
                    await self._send_voice_response(connection, response)
            else:
                # Non-streaming mode - accumulate and send complete response
                full_text = ""
                full_audio = b""
                tool_calls = []

                async for response in connection.bot.ask(
                    question=text,
                    session_id=connection.session_id,
                    user_id=connection.user_id,
                ):
                    if response.text:
                        full_text += response.text
                    if response.audio_data:
                        full_audio += response.audio_data
                    if response.tool_calls:
                        tool_calls.extend(response.tool_calls)

                # Send complete response
                await self._send_complete_voice_response(
                    connection,
                    text=full_text,
                    audio_data=full_audio,
                    tool_calls=tool_calls,
                )

        except Exception as e:
            self.logger.error("Error processing text: %s", e)
            await self._send_error(connection.ws, str(e))

    async def _handle_voice_complete(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """
        Handle complete audio buffer for non-streaming voice processing.

        Uses VoiceBot.ask_voice() which processes complete audio and returns
        complete response (no streaming).

        This is useful when:
        - Client wants to send complete audio at once
        - Client prefers complete response over streaming
        - Lower latency is less important than simplicity

        Message format:
        {
            "type": "voice_complete",
            "audio_base64": "<complete audio buffer in base64>",
            "audio_format": "audio/pcm;rate=16000"  // optional
        }

        Response:
        {
            "type": "voice_response",
            "text": "transcribed and response text",
            "audio_base64": "<complete response audio>",
            "audio_format": "audio/pcm;rate=24000",
            "tool_calls": [...],
            "usage": {...}
        }
        """
        if not connection.bot:
            await self._send_error(connection.ws, "Session not started")
            return

        audio_b64 = message.get("audio_base64", "") or message.get("data", "")
        if not audio_b64:
            await self._send_error(connection.ws, "No audio data provided")
            return

        try:
            # Decode audio
            audio_bytes = base64.b64decode(audio_b64)

            self.logger.info(
                f"Processing complete audio: {len(audio_bytes)} bytes "
                f"for session {connection.session_id}"
            )

            # Notify client we're processing
            await self._send_message(connection.ws, {
                "type": "processing",
                "message": "Processing audio...",
                "audio_size": len(audio_bytes),
            })

            # Use non-streaming ask_voice
            response = await connection.bot.ask_voice(
                audio_input=audio_bytes,
                session_id=connection.session_id,
                user_id=connection.user_id,
            )

            # Send complete response
            await self._send_complete_voice_response(
                connection,
                text=response.text,
                audio_data=response.audio_data,
                tool_calls=response.tool_calls,
                usage=response.usage,
                metadata=response.metadata,
            )

        except Exception as e:
            self.logger.error("Error processing voice: %s", e)
            await self._send_error(connection.ws, str(e))

    async def _handle_voice_binary_complete(
        self,
        connection: WebSocketConnection,
        audio_bytes: bytes
    ) -> None:
        """
        Handle complete binary audio for non-streaming processing.

        Called when connection is in non-streaming mode and receives
        complete binary audio data.
        """
        if not connection.bot:
            return

        try:
            self.logger.info(
                f"Processing binary audio: {len(audio_bytes)} bytes"
            )

            await self._send_message(connection.ws, {
                "type": "processing",
                "message": "Processing audio...",
            })

            response = await connection.bot.ask_voice(
                audio_input=audio_bytes,
                session_id=connection.session_id,
                user_id=connection.user_id,
            )

            await self._send_complete_voice_response(
                connection,
                text=response.text,
                audio_data=response.audio_data,
                tool_calls=response.tool_calls,
                usage=response.usage,
                metadata=response.metadata,
            )

        except Exception as e:
            self.logger.error("Error processing binary voice: %s", e)
            await self._send_error(connection.ws, str(e))

    async def _send_complete_voice_response(
        self,
        connection: WebSocketConnection,
        text: str = "",
        audio_data: Optional[bytes] = None,
        tool_calls: Optional[List[Any]] = None,
        usage: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send complete voice response (non-streaming).

        Used by ask_voice and non-streaming text-to-speech.
        """
        metadata = metadata or {}

        # Send user transcription if available
        if metadata.get("user_transcription"):
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": metadata["user_transcription"],
                "is_user": True,
            })

        # Send tool calls
        for tc in (tool_calls or []):
            await self._send_message(connection.ws, {
                "type": "tool_call",
                "name": tc.name,
                "arguments": tc.arguments,
                "result": tc.result,
                "execution_time_ms": getattr(tc, "execution_time_ms", None),
            })

        # Send complete response
        response_msg = {
            "type": "voice_response",
            "text": text,
            "audio_base64": base64.b64encode(audio_data).decode() if audio_data else "",
            "audio_format": "audio/pcm;rate=24000",
            "is_complete": True,
        }

        if usage:
            response_msg["usage"] = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
                "total_tokens": getattr(usage, "total_tokens", 0),
                "audio_duration_ms": getattr(usage, "audio_duration_ms", 0),
            }

        await self._send_message(connection.ws, response_msg)

        # Signal ready for next input
        await self._send_message(connection.ws, {
            "type": "ready_to_speak",
            "message": "Ready for new question"
        })

    # =========================================================================
    # Voice Session
    # =========================================================================

    async def _run_voice_session(self, connection: WebSocketConnection) -> None:
        """Run voice session with audio streaming."""
        if not connection.bot:
            return

        async def audio_from_queue():
            """Generator that reads audio from queue."""
            audio_ended_sent = False

            while not connection.shutdown_event.is_set():
                try:
                    chunk = await asyncio.wait_for(
                        connection.audio_queue.get(),
                        timeout=0.5
                    )
                    audio_ended_sent = False
                    yield chunk
                except asyncio.TimeoutError:
                    if connection.stop_audio_sending and connection.audio_queue.empty():
                        if not audio_ended_sent:
                            yield None
                            audio_ended_sent = True
                    continue
                except asyncio.CancelledError:
                    break

        while not connection.shutdown_event.is_set():
            try:
                async for response in connection.bot.ask_stream(
                    audio_input=audio_from_queue(),
                    session_id=connection.session_id,
                    user_id=connection.user_id,
                    stt_only=connection.stt_only,
                ):
                    await self._send_voice_response(connection, response)

                    if response.metadata.get("go_away"):
                        await self._send_message(connection.ws, {
                            "type": "session_warning",
                            "message": "Session reconnecting...",
                        })
                        break

                    if connection.shutdown_event.is_set():
                        return

            except asyncio.CancelledError:
                return
            except Exception as e:
                self.logger.error("Voice session error: %s", e)
                await self._send_error(connection.ws, str(e))
                await asyncio.sleep(1)

    async def _send_voice_response(
        self,
        connection: WebSocketConnection,
        response: Any
    ) -> None:
        """Send voice response to client.

        In STT-only mode (connection.stt_only=True) only ``transcription``
        frames (is_user=True) are forwarded; ``response_chunk`` and model
        audio frames are suppressed (double-brain guard).
        """
        # STT-only: skip all model response frames — only transcription is allowed.
        if not connection.stt_only:
            # Send response_chunk for audio OR text (not just audio)
            # FILTER: Skip internal thought processes that leak into output
            # Generic pattern:
            # 1. Bold/Header followed by a Gerund (Verb-ing) -> **Clarifying...**
            # 2. Bold/Header followed by "Show [Capital]" -> **Show Product Image**
            is_thought = response.text and re.match(
                r'^\s*(?:(\*\*|##)?\s*[A-Z][a-z]+ing\b|(\*\*|##)\s*Show\s+[A-Z])',
                response.text
            )

            # Determine strict text to send (suppress if thought)
            text_to_send = response.text
            if is_thought:
                text_to_send = ""

            if (response.audio_data or text_to_send) and not response.is_complete:
                await self._send_message(connection.ws, {
                    "type": "response_chunk",
                    "text": text_to_send or "",
                    "audio_base64": base64.b64encode(response.audio_data).decode() if response.audio_data else "",
                    "audio_format": "audio/pcm;rate=24000" if response.audio_data else "",
                    "is_interrupted": response.is_interrupted,
                })

        # User transcription is always forwarded (both modes).
        if response.metadata.get("user_transcription"):
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": response.metadata["user_transcription"],
                "is_user": True,
            })

        # Everything below this point is model-response output — skip in STT-only.
        if connection.stt_only:
            return

        # Forward the assistant's SPOKEN transcription (output_transcription) as
        # the display text. In audio mode Gemini's model_turn TEXT modality is
        # generated separately from the audio — it diverges from what's actually
        # spoken (and leaks "thinking" headers), so the transcription is the
        # source of truth for the bubble. The front shows this and ignores the
        # response_chunk text (audio only).
        assistant_text = response.metadata.get("assistant_transcription")
        if not assistant_text and response.turn_metadata:
            assistant_text = response.turn_metadata.output_transcription
        if assistant_text:
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": assistant_text,
                "is_user": False,
            })

        if response.metadata.get("display_data"):
            await self._send_message(connection.ws, {
                "type": "display_data",
                "data": response.metadata["display_data"]
            })

        for tc in response.tool_calls:
            await self._send_message(connection.ws, {
                "type": "tool_call",
                "name": tc.name,
                "arguments": tc.arguments,
                "result": tc.result,
                "execution_time_ms": tc.execution_time_ms,
            })

        if response.is_complete:
            # Re-check filter for the final text payload
            final_text = response.text
            if final_text and re.match(r'^\s*(?:(\*\*|##)?\s*[A-Z][a-z]+ing\b|(\*\*|##)\s*Show\s+[A-Z])', final_text):
                final_text = ""

            await self._send_message(connection.ws, {
                "type": "response_complete",
                "text": final_text or "",
                "is_interrupted": response.is_interrupted,
            })

            await self._send_message(connection.ws, {
                "type": "ready_to_speak",
                "message": "Ready for new question"
            })

        # ── Avatar audio tee (FEAT-245) ───────────────────────────────────
        # Best-effort: exceptions are caught and logged; the browser audio
        # path MUST NOT be interrupted by an avatar hiccup (dual audio).
        if connection.avatar_session is not None:
            try:
                if response.is_interrupted:
                    await connection.avatar_session.interrupt()
                else:
                    if response.audio_data:
                        await connection.avatar_session.speak(response.audio_data)
                    if response.is_complete:
                        await connection.avatar_session.finish_turn()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "VoiceChatHandler: avatar tee error (voice stream unaffected): %s", exc
                )

    # =========================================================================
    # Utilities
    # =========================================================================

    async def _send_message(
        self,
        ws: web.WebSocketResponse,
        message: Dict[str, Any]
    ) -> None:
        """Send JSON message to client."""
        try:
            await ws.send_json(message)
        except Exception as e:
            self.logger.error("Error sending message: %s", e)

    async def _send_error(
        self,
        ws: web.WebSocketResponse,
        error_message: str
    ) -> None:
        """Send error message to client."""
        await self._send_message(ws, {
            "type": "error",
            "message": error_message,
            "timestamp": datetime.now().isoformat(),
        })

    async def _cleanup_connection(self, connection: WebSocketConnection) -> None:
        """Clean up connection resources."""
        connection.shutdown_event.set()

        if connection.voice_task:
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

        if connection.bot:
            await connection.bot.close()

        # Clear audio queue
        while not connection.audio_queue.empty():
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Clear audio buffer
        connection.audio_buffer = b""

        # Tear down avatar session (FEAT-245) — idempotent, never raises
        if connection.avatar_session is not None:
            try:
                await connection.avatar_session.aclose()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "VoiceChatHandler: avatar session cleanup error: %s", exc
                )
            finally:
                connection.avatar_session = None

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Send message to all active connections."""
        for connection in self.connections.values():
            await self._send_message(connection.ws, message)

    @property
    def active_connections(self) -> int:
        """Number of active connections."""
        return len(self.connections)


# =============================================================================
# Factory Function
# =============================================================================

def create_voice_server(
    bot_factory: Optional[Callable[[], VoiceBot]] = None,
    bot_config: Optional[Union[BotConfig, Dict[str, Any]]] = None,
    *,
    require_auth: bool = False,
    secret_key: Optional[str] = None,
    static_dir: Optional[str] = None,
    **kwargs
) -> web.Application:
    """
    Create complete voice server application.

    Args:
        bot_factory: Custom bot factory
        bot_config: Default bot configuration
        require_auth: Require JWT authentication
        secret_key: JWT secret key
        static_dir: Static files directory
        **kwargs: Additional handler arguments

    Returns:
        Configured aiohttp Application
    """
    handler = VoiceChatHandler(
        bot_factory=bot_factory,
        default_config=bot_config,
        require_auth=require_auth,
        secret_key=secret_key,
        **kwargs
    )

    app = web.Application()

    # Setup routes
    handler.setup_routes(
        app,
        include_static=static_dir is not None,
        static_dir=static_dir,
    )

    # Serve index if static dir exists
    if static_dir:
        from pathlib import Path
        frontend_dir = Path(static_dir)
        if (frontend_dir / "chat.html").exists():
            async def index(request):
                return web.FileResponse(frontend_dir / "chat.html")
            app.router.add_get("/", index)

    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)

        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-User-Id"
        return response

    app.middlewares.append(cors_middleware)

    return app


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Voice Chat WebSocket Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    parser.add_argument("--voice", default="Puck", help="Default voice name")
    parser.add_argument("--require-auth", action="store_true", help="Require authentication")
    parser.add_argument("--secret-key", help="JWT secret key")
    args = parser.parse_args()

    app = create_voice_server(
        bot_config=BotConfig(
            voice_name=args.voice,
            system_prompt="You are a helpful voice assistant.",
        ),
        require_auth=args.require_auth,
        secret_key=args.secret_key,
    )

    print(f"Starting voice server on {args.host}:{args.port}")
    print(f"Authentication: {'required' if args.require_auth else 'optional'}")
    web.run_app(app, host=args.host, port=args.port)