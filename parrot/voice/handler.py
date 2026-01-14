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
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)
from aiohttp import web, WSMsgType
from navconfig.logging import logging

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

@dataclass
class AuthenticatedUser:
    """Represents an authenticated user from JWT token."""
    user_id: str
    username: str
    email: str = ""
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class TokenValidator:
    """
    JWT Token validator.

    Supports multiple validation backends:
    - navigator_auth (production)
    - Custom validator function
    - Fallback for testing
    """

    def __init__(
        self,
        *,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        validator_func: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        allow_anonymous: bool = False,
    ):
        """
        Initialize token validator.

        Args:
            secret_key: JWT secret key (if not using navigator_auth)
            algorithm: JWT algorithm (default HS256)
            validator_func: Custom async validator function
            allow_anonymous: Allow connections without authentication
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.validator_func = validator_func
        self.allow_anonymous = allow_anonymous
        self.logger = logging.getLogger(f"{__name__}.TokenValidator")

    async def validate(self, token: str) -> Optional[AuthenticatedUser]:
        """
        Validate JWT token and return user info.

        Args:
            token: JWT bearer token

        Returns:
            AuthenticatedUser if valid, None otherwise
        """
        if not token:
            return None

        # Try custom validator first
        if self.validator_func:
            try:
                if asyncio.iscoroutinefunction(self.validator_func):
                    result = await self.validator_func(token)
                else:
                    result = self.validator_func(token)

                if result:
                    return AuthenticatedUser(
                        user_id=result.get('user_id', result.get('sub', '')),
                        username=result.get('username', result.get('preferred_username', 'user')),
                        email=result.get('email', ''),
                        roles=result.get('roles', []),
                        permissions=result.get('permissions', []),
                        raw_payload=result,
                    )
            except Exception as e:
                self.logger.warning(f"Custom validator error: {e}")
                return None

        # Try navigator_auth
        try:
            from navigator_auth.conf import SECRET_KEY, AUTH_JWT_ALGORITHM
            import jwt

            payload = jwt.decode(
                token,
                SECRET_KEY,
                algorithms=[AUTH_JWT_ALGORITHM]
            )
            return AuthenticatedUser(
                user_id=payload.get('user_id', payload.get('sub', '')),
                username=payload.get('username', payload.get('preferred_username', 'user')),
                email=payload.get('email', ''),
                roles=payload.get('roles', []),
                permissions=payload.get('permissions', []),
                raw_payload=payload,
            )

        except ImportError:
            # navigator_auth not available, try with provided secret
            if self.secret_key:
                try:
                    import jwt
                    payload = jwt.decode(
                        token,
                        self.secret_key,
                        algorithms=[self.algorithm]
                    )
                    return AuthenticatedUser(
                        user_id=payload.get('user_id', payload.get('sub', '')),
                        username=payload.get('username', 'user'),
                        email=payload.get('email', ''),
                        roles=payload.get('roles', []),
                        permissions=payload.get('permissions', []),
                        raw_payload=payload,
                    )
                except Exception as e:
                    self.logger.warning(f"JWT decode error: {e}")
                    return None

            # Fallback for testing (accept any token)
            self.logger.warning(
                "No auth backend available, using fallback validation"
            )
            return AuthenticatedUser(
                user_id=f"test_{token[:8]}",
                username=f"user_{token[:8]}",
                email="test@example.com",
                roles=[],
            )

        except Exception as e:
            self.logger.warning(f"Token validation error: {e}")
            return None


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

    # Ping tracking
    last_ping: Optional[datetime] = None
    ping_count: int = 0


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
        self.logger.info(f"WebSocket route registered: {ws_path}")

        # Health check
        if include_health:
            health_path = f"{prefix}{self.health_route}"
            app.router.add_get(health_path, self._handle_health)
            self.logger.info(f"Health route registered: {health_path}")

        # Static files
        if include_static and static_dir:
            from pathlib import Path
            static_path = Path(static_dir)
            if static_path.exists():
                app.router.add_static(f"{prefix}/static", static_path)
                self.logger.info(f"Static route registered: {prefix}/static")

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
                        self.logger.error(f"Error handling message: {e}")
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
                    self.logger.error(f"WebSocket error: {ws.exception()}")

        except asyncio.CancelledError:
            self.logger.info(f"Connection cancelled: {session_id}")

        finally:
            await self._cleanup_connection(connection)
            self.connections.pop(session_id, None)
            self.logger.info(f"Connection closed: {session_id}")

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
            self.logger.warning(f"Unknown message type: {msg_type}")

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

        # Clear audio buffer for buffered mode
        connection.audio_buffer = b""

        # Store config for factory
        self._current_config = config
        connection.bot = self.bot_factory()

        # Start voice task only for streaming mode
        connection.shutdown_event.clear()
        connection.session_active = True
        connection.stop_audio_sending = False

        if streaming_mode == "streaming":
            connection.voice_task = asyncio.create_task(
                self._run_voice_session(connection)
            )

        await self._send_message(connection.ws, {
            "type": "session_started",
            "session_id": connection.session_id,
            "user_id": connection.user_id,
            "streaming_mode": streaming_mode,
            "config": {
                "voice_name": config.voice_name,
                "language": config.language,
                "input_format": "audio/pcm;rate=16000",
                "output_format": "audio/pcm;rate=24000",
            }
        })

        await self._send_message(connection.ws, {
            "type": "ready_to_speak",
            "message": "Ready for your question"
        })

        self.logger.info(
            f"Voice session started: {connection.session_id} "
            f"(mode={streaming_mode})"
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

        await self._send_message(connection.ws, {
            "type": "session_ended",
            "session_id": connection.session_id,
        })

        self.logger.info(f"Voice session ended: {connection.session_id}")

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

        self.logger.info(f"Voice session reset: {connection.session_id}")

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
            self.logger.error(f"Error processing text: {e}")
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
            self.logger.error(f"Error processing voice: {e}")
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
            self.logger.error(f"Error processing binary voice: {e}")
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
                self.logger.error(f"Voice session error: {e}")
                await self._send_error(connection.ws, str(e))
                await asyncio.sleep(1)

    async def _send_voice_response(
        self,
        connection: WebSocketConnection,
        response: Any
    ) -> None:
        """Send voice response to client."""
        # Send response_chunk for audio OR text (not just audio)
        # FILTER: Skip internal thought processes that leak into output
        is_thought = response.text and re.match(
            r'^\s*(\*\*|##)?\s*(Clarifying|Analyzing|Defining|Thinking|Focusing|Honing|Refining)',
            response.text,
            re.IGNORECASE
        )
        
        if (response.audio_data or (response.text and not is_thought)) and not response.is_complete:
            await self._send_message(connection.ws, {
                "type": "response_chunk",
                "text": response.text or "",
                "audio_base64": base64.b64encode(response.audio_data).decode() if response.audio_data else "",
                "audio_format": "audio/pcm;rate=24000" if response.audio_data else "",
                "is_interrupted": response.is_interrupted,
            })

        if response.metadata.get("user_transcription"):
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": response.metadata["user_transcription"],
                "is_user": True,
            })

        assistant_text = response.metadata.get("assistant_transcription")
        if not assistant_text and response.turn_metadata:
            assistant_text = response.turn_metadata.output_transcription
        if assistant_text:
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": assistant_text,
                "is_user": False,
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
            await self._send_message(connection.ws, {
                "type": "response_complete",
                "text": response.text or "",
                "is_interrupted": response.is_interrupted,
            })

            await self._send_message(connection.ws, {
                "type": "ready_to_speak",
                "message": "Ready for new question"
            })

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
            self.logger.error(f"Error sending message: {e}")

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