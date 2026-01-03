"""
AI-Parrot Voice Chat Server - Proof of Concept

Standalone server for testing voice interactions with Gemini Live API.
Serves both the WebSocket voice endpoint and the frontend static files.

Usage:
    # Set your Google API key
    export GOOGLE_API_KEY=your_api_key_here

    # Run the server
    python server.py

    # Open http://localhost:8765 in your browser
"""
from typing import Dict, Any, Optional
import asyncio
import json
import base64
import uuid
import os
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from aiohttp import web, WSMsgType
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from google import genai
from google.genai import types
from navconfig.logging import logging


@dataclass
class VoiceConnection:
    """Represents an active voice WebSocket connection."""
    ws: web.WebSocketResponse
    session_id: str
    user_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    config: Dict[str, Any] = field(default_factory=dict)

    # Audio streaming state
    audio_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    is_recording: bool = False
    session_active: bool = False
    recording_start_time: Optional[datetime] = None  # Track when recording started
    stop_audio_sending: bool = False  # Flag to immediately stop audio forwarding
    gemini_responding: bool = False  # True when Gemini has started responding (VAD triggered)

    # Task management
    session_task: Optional[asyncio.Task] = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)
    session_restarting: bool = False  # Guard against concurrent restart attempts
    gemini_session_handle: Optional[str] = None  # For session resumption
    gemini_session: Any = None  # Reference to active Gemini session for text testing
    welcome_sent: bool = False  # Track if welcome message was already sent


