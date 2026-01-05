"""
VoiceChatHandler - WebSocket Handler

This handler ONLY handles WebSocket transport.
It does NOT know about Google/Gemini - all voice logic
is encapsulated in VoiceBot/GeminiLiveClient.

Responsibilities:
- Handle WebSocket connections
- Encode/decode base64 audio
- Route control messages
- Maintain connection state
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
)
from aiohttp import web, WSMsgType
from navconfig.logging import logging
from parrot.bots.voice import VoiceBot, create_voice_bot, VoiceConfig
from parrot.voice.models import VoiceConfig as VoiceModelConfig


@dataclass
class BotConfig:
    """Configuration for VoiceBot creation.
    
    All default values are defined here, making configuration explicit
    and type-safe.
    """
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
        """Convert to dictionary for passing to create_voice_bot().
        
        Excludes None values to allow defaults in create_voice_bot.
        """
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


@dataclass
class WebSocketConnection:
    """Represents an active WebSocket connection."""
    ws: web.WebSocketResponse
    session_id: str
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    # Bot associated with this connection
    bot: Optional[VoiceBot] = None

    # Estado de grabación (matching VoiceChatServer)
    is_recording: bool = False
    recording_start_time: Optional[datetime] = None
    session_active: bool = False  # True when bot session is active
    stop_audio_sending: bool = False  # Flag to immediately stop audio forwarding
    gemini_responding: bool = False  # True when Gemini has started responding (VAD triggered)

    # Audio queue for the bot
    audio_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # Voice session task
    voice_task: Optional[asyncio.Task] = None

    # Shutdown event
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    # Configuration received from client
    config: Optional[BotConfig] = None


class VoiceChatHandler:
    """
    Handler of WebSocket messages for voice chat.

    Completely decoupled from the voice provider (Google, OpenAI, etc.).
    Only handles WebSocket transport WebSocket <-> VoiceBot.

    Usage:
        handler = VoiceChatHandler(
            bot_factory=lambda: create_voice_bot(
                name="Assistant",
                voice_name="Puck",
            )
        )

        app = web.Application()
        app.router.add_get('/ws/voice', handler.handle_websocket)
    """

    def __init__(
        self,
        bot_factory: Optional[Callable[[], VoiceBot]] = None,
        default_config: Optional[BotConfig | Dict[str, Any]] = None,
    ):
        """
        Initialize handler.

        Args:
            bot_factory: Bot factory for creating VoiceBot instances
            default_config: Default configuration for bots (BotConfig or dict)
        """
        self.bot_factory = bot_factory or self._default_bot_factory
        # Support both BotConfig and dict for backward compatibility
        if isinstance(default_config, BotConfig):
            self.default_config = default_config
        elif isinstance(default_config, dict):
            self.default_config = BotConfig.from_dict(default_config)
        else:
            self.default_config = BotConfig()
        self._current_config: Optional[BotConfig] = None
        self.connections: Dict[str, WebSocketConnection] = {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _default_bot_factory(self) -> VoiceBot:
        """Default Factory for Bots"""
        # Use _current_config if set (merged config from session), else use default_config
        config = self._current_config or self.default_config
        return create_voice_bot(**config.as_dict())

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Handler of Websocket messages

        Messages protocol:

        Client -> Server:
        - {"type": "start_session", "config": {...}}
        - {"type": "audio_data", "data": "<base64>"}
        - {"type": "start_recording"}
        - {"type": "stop_recording"}
        - {"type": "send_text", "text": "..."}
        - {"type": "end_session"}

        Server -> Client:
        - {"type": "session_started", "session_id": "..."}
        - {"type": "voice_response", "text": "...", "audio_base64": "..."}
        - {"type": "transcription", "text": "...", "role": "user|assistant"}
        - {"type": "tool_call", "name": "...", "result": {...}}
        - {"type": "error", "message": "..."}
        """
        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024  # 10MB for audio
        )
        await ws.prepare(request)

        session_id = str(uuid.uuid4())

        connection = WebSocketConnection(
            ws=ws,
            session_id=session_id,
            user_id=request.query.get('user_id'),
        )
        self.connections[session_id] = connection

        self.logger.info(f"New WebSocket connection: {session_id}")

        try:
            # Send connection confirmation
            await self._send_message(ws, {
                "type": "connected",
                "session_id": session_id,
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
                    # Direct binary audio (matching VoiceChatServer _handle_binary)
                    # Auto-detect recording start
                    if not connection.is_recording:
                        connection.stop_audio_sending = False
                        connection.gemini_responding = False
                        connection.recording_start_time = datetime.now()
                    connection.is_recording = True

                    if connection.session_active and not connection.stop_audio_sending:
                        await connection.audio_queue.put(msg.data)

                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(f"WebSocket error: {ws.exception()}")

        except asyncio.CancelledError:
            self.logger.info(f"Connection cancelled: {session_id}")

        finally:
            await self._cleanup_connection(connection)
            del self.connections[session_id]
            self.logger.info(f"Connection closed: {session_id}")

        return ws

    async def _handle_message(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Route message to appropriate handler."""
        msg_type = message.get('type', '')

        handlers = {
            'start_session': self._handle_start_session,
            'end_session': self._handle_end_session,
            'reset_session': self._handle_reset_session,  # VoiceChatServer compatibility
            'start_recording': self._handle_start_recording,
            'stop_recording': self._handle_stop_recording,
            'audio_data': self._handle_audio_data,
            'audio_chunk': self._handle_audio_data,  # Alias for VoiceChatServer compatibility
            'send_text': self._handle_send_text,
            'text_message': self._handle_send_text,  # Alias for VoiceChatServer compatibility
            'ping': self._handle_ping,
        }

        if handler := handlers.get(msg_type):
            await handler(connection, message)
        else:
            self.logger.warning(f"Unknown message type: {msg_type}")

    async def _handle_start_session(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Start voice session."""
        # Merge default config with client-provided config
        client_config = message.get('config', {})
        config = self.default_config.merge_with(client_config)
        connection.config = config

        # Use bot_factory to create the bot (uses merged config)
        # Store config in instance for factory to use
        self._current_config = config
        connection.bot = self.bot_factory()

        # Start voice task
        connection.shutdown_event.clear()
        connection.session_active = True
        connection.stop_audio_sending = False
        connection.voice_task = asyncio.create_task(
            self._run_voice_session(connection)
        )

        await self._send_message(connection.ws, {
            "type": "session_started",
            "session_id": connection.session_id,
            "config": {
                "voice_name": config.voice_name,
                "language": config.language,
                "input_format": "audio/pcm;rate=16000",
                "output_format": "audio/pcm;rate=24000",
            }
        })

        # Signal frontend that it can speak (enables Talk button)
        await self._send_message(connection.ws, {
            "type": "ready_to_speak",
            "message": "Ready for your question"
        })

        self.logger.info(f"Voice session started: {connection.session_id}")

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

        self.logger.info(
            f"Voice session ended: {connection.session_id}"
        )

    async def _handle_reset_session(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Reset session - end current and start new."""
        # End current session
        await self._handle_end_session(connection, message)

        # Clear audio queue
        while not connection.audio_queue.empty():
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Start new session with same config
        await self._handle_start_session(connection, {
            'config': connection.config.as_dict() if connection.config else {}
        })

        self.logger.info(f"Voice session reset: {connection.session_id}")

    async def _handle_start_recording(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Start audio recording."""
        # Reset flags for new recording (like VoiceChatServer)
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
        """Stop audio recording (matching VoiceChatServer)."""
        connection.is_recording = False
        connection.stop_audio_sending = True  # Immediately stop audio forwarding

        # Check minimum recording duration (500ms)
        MIN_DURATION_MS = 500
        duration_ms = 0
        if connection.recording_start_time:
            duration_ms = (datetime.now() - connection.recording_start_time).total_seconds() * 1000
            connection.recording_start_time = None  # Reset for next recording

            if duration_ms < MIN_DURATION_MS:
                self.logger.info(
                    f"Recording too short ({duration_ms:.0f}ms < {MIN_DURATION_MS}ms), ignoring: {connection.session_id}"
                )
                # Clear the queue
                while not connection.audio_queue.empty():
                    try:
                        connection.audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                # Notify client to reset UI
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

    async def _handle_audio_data(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Receive audio chunk (base64) - matching VoiceChatServer behavior."""
        # Detect new recording start - reset flags (like VoiceChatServer)
        if not connection.is_recording:
            self.logger.debug(f"New recording started: {connection.session_id}")
            connection.stop_audio_sending = False  # Reset FIRST
            connection.gemini_responding = False  # Reset responding flag for new turn
            connection.recording_start_time = datetime.now()

        connection.is_recording = True

        # Check session is active
        if not connection.session_active or connection.stop_audio_sending:
            self.logger.warning(
                f"Audio NOT queued: session_active={connection.session_active}, "
                f"stop_audio_sending={connection.stop_audio_sending}"
            )
            return

        if audio_b64 := message.get('data', ''):
            audio_bytes = base64.b64decode(audio_b64)
            await connection.audio_queue.put(audio_bytes)
            self.logger.debug(f"Audio queued: {len(audio_bytes)} bytes, queue size: {connection.audio_queue.qsize()}")

    async def _handle_send_text(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Send text to bot and receive voice response."""
        text = message.get('text', '')
        if not text or not connection.bot:
            return

        try:
            async for response in connection.bot.ask(
                question=text,
                session_id=connection.session_id,
                user_id=connection.user_id,
            ):
                await self._send_voice_response(connection, response)
        except Exception as e:
            self.logger.error(f"Error processing text: {e}")
            await self._send_error(connection.ws, str(e))

    async def _handle_ping(
        self,
        connection: WebSocketConnection,
        message: Dict[str, Any]
    ) -> None:
        """Respond to ping with pong."""
        await self._send_message(connection.ws, {
            "type": "pong",
            "timestamp": datetime.now().isoformat(),
        })

    async def _run_voice_session(self, connection: WebSocketConnection) -> None:
        """
        Run voice session.

        Reads audio from queue, sends it to the bot, and transmits responses.
        """
        if not connection.bot:
            return

        async def audio_from_queue():
            """Generator that reads audio from queue.
            
            For multi-turn support:
            - Yields audio chunks to send to Gemini
            - Yields None (sentinel) when turn ends to trigger audio_stream_end
            - Stays alive until shutdown_event is set
            """
            audio_ended_sent = False
            
            while not connection.shutdown_event.is_set():
                try:
                    chunk = await asyncio.wait_for(
                        connection.audio_queue.get(),
                        timeout=0.5
                    )
                    # New audio arrived - reset end signal flag
                    audio_ended_sent = False
                    yield chunk
                except asyncio.TimeoutError:
                    # No audio available
                    # If recording stopped and queue empty, signal end of this turn's audio
                    if connection.stop_audio_sending and connection.audio_queue.empty():
                        if not audio_ended_sent:
                            self.logger.debug(
                                f"Turn audio complete for session {connection.session_id}"
                            )
                            # Yield None sentinel to signal end of turn's audio
                            # The _audio_sender will send audio_stream_end
                            yield None
                            audio_ended_sent = True
                    continue
                except asyncio.CancelledError:
                    break

        # Multi-turn session loop
        # Gemini sessions may close (GoAway, timeout, etc.) but we keep listening
        # and restart the session for subsequent questions
        while not connection.shutdown_event.is_set():
            try:
                self.logger.debug(f"Starting/restarting Gemini session for {connection.session_id}")

                async for response in connection.bot.ask_stream(
                    audio_input=audio_from_queue(),
                    session_id=connection.session_id,
                    user_id=connection.user_id,
                ):
                    await self._send_voice_response(connection, response)

                    # Check for unrecoverable error (e.g., unsupported language)
                    if response.metadata.get('error') and not response.metadata.get('is_retryable', True):
                        error_type = response.metadata.get('error_type', 'unknown')
                        self.logger.error(
                            f"Unrecoverable error ({error_type}): {response.metadata.get('error')}"
                        )
                        if error_type == 'unsupported_language':
                            # Fallback to English and restart
                            await self._send_message(connection.ws, {
                                "type": "session_warning",
                                "message": "Language not supported. Switching to English..."
                            })
                            # Update config to use English
                            connection.config = connection.config.merge_with({'language': 'en-US'})
                            self._current_config = connection.config
                            # Recreate bot with English
                            if connection.bot:
                                await connection.bot.close()
                            connection.bot = self.bot_factory()
                            self.logger.info(
                                f"Fallback to English for session {connection.session_id}"
                            )
                            break  # Break to restart with English
                        else:
                            await self._send_error(connection.ws, response.metadata.get('error'))
                            connection.session_active = False
                            return  # Exit completely for other unrecoverable errors

                    # Check for GoAway - session will close
                    if response.metadata.get('go_away'):
                        self.logger.info(f"Received GoAway, will restart session: {connection.session_id}")
                        await self._send_message(connection.ws, {
                            "type": "session_warning",
                            "message": "Session reconnecting...",
                        })
                        break

                    if connection.shutdown_event.is_set():
                        return

                # Session ended - notify and loop to restart
                if not connection.shutdown_event.is_set():
                    self.logger.info(f"Gemini session ended, restarting: {connection.session_id}")

            except asyncio.CancelledError:
                self.logger.info(f"Voice session cancelled: {connection.session_id}")
                return
            except Exception as e:
                error_str = str(e).lower()
                is_language_error = "unsupported language" in error_str

                if is_language_error:
                    # Unrecoverable configuration error - don't retry
                    self.logger.error(
                        f"Voice session unrecoverable error: {e}",
                        exc_info=True
                    )
                    await self._send_error(
                        connection.ws,
                        "Language not supported for this model. Please use English."
                    )
                    connection.session_active = False
                    return  # Exit the loop
                else:
                    self.logger.error(f"Voice session error: {e}", exc_info=True)
                    await self._send_error(connection.ws, str(e))
                    # Wait before retry
                    await asyncio.sleep(1)

    async def _send_voice_response(
        self,
        connection: WebSocketConnection,
        response: Any
    ) -> None:
        """Send voice response to client in VoiceChatServer format."""
        import base64

        # Send audio chunks as response_chunk (matching VoiceChatServer)
        # BUT only if this is NOT a complete response (to avoid duplicate audio)
        if response.audio_data and not response.is_complete:
            await self._send_message(connection.ws, {
                "type": "response_chunk",
                "text": "",
                "audio_base64": base64.b64encode(response.audio_data).decode(),
                "audio_format": "audio/pcm;rate=24000",
                "is_interrupted": response.is_interrupted,
            })

        # Send user transcription if available
        if response.metadata.get('user_transcription'):
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": response.metadata['user_transcription'],
                "is_user": True,
            })

        # Send assistant transcription if available (from metadata or turn_metadata)
        assistant_text = response.metadata.get('assistant_transcription')
        if not assistant_text and response.turn_metadata:
            assistant_text = response.turn_metadata.output_transcription
        if assistant_text:
            await self._send_message(connection.ws, {
                "type": "transcription",
                "text": assistant_text,
                "is_user": False,
            })

        # Send tool call notifications
        for tc in response.tool_calls:
            await self._send_message(connection.ws, {
                "type": "tool_call",
                "name": tc.name,
                "arguments": tc.arguments,
                "result": tc.result,
                "execution_time_ms": tc.execution_time_ms,
            })

        # On turn complete, send response_complete and ready_to_speak
        if response.is_complete:
            # Don't include text in response_complete - it contains model "thoughts"
            # Actual transcriptions were already sent via transcription messages
            await self._send_message(connection.ws, {
                "type": "response_complete",
                "text": "",  # Don't show thoughts/reasoning
                "audio_base64": "",  # Audio already streamed
                "is_interrupted": response.is_interrupted,
            })

            # Signal frontend that it can speak again (enables Talk button)
            await self._send_message(connection.ws, {
                "type": "ready_to_speak",
                "message": "Ready for new question"
            })

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
        """Clean up resources of a connection."""
        connection.shutdown_event.set()

        if connection.voice_task:
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

        if connection.bot:
            await connection.bot.close()

        # Empty queue
        while not connection.audio_queue.empty():
            try:
                connection.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Send message to all active connections."""
        for connection in self.connections.values():
            await self._send_message(connection.ws, message)

    @property
    def active_connections(self) -> int:
        """Number of active connections."""
        return len(self.connections)


# =============================================================================
# Factory to create complete server
# =============================================================================

def create_voice_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    bot_config: Optional[Dict[str, Any]] = None,
    **kwargs
) -> web.Application:
    """
    Create complete voice server.

    Args:
        host: Host for the server
        port: Port for the server
        bot_config: Default configuration for bots
        **kwargs: Additional arguments for aiohttp

    Returns:
        Configured aiohttp application
    """
    from parrot.conf import STATIC_DIR  # pylint: disable=C0415
    frontend_dir = STATIC_DIR / 'chat'
    handler = VoiceChatHandler(default_config=bot_config or {})

    app = web.Application()
    app.router.add_get('/ws/voice', handler.handle_websocket)

    if frontend_dir.exists():
        app.router.add_static('/static', frontend_dir)

        # Serve chat.html at root
        async def index(request):
            return web.FileResponse(frontend_dir / 'chat.html')

        app.router.add_get('/', index)

    # Health check
    async def health_check(request):
        return web.json_response({
            "status": "ok",
            "active_connections": handler.active_connections,
        })

    app.router.add_get('/health', health_check)

    # CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)

        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-User-Id'
        return response

    app.middlewares.append(cors_middleware)

    return app


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Voice Chat WebSocket Server")
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind')
    parser.add_argument('--port', type=int, default=8765, help='Port to bind')
    parser.add_argument('--voice', default='Puck', help='Default voice name')
    args = parser.parse_args()

    app = create_voice_server(
        host=args.host,
        port=args.port,
        bot_config={
            'voice_name': args.voice,
            'system_prompt': "You are a helpful voice assistant.",
        }
    )

    print(f"Starting voice server on {args.host}:{args.port}")
    web.run_app(app, host=args.host, port=args.port)
