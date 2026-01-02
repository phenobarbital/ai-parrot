"""
Voice Session Manager

Manages bidirectional voice streaming sessions using native speech-to-speech
models like Gemini Live API. Handles audio streaming, transcription,
tool execution, and multimodal responses.
"""
import contextlib
from typing import AsyncIterator, Optional, List, Dict, Any, Callable
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from google import genai
from google.genai import types
from navconfig.logging import logging
from .models import (
    VoiceConfig,
    VoiceChunk,
    VoiceMessage,
    VoiceResponse,
    AudioFormat,
    SessionState,
    VoiceProvider
)


@dataclass
class SessionContext:
    """Context maintained throughout a voice session."""
    session_id: str
    user_id: Optional[str] = None
    state: SessionState = SessionState.IDLE
    created_at: datetime = field(default_factory=datetime.now)
    messages: List[VoiceMessage] = field(default_factory=list)
    current_turn_audio: bytes = b""
    current_turn_text: str = ""
    tool_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class VoiceSession:
    """
    Manages a bidirectional voice streaming session.

    Provides real-time voice interaction using native speech-to-speech models.
    Supports Gemini Live API with automatic fallback options.

    Usage:
        session = VoiceSession(config, system_prompt, tools)
        async for response in session.run(audio_iterator):
            # Handle voice responses
            pass

    Note: This class does NOT use __aenter__/__aexit__ directly.
    Instead, use the `run()` method which properly manages the Gemini
    Live API context internally.
    """

    def __init__(
        self,
        config: Optional[VoiceConfig] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Callable] = None,
        api_key: Optional[str] = None,
    ):
        """
        Initialize voice session.

        Args:
            config: Voice configuration (uses defaults if None)
            system_prompt: System instructions for the model
            tools: List of tool definitions for function calling
            tool_executor: Async function to execute tool calls
            api_key: API key (falls back to environment variable)
        """
        self.config = config or VoiceConfig()
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.tool_executor = tool_executor

        # Initialize client
        self.client = genai.Client(api_key=api_key)

        # Session state
        self.context: Optional[SessionContext] = None
        self._audio_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Build the configuration for Gemini Live API."""
        # Build speech config
        speech_config = types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self.config.voice_name
                )
            )
        )

        # Build base config
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO", "TEXT"],
            speech_config=speech_config,
            output_audio_transcription=types.AudioTranscriptionConfig()
        )

        # Add system instruction
        if self.system_prompt:
            config.system_instruction = self.system_prompt

        # Add tools if provided
        if self.tools:
            config.tools = [
                types.Tool(function_declarations=self.tools)
            ]

        # Configure input transcription
        if self.config.enable_input_transcription:
            config.input_audio_transcription = types.AudioTranscriptionConfig()

        return config

    async def run(
        self,
        audio_iterator: AsyncIterator[bytes]
    ) -> AsyncIterator[VoiceResponse]:
        """
        Run a complete voice session with proper context management.

        This is the main entry point. All Gemini Live API interaction
        happens inside this method within a proper async context.

        Args:
            audio_iterator: Async iterator yielding audio chunks (PCM 16-bit, 16kHz)

        Yields:
            VoiceResponse objects containing text and/or audio data
        """
        self.context = SessionContext(
            session_id=str(uuid.uuid4()),
            state=SessionState.CONNECTING
        )

        self.logger.info(f"Starting voice session {self.context.session_id}")

        live_config = self._build_live_config()
        self._running = True
        self._shutdown_event.clear()

        try:
            # All Gemini interaction happens inside this async with block
            async with self.client.aio.live.connect(
                model=self.config.get_model(),
                config=live_config
            ) as session:
                self.context.state = SessionState.ACTIVE
                self.logger.info(f"Voice session {self.context.session_id} connected")

                # Start audio sender task
                sender_task = asyncio.create_task(
                    self._audio_sender(session, audio_iterator)
                )

                try:
                    # Receive and yield responses
                    async for response in self._receive_responses(session):
                        yield response

                        # Check for shutdown
                        if self._shutdown_event.is_set():
                            break

                finally:
                    # Ensure sender task is cancelled
                    sender_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender_task

        except asyncio.CancelledError:
            self.logger.info(f"Voice session {self.context.session_id} cancelled")
            raise
        except Exception as e:
            self.context.state = SessionState.ERROR
            self.logger.error(f"Voice session error: {e}")
            raise
        finally:
            self._running = False
            self.context.state = SessionState.CLOSED
            self.logger.info(f"Voice session {self.context.session_id} ended")

    async def run_with_queue(self) -> AsyncIterator[VoiceResponse]:
        """
        Run voice session using internal audio queue.

        Use this when you want to push audio via `queue_audio()` method
        instead of providing an iterator.

        Yields:
            VoiceResponse objects containing text and/or audio data
        """
        async def audio_from_queue() -> AsyncIterator[bytes]:
            """Generator that yields audio from the internal queue."""
            while self._running:
                try:
                    yield await asyncio.wait_for(
                        self._audio_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

        async for response in self.run(audio_from_queue()):
            yield response

    async def queue_audio(self, audio_data: bytes) -> None:
        """
        Queue audio data to be sent to the model.

        Use this with `run_with_queue()` method.

        Args:
            audio_data: Raw PCM audio bytes (16-bit, 16kHz, mono)
        """
        if self._running:
            await self._audio_queue.put(audio_data)

    def shutdown(self) -> None:
        """Signal the session to shutdown gracefully."""
        self._shutdown_event.set()
        self._running = False

    async def _audio_sender(
        self,
        session,
        audio_iterator: AsyncIterator[bytes]
    ) -> None:
        """Send audio from iterator to Gemini session."""
        audio_buffer = b""

        try:
            async for audio_chunk in audio_iterator:
                if not self._running:
                    break

                audio_buffer += audio_chunk
                self.context.current_turn_audio += audio_chunk
                self.context.state = SessionState.LISTENING

                # Send in chunks of ~200ms (3200 bytes at 16kHz, 16-bit)
                while len(audio_buffer) >= 3200:
                    chunk = audio_buffer[:3200]
                    audio_buffer = audio_buffer[3200:]

                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=chunk,
                            mime_type=self.config.input_format.value
                        )
                    )

        except asyncio.CancelledError:
            # Flush remaining buffer before exit
            if audio_buffer:
                with contextlib.suppress(Exception):
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_buffer,
                            mime_type=self.config.input_format.value
                        )
                    )
            raise
        except Exception as e:
            self.logger.error(f"Error sending audio: {e}")

    async def _receive_responses(self, session) -> AsyncIterator[VoiceResponse]:
        """Receive responses from Gemini session."""
        current_text = ""
        current_audio = b""

        try:
            async for response in session.receive():
                if not self._running:
                    break

                # Handle server content (text/audio responses)
                if hasattr(response, 'server_content') and response.server_content:
                    server_content = response.server_content

                    # Check for interruption
                    if getattr(server_content, 'interrupted', False):
                        self.context.state = SessionState.INTERRUPTED
                        yield VoiceResponse(
                            text=current_text,
                            audio_data=current_audio or None,
                            is_interrupted=True
                        )
                        current_text = ""
                        current_audio = b""
                        continue

                    # Check for turn completion
                    if getattr(server_content, 'turn_complete', False):
                        self.context.state = SessionState.ACTIVE
                        yield VoiceResponse(
                            text=current_text,
                            audio_data=current_audio or None,
                            is_complete=True
                        )

                        # Save to history
                        if current_text or current_audio:
                            self.context.messages.append(VoiceMessage(
                                id=str(uuid.uuid4()),
                                role="assistant",
                                audio_data=current_audio or None,
                                transcription=current_text,
                            ))

                        current_text = ""
                        current_audio = b""
                        continue

                    # Process model turn content
                    if hasattr(server_content, 'model_turn') and server_content.model_turn:
                        self.context.state = SessionState.SPEAKING

                        for part in server_content.model_turn.parts:
                            # Handle text
                            if hasattr(part, 'text') and part.text:
                                current_text += part.text
                                yield VoiceResponse(
                                    text=part.text,
                                    is_complete=False
                                )

                            # Handle audio
                            if hasattr(part, 'inline_data') and part.inline_data:
                                audio_chunk = part.inline_data.data
                                current_audio += audio_chunk
                                yield VoiceResponse(
                                    text="",
                                    audio_data=audio_chunk,
                                    audio_format=AudioFormat.PCM_24K,
                                    is_complete=False
                                )

                # Handle tool calls
                if hasattr(response, 'tool_call') and response.tool_call:
                    tool_calls = []
                    for fc in response.tool_call.function_calls:
                        tool_call = {
                            "id": fc.id,
                            "name": fc.name,
                            "arguments": dict(fc.args) if fc.args else {}
                        }
                        tool_calls.append(tool_call)

                        # Execute tool if executor provided
                        if self.tool_executor:
                            try:
                                result = await self.tool_executor(fc.name, dict(fc.args))
                                await self._send_tool_response(session, fc.id, fc.name, result)
                            except Exception as e:
                                self.logger.error(f"Tool execution error: {e}")
                                await self._send_tool_response(
                                    session, fc.id, fc.name,
                                    {"error": str(e)}
                                )

                    yield VoiceResponse(
                        text="",
                        tool_calls=tool_calls,
                        is_complete=False
                    )

                # Handle input transcription
                if hasattr(response, 'input_transcription') and response.input_transcription:
                    transcription = getattr(response.input_transcription, 'text', '')
                    if transcription:
                        self.context.current_turn_text = transcription
                        yield VoiceResponse(
                            text="",
                            metadata={"user_transcription": transcription},
                            is_complete=False
                        )

        except asyncio.CancelledError:
            self.logger.info("Response stream cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in response stream: {e}")
            self.context.state = SessionState.ERROR
            raise

    async def _send_tool_response(
        self,
        session,
        tool_id: str,
        tool_name: str,
        result: Any
    ) -> None:
        """Send tool execution result back to the model."""
        response_content = result if isinstance(result, str) else str(result)

        await session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=tool_id,
                    name=tool_name,
                    response={"result": response_content}
                )
            ]
        )


class VoiceSessionManager:
    """
    Manages multiple voice sessions.

    Provides session lifecycle management, cleanup, and monitoring.
    """

    def __init__(self):
        self.sessions: Dict[str, VoiceSession] = {}
        self.logger = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )

    async def create_session(
        self,
        session_id: Optional[str] = None,
        config: Optional[VoiceConfig] = None,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Callable] = None,
    ) -> VoiceSession:
        """Create and register a new voice session."""
        session_id = session_id or str(uuid.uuid4())

        session = VoiceSession(
            config=config,
            system_prompt=system_prompt,
            tools=tools,
            tool_executor=tool_executor
        )
        self.sessions[session_id] = session
        self.logger.info(f"Created voice session: {session_id}")
        return session

    async def get_session(self, session_id: str) -> Optional[VoiceSession]:
        """Get an existing session by ID."""
        return self.sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        if session := self.sessions.pop(session_id, None):
            await session.close()
            self.logger.info(f"Closed voice session: {session_id}")

    async def close_all(self) -> None:
        """Close all active sessions."""
        for session_id in list(self.sessions.keys()):
            await self.close_session(session_id)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self.sessions)