class VoiceChatServer:
    """
    WebSocket server for voice chat with Gemini Live API.

    Handles bidirectional audio streaming between web clients and the Gemini model.
    """
    # Valid models for Gemini Live API Native Audio
    # See: https://ai.google.dev/gemini-api/docs/live
    NATIVE_AUDIO_MODELS = [
        "gemini-2.5-flash-native-audio-preview-12-2025",  # Latest (Dec 2025)
        "gemini-2.5-flash-native-audio-preview-09-2025",  # September 2025
    ]

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('GOOGLE_API_KEY')
        self.connections: Dict[str, VoiceConnection] = {}
        self.client = None
        self.logger = logging.getLogger("Parrot.VoiceChatServer")
        self.client = genai.Client(api_key=self.api_key)
        self.logger.info("Google GenAI client initialized")

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Main WebSocket handler for voice connections."""
        ws = web.WebSocketResponse(
            heartbeat=30.0,
            max_msg_size=10 * 1024 * 1024  # 10MB
        )
        await ws.prepare(request)

        session_id = str(uuid.uuid4())
        connection = VoiceConnection(
            ws=ws,
            session_id=session_id,
            user_id=request.headers.get('X-User-Id')
        )
        self.connections[session_id] = connection

        self.logger.info(
            f"Voice connection established: {session_id}"
        )

        try:
            # Send connection confirmation
            await self._send(ws, {
                "type": "connected",
                "session_id": session_id,
                "message": "Connected to AI-Parrot Voice Server"
            })

            # Message loop
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(connection, msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await self._handle_binary(connection, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(f"WebSocket error: {ws.exception()}")
                    break

        except asyncio.CancelledError:
            self.logger.info(f"Connection cancelled: {session_id}")
        except Exception as e:
            self.logger.error(f"Connection error: {e}", exc_info=True)
        finally:
            await self._cleanup(session_id)

        return ws

    async def _handle_message(self, conn: VoiceConnection, data: str) -> None:
        """Handle incoming JSON messages."""
        try:
            message = json.loads(data)
            msg_type = message.get('type', '')

            handlers = {
                'start_session': self._handle_start_session,
                'audio_chunk': self._handle_audio_chunk,
                'stop_recording': self._handle_stop_recording,
                'text_message': self._handle_text_message,
                'test_text': self._handle_test_text,  # Debug: test session with text
                'end_session': self._handle_end_session,
                'reset_session': self._handle_reset_session,
                'ping': lambda c, m: self._send(c.ws, {"type": "pong"})
            }

            if handler := handlers.get(msg_type):
                await handler(conn, message)
            else:
                self.logger.warning(
                    f"Unknown message type: {msg_type}"
                )

        except json.JSONDecodeError as e:
            await self._send(
                conn.ws, {"type": "error", "message": f"Invalid JSON: {e}"}
            )

    async def _handle_binary(self, conn: VoiceConnection, data: bytes) -> None:
        """Handle binary audio data - queue it for the session task."""
        if conn.is_recording and conn.session_active and not conn.stop_audio_sending:
            # Track recording start time
            if conn.recording_start_time is None:
                conn.recording_start_time = datetime.now()
                conn.stop_audio_sending = False  # Ensure sending is enabled
            await conn.audio_queue.put(data)

    async def _handle_start_session(self, conn: VoiceConnection, message: Dict) -> None:
        """Initialize a new Gemini Live session."""
        config = message.get('config', {})
        conn.config = config

        try:
            from pprint import pformat  # pylint: disable=import-outside-toplevel
            self.logger.info(
                "Client session request received: %s",
                pformat(config)
            )
        except Exception as format_error:  # pragma: no cover - defensive logging
            self.logger.warning(
                "Unable to format session config: %s", format_error,
                exc_info=True
            )

        if not self.client:
            # Mock mode - simulate session start
            conn.session_active = True
            await self._send(conn.ws, {
                "type": "session_started",
                "session_id": conn.session_id,
                "config": {
                    "voice_name": config.get('voice_name', 'Puck'),
                    "language": config.get('language', 'en-US'),
                    "mode": "mock"
                }
            })
            self.logger.info(f"Mock session started: {conn.session_id}")
            return

        try:
            # Get voice configuration
            voice_name = config.get('voice_name', 'Puck')

            # ============================================================
            # Build LiveConnectConfig using proper typed objects
            # Native Audio models only support ["AUDIO"] response modality
            # See: https://github.com/googleapis/js-genai/issues/1212
            # ============================================================
            live_config = types.LiveConnectConfig(
                # IMPORTANT: Only "AUDIO" for Native Audio models!
                response_modalities=["AUDIO"],
                context_window_compression=(
                    # Configures compression with default parameters.
                    types.ContextWindowCompressionConfig(
                        sliding_window=types.SlidingWindow(),
                    )
                ),
                # Speech/voice configuration
                speech_config=types.SpeechConfig(
                    language_code="en-US",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice_name
                        )
                    )
                ),
                # Enable transcriptions using proper config objects
                input_audio_transcription=types.AudioTranscriptionConfig(),
                output_audio_transcription=types.AudioTranscriptionConfig(),
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
                # Enable VAD (Voice Activity Detection) with tuned settings
                # LOW sensitivity = less likely to detect false starts/ends
                realtime_input_config=types.RealtimeInputConfig(
                    automatic_activity_detection=types.AutomaticActivityDetection(
                        disabled=False,
                        start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                        prefix_padding_ms=100,  # Include 100ms audio before speech start
                        silence_duration_ms=500,  # Wait 500ms of silence before ending
                    )
                ),
                # Session resumption - DISABLED FOR DEBUGGING
                session_resumption=types.SessionResumptionConfig(
                    handle=conn.gemini_session_handle
                ),
                # Generation config
                temperature=0.7,
                max_output_tokens=8192
            )

            # Add system instruction if provided
            if system_prompt := config.get('system_prompt'):
                live_config.system_instruction = system_prompt

            # Use the model from config or default to latest
            model = config.get('model', 'gemini-2.5-flash-native-audio-preview-12-2025')

            self.logger.info(f"Starting session with model: {model}")

            # Reset shutdown event for new session
            conn.shutdown_event.clear()

            # Start the session task - all Gemini interaction happens inside async with
            conn.session_task = asyncio.create_task(
                self._run_gemini_session(conn, model, live_config)
            )

            await self._send(conn.ws, {
                "type": "session_started",
                "session_id": conn.session_id,
                "config": {
                    "voice_name": voice_name,
                    "language": config.get('language', 'en-US'),
                    "model": model
                }
            })

            self.logger.info(
                f"Live session started: {conn.session_id}"
            )

        except Exception as e:
            self.logger.error(f"Failed to start session: {e}", exc_info=True)
            await self._send(conn.ws, {
                "type": "error",
                "message": f"Failed to start session: {str(e)}"
            })

    async def _restart_session(self, conn: VoiceConnection) -> None:
        """Restart the Gemini session for a new turn."""
        # Cancel any existing session task
        if conn.session_task:
            conn.session_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await conn.session_task
            conn.session_task = None

        # Clear the audio queue
        while not conn.audio_queue.empty():
            try:
                conn.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Reset state
        conn.shutdown_event.clear()
        conn.stop_audio_sending = False

        # Build config using stored settings
        voice_name = conn.config.get('voice_name', 'Puck')
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            context_window_compression=(
                # Configures compression with default parameters.
                types.ContextWindowCompressionConfig(
                    sliding_window=types.SlidingWindow(),
                )
            ),
            speech_config=types.SpeechConfig(
                language_code="en-US",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=100,
                    silence_duration_ms=500,
                )
            ),
            # Session resumption - DISABLED FOR DEBUGGING
            session_resumption=types.SessionResumptionConfig(
                handle=conn.gemini_session_handle
            ),
            temperature=0.7,
            max_output_tokens=8192
        )

        if system_prompt := conn.config.get('system_prompt'):
            live_config.system_instruction = system_prompt

        model = conn.config.get(
            'model',
            'gemini-2.5-flash-native-audio-preview-12-2025'
        )

        # Start new session task
        conn.session_task = asyncio.create_task(
            self._run_gemini_session(conn, model, live_config)
        )

        # Wait for session to actually connect (up to 3 seconds)
        for _ in range(30):  # 30 * 100ms = 3 seconds max
            await asyncio.sleep(0.1)
            if conn.session_active:
                self.logger.info(f"Session reconnected: {conn.session_id}")
                return

        self.logger.warning(f"Session reconnect timeout: {conn.session_id}")

    async def _schedule_session_restart(self, conn: VoiceConnection) -> None:
        """Schedule a session restart after receiving GoAway message.

        This allows us to proactively reconnect before the session times out,
        using the stored session handle for resumption.
        """
        # Wait a bit to let any in-flight responses complete
        await asyncio.sleep(2)

        # Only restart if the session is still active and not already restarting
        if conn.session_active and not conn.session_restarting:
            self.logger.info(f"Proactive session restart due to GoAway: {conn.session_id}")
            conn.session_restarting = True
            try:
                await self._restart_session(conn)
                await self._send(conn.ws, {
                    "type": "session_reconnected",
                    "message": "Session reconnected successfully"
                })
            except Exception as e:
                self.logger.error(f"Failed to restart session: {e}")
            finally:
                conn.session_restarting = False

    async def _run_gemini_session(
        self,
        conn: VoiceConnection,
        model: str,
        live_config: Dict
    ) -> None:
        """
        Run the Gemini Live session within proper async context.

        All interaction with the Gemini session happens inside this method,
        within the `async with` block.
        """
        try:
            try:
                from pprint import pformat  # pylint: disable=import-outside-toplevel
                self.logger.info(
                    "Opening Gemini session with model=%s, config=%s",
                    model,
                    pformat(live_config)
                )
            except Exception as format_error:  # pragma: no cover - defensive logging
                self.logger.warning(
                    "Failed to format live_config for logging: %s", format_error,
                    exc_info=True
                )

            async with self.client.aio.live.connect(
                model=model,
                config=live_config
            ) as session:
                conn.session_active = True
                conn.gemini_session = session  # Store reference for text testing
                self.logger.info(f"Gemini session connected: {conn.session_id}")

                # Send proactive welcome message to test if Gemini is working
                # This verifies the session before any audio is sent
                # Only send ONCE per connection, not on session restarts
                # Default to FALSE to avoid browser autoplay policy issues
                send_welcome = conn.config.get('send_welcome', False)
                if send_welcome and not conn.welcome_sent:
                    conn.welcome_sent = True
                    self.logger.info("Sending proactive welcome message to Gemini...")
                    try:
                        await session.send_client_content(
                            turns=types.Content(
                                role="user",
                                parts=[
                                    types.Part(
                                        text="Please greet the user with a friendly 'Hi! How can I help you today?' in a warm, welcoming tone."  # noqa
                                    )
                                ]
                            )
                        )
                        self.logger.info("Welcome message sent, waiting for Gemini response...")
                    except Exception as e:
                        self.logger.error(
                            f"Failed to send welcome message: {e}",
                            exc_info=True
                        )

                # Run audio sender and response receiver concurrently
                sender_task = asyncio.create_task(
                    self._audio_sender(conn, session)
                )
                receiver_task = asyncio.create_task(
                    self._response_receiver(conn, session)
                )

                # Wait for shutdown signal - only this should end the session normally
                # If receiver or sender tasks end, restart them (they shouldn't end normally)
                while True:
                    done, pending = await asyncio.wait(
                        [
                            sender_task,
                            receiver_task,
                            asyncio.create_task(conn.shutdown_event.wait())
                        ],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Check which task completed
                    for task in done:
                        if task == sender_task:
                            self.logger.warning("Audio sender task ended unexpectedly")
                            # Check if it raised an exception
                            try:
                                task.result()
                            except Exception as e:
                                self.logger.error(f"Sender task error: {e}", exc_info=True)
                        elif task == receiver_task:
                            self.logger.warning("Response receiver task ended unexpectedly")
                            try:
                                task.result()
                            except Exception as e:
                                self.logger.error(f"Receiver task error: {e}", exc_info=True)
                        else:
                            # Shutdown event was triggered
                            self.logger.info("Shutdown event triggered, ending session")
                            # Cancel remaining tasks
                            for p in pending:
                                p.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await p
                            return

                    # If only sender/receiver finished, break the loop (don't keep cycling)
                    # The session may have naturally ended from Gemini side
                    if sender_task in done or receiver_task in done:
                        self.logger.info("Task completed, ending session loop")
                        for p in pending:
                            p.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await p
                        break

        except asyncio.CancelledError:
            self.logger.info(
                f"Gemini session cancelled: {conn.session_id}"
            )
        except Exception as e:
            self.logger.error(f"Gemini session error: {e}", exc_info=True)
            await self._send(conn.ws, {"type": "error", "message": str(e)})
        finally:
            conn.session_active = False
            self.logger.info(
                f"Gemini session ended: {conn.session_id}, WS closed: {conn.ws.closed}"
            )

    async def _audio_sender(self, conn: VoiceConnection, session) -> None:
        """Send audio from queue to Gemini session."""
        audio_buffer = b""
        total_bytes_sent = 0
        chunks_sent = 0

        try:
            audio_stream_ended = False
            self.logger.info(f"Audio sender started for session: {conn.session_id}")

            while conn.session_active and not conn.ws.closed:
                # Check if audio sending should stop
                if conn.stop_audio_sending:
                    if not audio_stream_ended:
                        # Send any remaining audio buffer first
                        if audio_buffer:
                            self.logger.debug(f"Sending remaining buffer: {len(audio_buffer)} bytes")
                            try:
                                await session.send_realtime_input(
                                    media=types.Blob(
                                        data=audio_buffer,
                                        mime_type="audio/pcm;rate=16000"
                                    )
                                )
                                self.logger.debug("Remaining buffer sent successfully")
                            except Exception as e:
                                self.logger.error(f"Error sending remaining buffer: {e}", exc_info=True)
                            audio_buffer = b""

                        # Small delay to let Gemini process the last audio chunks
                        await asyncio.sleep(0.3)

                        # Signal end of audio stream to Gemini
                        self.logger.info(
                            f"Sending audio_stream_end signal (total sent: {total_bytes_sent} bytes, {chunks_sent} chunks)"  # noqa
                        )
                        try:
                            # Send end signal with a short timeout to prevent blocking
                            await asyncio.wait_for(
                                session.send_realtime_input(audio_stream_end=True),
                                timeout=2.0
                            )
                            self.logger.info("audio_stream_end sent successfully, waiting for Gemini response...")
                        except asyncio.TimeoutError:
                            self.logger.error("TIMEOUT sending audio_stream_end - this may cause Gemini to not respond!")  # noqa
                        except Exception as e:
                            self.logger.error(f"Error sending audio_stream_end: {e}", exc_info=True)

                        audio_stream_ended = True

                        # Track that we're waiting for a response (only if Gemini hasn't already started responding via VAD)
                        if not conn.gemini_responding:
                            conn.waiting_for_response = True
                            conn.response_wait_start = asyncio.get_event_loop().time()
                        else:
                            self.logger.info("Gemini already responding (VAD triggered), skipping response timeout")
                            conn.waiting_for_response = False

                    # Check if we've been waiting too long for a response (only if Gemini hasn't started responding)
                    if getattr(conn, 'waiting_for_response', False) and not conn.gemini_responding:
                        wait_time = asyncio.get_event_loop().time() - getattr(conn, 'response_wait_start', 0)
                        if wait_time > 15:  # 15 seconds timeout
                            self.logger.warning(
                                "No response from Gemini after %.1fs (sent=%d bytes in %d chunks), notifying client",
                                wait_time,
                                total_bytes_sent,
                                chunks_sent
                            )
                            await self._send(conn.ws, {
                                "type": "error",
                                "message": "No response from Gemini. Please try again."
                            })
                            conn.waiting_for_response = False

                    # Wait quietly until session ends or new recording starts
                    await asyncio.sleep(0.2)
                    continue

                try:
                    # Get audio with timeout to allow checking shutdown
                    audio_data = await asyncio.wait_for(
                        conn.audio_queue.get(),
                        timeout=0.1
                    )

                    # Double-check flag after getting data
                    if conn.stop_audio_sending:
                        continue

                    # Reset audio_stream_ended flag for new recording
                    audio_stream_ended = False
                    audio_buffer += audio_data
                    self.logger.debug(f"Audio buffer now: {len(audio_buffer)} bytes")

                    # Send in chunks of ~200ms (3200 bytes at 16kHz, 16-bit)
                    while len(audio_buffer) >= 3200 and not conn.stop_audio_sending:
                        chunk = audio_buffer[:3200]
                        audio_buffer = audio_buffer[3200:]

                        self.logger.debug(
                            "Sending audio chunk #%d (%d bytes) to Gemini [mime=audio/pcm;rate=16000]",
                            chunks_sent + 1,
                            len(chunk)
                        )
                        await session.send_realtime_input(
                            media=types.Blob(
                                data=chunk,
                                mime_type="audio/pcm;rate=16000"
                            )
                        )
                        total_bytes_sent += len(chunk)
                        chunks_sent += 1
                        self.logger.debug(f"Sent chunk to Gemini: {len(chunk)} bytes (total: {total_bytes_sent})")
                except asyncio.TimeoutError:
                    # No audio in queue, continue loop
                    continue
                except Exception as e:
                    self.logger.error(f"Error sending audio: {e}", exc_info=True)
                    break

        except asyncio.CancelledError:
            # Flush remaining buffer before exit
            if audio_buffer:
                try:
                    await session.send_realtime_input(
                        media=types.Blob(
                            data=audio_buffer,
                            mime_type="audio/pcm;rate=16000"
                        )
                    )
                    self.logger.debug("Flushed remaining buffer on cancel")
                except Exception as e:
                    self.logger.error(f"Error flushing buffer on cancel: {e}", exc_info=True)
            raise

    def _identify_response_type(self, response) -> str:
        """Identify the type of response for logging."""
        types_found = []

        if hasattr(response, 'setup_complete') and response.setup_complete:
            types_found.append("setup_complete")
        if hasattr(response, 'server_content') and response.server_content:
            types_found.append("server_content")
        if hasattr(response, 'tool_call') and response.tool_call:
            types_found.append("tool_call")
        if hasattr(response, 'tool_call_cancellation') and response.tool_call_cancellation:
            types_found.append("tool_call_cancellation")
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            types_found.append("usage_metadata")
        if hasattr(response, 'go_away') and response.go_away:
            types_found.append("go_away")
        if hasattr(response, 'session_resumption_update') and response.session_resumption_update:
            types_found.append("session_resumption_update")

        return ', '.join(types_found) if types_found else "unknown"

    async def _response_receiver(self, conn: VoiceConnection, session) -> None:
        """Receive responses from Gemini and forward to WebSocket client."""
        current_text = ""
        current_audio = b""
        message_count = 0

        self.logger.info(
            f"Response receiver started for session: {conn.session_id}"
        )

        try:
            self.logger.debug(
                f"Starting to receive responses from Gemini: {conn.session_id}"
            )
            async for response in session.receive():
                message_count += 1
                self.logger.debug(f"Received response from Gemini: {conn.session_id}")
                # Clear the waiting flag since we got a response
                conn.responses_received = message_count
                conn.waiting_for_response = False
                response_type = self._identify_response_type(response)
                self.logger.info(f"📩 Message #{message_count}: {response_type}")
                conn.last_gemini_message = response_type

                # Debug full response structure
                try:
                    # import pprint
                    # self.logger.debug(f"Gemini raw response: {pprint.pformat(response)}")
                    pass
                except Exception:
                    self.logger.debug(f"Gemini response: {response}")
                if conn.ws.closed or not conn.session_active:
                    self.logger.debug(f"Breaking receive loop: ws.closed={conn.ws.closed}, session_active={conn.session_active}")
                    break

                # Handle GoAway message - session will disconnect soon
                if hasattr(response, 'go_away') and response.go_away:
                    time_left = getattr(response.go_away, 'time_left', 'unknown')
                    self.logger.warning(f"Gemini GoAway received, {time_left} until disconnect: {conn.session_id}")
                    # Notify frontend that we need to reconnect soon
                    await self._send(conn.ws, {
                        "type": "session_warning",
                        "message": f"Session will disconnect in {time_left}. Will auto-reconnect.",
                        "time_left": str(time_left)
                    })
                    # Schedule a session restart before disconnect
                    # The session will be resumed using the stored handle
                    asyncio.create_task(self._schedule_session_restart(conn))
                    continue

                # Handle session resumption updates - store handle for reconnection
                if hasattr(response, 'session_resumption_update') and response.session_resumption_update:
                    update = response.session_resumption_update
                    if getattr(update, 'resumable', False) and getattr(update, 'new_handle', None):
                        conn.gemini_session_handle = update.new_handle
                        self.logger.info(f"Session resumption handle updated: {conn.session_id}")

                # Handle server content (audio responses)
                if hasattr(response, 'server_content') and response.server_content:
                    sc = response.server_content

                    # Check for generation_complete (model finished generating)
                    if getattr(sc, 'generation_complete', False):
                        self.logger.info(f"Generation complete for session: {conn.session_id}")

                    # Check for interruption
                    if getattr(sc, 'interrupted', False):
                        self.logger.info(f"Turn interrupted. Audio: {len(current_audio)} bytes")
                        conn.gemini_responding = False  # Reset on interruption
                        await self._send(conn.ws, {
                            "type": "response_complete",
                            "text": current_text or "",
                            "audio_base64": base64.b64encode(current_audio).decode() if current_audio else "",
                            "is_interrupted": True
                        })
                        current_text = ""
                        current_audio = b""
                        continue

                    # Check for turn completion
                    if getattr(sc, 'turn_complete', False):
                        # Save audio to file for debugging
                        if current_audio:
                            debug_path = f"/tmp/gemini_audio_{conn.session_id}.pcm"
                            # with open(debug_path, "wb") as f:
                            #    f.write(current_audio)
                            # self.logger.info(f"DEBUG: Saved audio to {debug_path} ({len(current_audio)} bytes)")

                        self.logger.info(f"Turn complete. Total audio: {len(current_audio)} bytes, Text: {len(current_text)} chars")
                        await self._send(conn.ws, {
                            "type": "response_complete",
                            "text": current_text,
                            "audio_base64": "",  # Client already received stream, send empty string instead of None
                            "is_interrupted": False
                        })

                        # Reset responding flag - turn is complete
                        conn.gemini_responding = False

                        # Signal frontend that it can speak again
                        await self._send(conn.ws, {
                            "type": "ready_to_speak",
                            "message": "Ready for new question"
                        })
                        current_text = ""
                        current_audio = b""
                        continue

                    # Process model output
                    if hasattr(sc, 'model_turn') and sc.model_turn:
                        for part in sc.model_turn.parts:
                            # Text output (from transcription)
                            if hasattr(part, 'text') and part.text:
                                # IGNORE generated text for Native Audio since it might be thoughts
                                # We only want the transcription of what was said
                                self.logger.debug(f"Ignored text part (reasoning): {part.text[:100]}...")

                            # Audio output
                            if hasattr(part, 'inline_data') and part.inline_data:
                                audio_chunk = part.inline_data.data
                                current_audio += audio_chunk
                                # Mark that Gemini has started responding (VAD triggered)
                                if not conn.gemini_responding:
                                    conn.gemini_responding = True
                                    self.logger.info("Gemini started responding (VAD triggered)")
                                self.logger.debug(f"Received audio chunk: {len(audio_chunk)} bytes")
                                await self._send(conn.ws, {
                                    "type": "response_chunk",
                                    "text": "",
                                    "audio_base64": base64.b64encode(audio_chunk).decode(),
                                    "audio_format": "audio/pcm;rate=24000",
                                    "is_interrupted": False
                                })

                    # Handle input transcription (user's speech) - it's in server_content!
                    if hasattr(sc, 'input_transcription') and sc.input_transcription:
                        transcription = getattr(sc.input_transcription, 'text', '')
                        if transcription:
                            self.logger.info(f"User transcription: {transcription}")
                            await self._send(conn.ws, {
                                "type": "transcription",
                                "text": transcription,
                                "is_user": True
                            })

                    # Handle output transcription (model's speech) - it's in server_content!
                    if hasattr(sc, 'output_transcription') and sc.output_transcription:
                        transcription = getattr(sc.output_transcription, 'text', '')
                        if transcription:
                            self.logger.info(f"Model transcription: {transcription}")
                            current_text += transcription  # Accumulate transcription
                            await self._send(conn.ws, {
                                "type": "transcription",
                                "text": transcription,
                                "is_user": False
                            })

        except asyncio.CancelledError:
            self.logger.info(
                f"Response receiver cancelled: {conn.session_id}"
            )
            raise
        except ConnectionClosedOK:
            self.logger.info(f"Gemini session closed normally: {conn.session_id}")
        except ConnectionClosedError as e:
            if e.code == 1011:
                self.logger.warning(
                    f"Gemini session timeout (1011): {conn.session_id}"
                )
                await self._send(conn.ws, {
                    "type": "error",
                    "code": "session_timeout",
                    "message": "Session timed out due to inactivity."
                })
            else:
                self.logger.error(f"Gemini connection error: {e}")
                await self._send(conn.ws, {
                    "type": "error",
                    "message": f"Connection error: {e}"
                })
        except Exception as e:
            self.logger.error(
                f"Response receiver error: {e}", exc_info=True
            )
            await self._send(conn.ws, {"type": "error", "message": str(e)})

    async def _handle_audio_chunk(self, conn: VoiceConnection, message: Dict) -> None:
        """Process incoming audio chunk."""
        audio_b64 = message.get('data', '')
        if not audio_b64:
            return

        try:
            audio_bytes = base64.b64decode(audio_b64)

            # Validate audio data - check if it's not silence
            if len(audio_bytes) >= 2:
                import struct
                # Interpret as 16-bit signed integers (little-endian)
                samples = struct.unpack(f'<{len(audio_bytes)//2}h', audio_bytes)
                max_amplitude = max(abs(s) for s in samples) if samples else 0
                # Log amplitude info (every 10th chunk to avoid spam)
                if not hasattr(conn, '_audio_chunk_count'):
                    conn._audio_chunk_count = 0
                conn._audio_chunk_count += 1
                if conn._audio_chunk_count % 10 == 1:
                    self.logger.debug(
                        f"Audio chunk #{conn._audio_chunk_count}: {len(audio_bytes)} bytes, max amplitude: {max_amplitude}"
                    )
                # Warn if audio appears to be silence
                if max_amplitude < 100 and conn._audio_chunk_count <= 5:
                    self.logger.warning(
                        f"Audio chunk appears to be silence (max amplitude: {max_amplitude})"
                    )

            # Detect new recording start - reset flags
            if not conn.is_recording:
                self.logger.debug(f"New recording started: {conn.session_id}")
                conn.stop_audio_sending = False  # Reset FIRST
                conn.gemini_responding = False  # Reset responding flag for new turn
                conn.recording_start_time = datetime.now()
                conn._audio_chunk_count = 0

            conn.is_recording = True

            # If session ended, restart it automatically (can happen at start or during recording)
            # Use session_restarting flag to prevent concurrent restart attempts
            if not conn.session_active and not conn.session_restarting and self.client:
                conn.session_restarting = True
                self.logger.info(f"Restarting Gemini session for new recording: {conn.session_id}")
                try:
                    await self._restart_session(conn)
                finally:
                    conn.session_restarting = False

            if conn.session_active and not conn.stop_audio_sending:
                # Queue audio for the sender task
                await conn.audio_queue.put(audio_bytes)
                self.logger.debug(f"Audio queued: {len(audio_bytes)} bytes, queue size: {conn.audio_queue.qsize()}")
            else:
                # Debug why audio isn't being queued
                self.logger.warning(
                    f"Audio NOT queued: session_active={conn.session_active}, "
                    f"stop_audio_sending={conn.stop_audio_sending}"
                )

        except Exception as e:
            self.logger.error(f"Error processing audio: {e}")

    async def _handle_stop_recording(self, conn: VoiceConnection, message: Dict) -> None:
        """Handle end of user speech."""
        conn.is_recording = False
        conn.stop_audio_sending = True  # Immediately stop audio forwarding

        # Check minimum recording duration (500ms)
        MIN_DURATION_MS = 500
        if conn.recording_start_time:
            duration = (datetime.now() - conn.recording_start_time).total_seconds() * 1000
            conn.recording_start_time = None  # Reset for next recording

            if duration < MIN_DURATION_MS:
                self.logger.info(
                    f"Recording too short ({duration:.0f}ms < {MIN_DURATION_MS}ms), ignoring: {conn.session_id}"
                )
                # Clear the queue
                while not conn.audio_queue.empty():
                    try:
                        conn.audio_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                # Notify client to reset UI
                await self._send(conn.ws, {
                    "type": "recording_stopped",
                    "message": "Recording too short. Please hold longer."
                })
                return
        else:
            conn.recording_start_time = None

        # Don't clear the queue here - let the audio sender flush remaining audio
        # and send audio_stream_end to Gemini

        self.logger.info(f"Recording stopped: {conn.session_id}")

        await self._send(conn.ws, {
            "type": "recording_stopped",
            "message": "Processing..."
        })

        # In mock mode, send a simulated response
        if not self.client:
            await asyncio.sleep(0.5)  # Simulate processing
            await self._send(conn.ws, {
                "type": "response_complete",
                "text": "Hello! This is a mock response. To use real voice, please set your GOOGLE_API_KEY environment variable.",  # noqa
                "audio_base64": None,
                "is_interrupted": False
            })

    async def _handle_text_message(self, conn: VoiceConnection, message: Dict) -> None:
        """Handle text input for hybrid interactions."""
        # Note: For text messages, we'd need to pass them through the session
        # This requires a different approach with the queue-based architecture
        if text := message.get('text', ''):
            self.logger.info(
                f"Text message received (not yet implemented): {text}"
            )

    async def _handle_test_text(self, conn: VoiceConnection, message: Dict) -> None:
        """DEBUG: Send a test text message to Gemini to verify session works."""
        test_text = message.get('text', 'Hello, please respond with just the word OK')

        self.logger.info(f"Testing Gemini session with text: '{test_text}'")

        if not conn.session_active:
            await self._send(conn.ws, {
                "type": "error",
                "message": "No active session to test"
            })
            return

        if not conn.gemini_session:
            await self._send(conn.ws, {
                "type": "error",
                "message": "No Gemini session reference available"
            })
            return

        # Send text directly through the session
        try:
            self.logger.info("Sending text content to Gemini...")
            await conn.gemini_session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=test_text)]
                )
            )
            self.logger.info("Text sent successfully, waiting for response...")

            # Set flag that we're waiting for response
            conn.waiting_for_response = True
            conn.response_wait_start = asyncio.get_event_loop().time()

            await self._send(conn.ws, {
                "type": "info",
                "message": f"Sent test text to Gemini: '{test_text}'. Waiting for response..."
            })
        except Exception as e:
            self.logger.error(f"Error sending test text: {e}", exc_info=True)
            await self._send(conn.ws, {
                "type": "error",
                "message": f"Failed to send text: {e}"
            })

    async def _handle_end_session(self, conn: VoiceConnection, message: Dict) -> None:
        """End the voice session."""
        # Signal the session task to shutdown
        conn.shutdown_event.set()

        if conn.session_task:
            conn.session_task.cancel()
            try:
                await conn.session_task
            except asyncio.CancelledError:
                pass
            conn.session_task = None

        conn.session_active = False
        conn.stop_audio_sending = True

        self.logger.info(f"Session ended by client: {conn.session_id}")

    async def _handle_reset_session(self, conn: VoiceConnection, message: Dict) -> None:
        """Reset the current Gemini session to clear stuck state."""
        self.logger.info(f"Client requested session reset: {conn.session_id}")
        await self._restart_session(conn)

        # Confirm reset to client
        await self._send(conn.ws, {
            "type": "session_reset",
            "message": "Session reset successfully"
        })

    async def _send(self, ws: web.WebSocketResponse, message: Dict) -> None:
        """Send JSON message to WebSocket client."""
        if not ws.closed:
            try:
                await ws.send_str(json.dumps(message))
            except Exception as e:
                self.logger.error(f"Error sending message: {e}")

    async def _cleanup(self, session_id: str) -> None:
        """Clean up connection resources."""
        if conn := self.connections.pop(session_id, None):
            # Signal shutdown
            conn.shutdown_event.set()

            # Cancel session task
            if conn.session_task:
                conn.session_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await conn.session_task

            # Close WebSocket
            if not conn.ws.closed:
                await conn.ws.close()

        self.logger.info(f"Connection cleaned up: {session_id}")


async def create_app() -> web.Application:
    """Create the aiohttp application."""
    from pathlib import Path  # pylint: disable=C0415
    app = web.Application()

    # Create voice server
    voice_server = VoiceChatServer()
    app['voice_server'] = voice_server

    # Routes
    app.router.add_get('/ws/voice', voice_server.handle_websocket)

    # Serve static files (frontend) - prioritize voice/ui folder
    voice_ui_dir = Path(__file__).parent / 'ui'
    if voice_ui_dir.exists() and (voice_ui_dir / 'chat.html').exists():
        frontend_dir = voice_ui_dir
    else:
        from parrot.conf import STATIC_DIR  # pylint: disable=C0415
        frontend_dir = STATIC_DIR / 'chat'

    if frontend_dir.exists():
        app.router.add_static('/static', frontend_dir)

        # Serve chat.html at root
        async def index(request):
            return web.FileResponse(frontend_dir / 'chat.html')

        app.router.add_get('/', index)

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


def main():
    """Run the voice chat server."""
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║         🦜 AI-Parrot Voice Chat Server                    ║
    ╠═══════════════════════════════════════════════════════════╣
    ║  WebSocket: ws://localhost:8765/ws/voice                  ║
    ║  Frontend:  http://localhost:8765                         ║
    ╠═══════════════════════════════════════════════════════════╣
    """)

    # Silence websockets logger
    logging.getLogger("websockets.client").setLevel(logging.WARNING)

    if not os.environ.get('GOOGLE_API_KEY'):
        print("""    ║  ⚠️  GOOGLE_API_KEY not set - running in MOCK mode       ║
    ║     Set it with: export GOOGLE_API_KEY=your_key          ║""")
    else:
        print("""    ║  ✅ GOOGLE_API_KEY detected - Live API enabled            ║""")

    app = asyncio.get_event_loop().run_until_complete(create_app())
    web.run_app(app, host='0.0.0.0', port=8765)


if __name__ == '__main__':
    main()
