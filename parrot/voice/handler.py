"""
Voice WebSocket Handler

Provides WebSocket endpoints for real-time voice interactions.
Handles bidirectional audio streaming between web clients and VoiceBot.
"""

import asyncio
import json
import uuid
import base64
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from aiohttp import web, WSMsgType
from navigator.views import BaseHandler
from .models import VoiceConfig, VoiceResponse
from ..bots.voice import VoiceBot, create_voice_bot


@dataclass
class WebSocketVoiceConnection:
    """Represents an active WebSocket voice connection."""
    ws: web.WebSocketResponse
    session_id: str
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    config: Dict[str, Any] = field(default_factory=dict)
    # Audio streaming state
    audio_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    is_recording: bool = False
    session_active: bool = False
    # Task management
    session_task: Optional[asyncio.Task] = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)


class VoiceStreamHandler(BaseHandler):
    """
    WebSocket handler for voice streaming.
    Provides real-time bidirectional audio streaming for voice chat.
    Protocol:
        Client → Server:
            - {"type": "start_session", "config": {...}}
            - {"type": "audio_chunk", "data": "<base64_pcm>"}
            - {"type": "stop_recording"}
            - {"type": "end_session"}

        Server → Client:
            - {"type": "session_started", "session_id": "..."}
            - {"type": "transcription", "text": "...", "is_user": true/false}
            - {"type": "response_chunk", "text": "...", "audio_base64": "..."}
            - {"type": "response_complete", "text": "...", "audio_base64": "..."}
            - {"type": "error", "message": "..."}
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connections: Dict[str, WebSocketVoiceConnection] = {}
        self.default_bot_config: Dict[str, Any] = kwargs.get('bot_config', {})
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def voice_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Main WebSocket endpoint for voice interactions.

        Route: /ws/voice or /ws/voice/{bot_id}
        """
        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024  # 10MB for audio
        )
        await ws.prepare(request)

        # Create connection
        session_id = str(uuid.uuid4())
        bot_id = request.match_info.get('bot_id', 'default')

        connection = WebSocketVoiceConnection(
            ws=ws,
            session_id=session_id,
            user_id=request.headers.get('X-User-Id')
        )
        self.connections[session_id] = connection

        self.logger.info(f"Voice WebSocket connected: {session_id}")

        try:
            # Send connection confirmation
            await self._send_message(ws, {
                "type": "connected",
                "session_id": session_id,
                "message": "Voice WebSocket connected. Send 'start_session' to begin."
            })

            # Message handling loop
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_text_message(connection, msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await self._handle_binary_message(connection, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(f"WebSocket error: {ws.exception()}")
                    break
                elif msg.type == WSMsgType.CLOSE:
                    break

        except asyncio.CancelledError:
            self.logger.info(f"Voice WebSocket cancelled: {session_id}")
        except Exception as e:
            self.logger.error(f"Voice WebSocket error: {e}")
            await self._send_error(ws, str(e))
        finally:
            # Cleanup
            await self._cleanup_connection(session_id)
            self.logger.info(f"Voice WebSocket disconnected: {session_id}")

        return ws

    async def _handle_text_message(
        self,
        connection: WebSocketVoiceConnection,
        data: str
    ) -> None:
        """Handle incoming JSON text messages."""
        try:
            message = json.loads(data)
            msg_type = message.get('type', '')

            if msg_type == 'start_session':
                await self._handle_start_session(connection, message)

            elif msg_type == 'audio_chunk':
                await self._handle_audio_chunk(connection, message)

            elif msg_type == 'stop_recording':
                await self._handle_stop_recording(connection)

            elif msg_type == 'text_message':
                await self._handle_text_input(connection, message)

            elif msg_type == 'end_session':
                await self._handle_end_session(connection)

            elif msg_type == 'ping':
                await self._send_message(connection.ws, {"type": "pong"})

            else:
                self.logger.warning(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            await self._send_error(connection.ws, f"Invalid JSON: {e}")

    async def _handle_binary_message(
        self,
        connection: WebSocketVoiceConnection,
        data: bytes
    ) -> None:
        """Handle incoming binary audio data."""
        if connection.is_recording and connection.session_active:
            await connection.audio_queue.put(data)

    async def _handle_start_session(
        self,
        connection: WebSocketVoiceConnection,
        message: Dict[str, Any]
    ) -> None:
        """Initialize a new voice session."""
        config = message.get('config', {})
        connection.config = config

        # Create voice configuration
        voice_config = VoiceConfig(
            voice_name=config.get('voice_name', 'Puck'),
            language=config.get('language', 'en-US'),
            enable_vad=config.get('enable_vad', True),
        )

        # Create voice bot
        system_prompt = config.get('system_prompt', self.default_bot_config.get('system_prompt'))

        bot = create_voice_bot(
            name=config.get('name', 'Voice Assistant'),
            system_prompt=system_prompt,
            voice_name=voice_config.voice_name,
            language=voice_config.language,
        )

        # Reset shutdown event for new session
        connection.shutdown_event.clear()

        # Start session task - bot handles Gemini connection internally
        connection.session_task = asyncio.create_task(
            self._run_voice_session(connection, bot)
        )

        await self._send_message(connection.ws, {
            "type": "session_started",
            "session_id": connection.session_id,
            "config": {
                "voice_name": voice_config.voice_name,
                "language": voice_config.language,
                "input_format": "audio/pcm;rate=16000",
                "output_format": "audio/pcm;rate=24000"
            }
        })

        self.logger.info(f"Voice session started: {connection.session_id}")

    async def _run_voice_session(
        self,
        connection: WebSocketVoiceConnection,
        bot: VoiceBot
    ) -> None:
        """
        Run the voice session with proper context management.

        All VoiceBot/Gemini interaction happens inside this method.
        """
        connection.session_active = True

        async def audio_from_queue() -> bytes:
            """Generator that yields audio from the connection's queue."""
            while connection.session_active and not connection.ws.closed:
                try:
                    audio_data = await asyncio.wait_for(
                        connection.audio_queue.get(),
                        timeout=0.1
                    )
                    yield audio_data
                except asyncio.TimeoutError:
                    # Check if we should shutdown
                    if connection.shutdown_event.is_set():
                        break
                    continue
                except asyncio.CancelledError:
                    break

        try:
            async for response in bot.ask_voice_stream(
                audio_input=audio_from_queue(),
                session_id=connection.session_id,
                user_id=connection.user_id
            ):
                if connection.ws.closed:
                    break

                await self._forward_response(connection.ws, response)

        except asyncio.CancelledError:
            self.logger.info(f"Voice session cancelled: {connection.session_id}")
        except Exception as e:
            self.logger.error(f"Voice session error: {e}", exc_info=True)
            await self._send_error(connection.ws, str(e))
        finally:
            connection.session_active = False
            self.logger.info(f"Voice session ended: {connection.session_id}")

    async def _handle_audio_chunk(
        self,
        connection: WebSocketVoiceConnection,
        message: Dict[str, Any]
    ) -> None:
        """Process incoming audio chunk."""
        if not connection.session_active:
            await self._send_error(connection.ws, "Session not started")
            return

        # Decode base64 audio
        audio_b64 = message.get('data', '')
        if audio_b64:
            try:
                audio_bytes = base64.b64decode(audio_b64)
                connection.is_recording = True
                await connection.audio_queue.put(audio_bytes)
            except Exception as e:
                self.logger.error(f"Error processing audio chunk: {e}")

    async def _handle_stop_recording(
        self,
        connection: WebSocketVoiceConnection
    ) -> None:
        """Handle end of user speech."""
        connection.is_recording = False

        await self._send_message(connection.ws, {
            "type": "recording_stopped",
            "message": "Processing your request..."
        })

    async def _handle_text_input(
        self,
        connection: WebSocketVoiceConnection,
        message: Dict[str, Any]
    ) -> None:
        """Handle text input (for hybrid voice/text interactions)."""
        text = message.get('text', '')
        if text:
            self.logger.info(f"Text message received: {text}")
            # Text input would require a different flow
            # For now, just acknowledge
            await self._send_message(connection.ws, {
                "type": "info",
                "message": "Text input received. Use voice for this session."
            })

    async def _handle_end_session(
        self,
        connection: WebSocketVoiceConnection
    ) -> None:
        """End the voice session."""
        # Signal shutdown
        connection.shutdown_event.set()
        connection.session_active = False

        if connection.session_task:
            connection.session_task.cancel()
            try:
                await connection.session_task
            except asyncio.CancelledError:
                pass
            connection.session_task = None

        await self._send_message(connection.ws, {
            "type": "session_ended",
            "session_id": connection.session_id
        })

    async def _forward_response(
        self,
        ws: web.WebSocketResponse,
        response: VoiceResponse
    ) -> None:
        """Forward a VoiceResponse to the WebSocket client."""
        message = {
            "type": "response_complete" if response.is_complete else "response_chunk",
            "text": response.text,
            "audio_base64": base64.b64encode(response.audio_data).decode() if response.audio_data else None,
            "audio_format": response.audio_format.value if response.audio_data else None,
            "is_interrupted": response.is_interrupted,
        }

        # Include transcription metadata if available
        if "user_transcription" in response.metadata:
            message["user_transcription"] = response.metadata["user_transcription"]

        # Include tool calls if any
        if response.tool_calls:
            message["tool_calls"] = response.tool_calls

        await self._send_message(ws, message)

    async def _send_message(
        self,
        ws: web.WebSocketResponse,
        message: Dict[str, Any]
    ) -> None:
        """Send a JSON message to the WebSocket client."""
        if not ws.closed:
            try:
                await ws.send_str(json.dumps(message))
            except Exception as e:
                self.logger.error(f"Error sending message: {e}")

    async def _send_error(
        self,
        ws: web.WebSocketResponse,
        error: str
    ) -> None:
        """Send an error message to the client."""
        await self._send_message(ws, {
            "type": "error",
            "message": error
        })

    async def _cleanup_connection(self, session_id: str) -> None:
        """Clean up a connection and its resources."""
        connection = self.connections.pop(session_id, None)
        if connection:
            # Signal shutdown
            connection.shutdown_event.set()
            connection.session_active = False

            # Cancel session task
            if connection.session_task:
                connection.session_task.cancel()
                try:
                    await connection.session_task
                except asyncio.CancelledError:
                    pass

            # Close WebSocket
            if not connection.ws.closed:
                await connection.ws.close()


def setup_voice_routes(app: web.Application, handler: VoiceStreamHandler = None) -> None:
    """
    Set up voice WebSocket routes on an aiohttp application.

    Args:
        app: aiohttp Application
        handler: VoiceStreamHandler instance (creates new if None)
    """
    if handler is None:
        handler = VoiceStreamHandler()

    app.router.add_get('/ws/voice', handler.voice_websocket)
    app.router.add_get('/ws/voice/{bot_id}', handler.voice_websocket)

    # Store handler reference for cleanup
    app['voice_handler'] = handler


# Standalone server for testing
async def create_voice_app() -> web.Application:
    """Create a standalone voice server application."""
    app = web.Application()

    handler = VoiceStreamHandler()
    setup_voice_routes(app, handler)

    # Add CORS headers for local testing
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


if __name__ == '__main__':
    # Run standalone voice server
    app = asyncio.get_event_loop().run_until_complete(create_voice_app())
    web.run_app(app, host='0.0.0.0', port=8765)
