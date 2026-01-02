"""
VoiceBot - Bot implementation with voice interaction capabilities.

Extends BaseBot to support voice input/output using native speech-to-speech
models like Gemini Live API.
"""

import asyncio
import uuid
import logging
from typing import Optional, Union, List, Dict, Any, AsyncIterator
from ..bots.base import BaseBot
from ..tools.abstract import AbstractTool
from ..voice.session import VoiceSession
from ..voice.models import VoiceConfig, VoiceResponse


class VoiceBot(BaseBot):
    """
    Bot with native voice interaction capabilities.

    Extends BaseBot to support:
    - Voice input processing (audio → understanding)
    - Voice output generation (response → speech)
    - Bidirectional streaming voice conversations
    - Tool execution during voice interactions

    Usage:
        bot = VoiceBot(
            name="Voice Assistant",
            system_prompt="You are a helpful voice assistant...",
            tools=[my_tool],
            voice_config=VoiceConfig(voice_name="Puck")
        )

        async for response in bot.ask_voice_stream(audio_iterator):
            # Handle voice responses
            pass
    """

    def __init__(
        self,
        name: str = "Voice Assistant",
        system_prompt: Optional[str] = None,
        tools: Optional[List[AbstractTool]] = None,
        voice_config: Optional[VoiceConfig] = None,
        llm: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize VoiceBot.

        Args:
            name: Bot name
            system_prompt: System instructions for the bot
            tools: List of tools available to the bot
            voice_config: Voice configuration (voice, language, etc.)
            llm: LLM client identifier (for text fallback)
            **kwargs: Additional BaseBot arguments
        """
        self.name = name
        self._system_prompt = system_prompt or self._default_voice_prompt()
        self.voice_config = voice_config or VoiceConfig()
        self._voice_tools = tools or []

        # Logger
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # Initialize parent if available
        if BaseBot != object:
            super().__init__(
                name=name,
                system_prompt=system_prompt,
                tools=tools,
                llm=llm,
                **kwargs
            )

    def _default_voice_prompt(self) -> str:
        """Default system prompt optimized for voice interactions."""
        return """You are a helpful voice assistant.

Key behaviors for voice interaction:
- Keep responses concise and conversational
- Speak naturally, as if having a face-to-face conversation
- Avoid long lists or complex formatting that doesn't work well in speech
- Use conversational transitions and acknowledgments
- If you need to present structured information, break it into digestible chunks
- Ask clarifying questions when the user's intent is unclear
- Acknowledge when you're performing an action or searching for information

Remember: The user is speaking to you, so respond in a way that sounds natural when spoken aloud."""

    @property
    def system_prompt(self) -> str:
        """Get the system prompt."""
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        """Set the system prompt."""
        self._system_prompt = value

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Get tool definitions formatted for Gemini Live API.

        Returns:
            List of function declarations for the API
        """
        definitions = []

        for tool in self._voice_tools:
            if hasattr(tool, 'get_tool_schema'):
                schema = tool.get_tool_schema()
            elif hasattr(tool, 'args_schema'):
                # Convert Pydantic schema to function declaration
                schema = {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args_schema.model_json_schema() if hasattr(tool.args_schema, 'model_json_schema') else {}
                }
            else:
                schema = {
                    "name": getattr(tool, 'name', 'unknown'),
                    "description": getattr(tool, 'description', ''),
                    "parameters": {"type": "object", "properties": {}}
                }

            definitions.append(schema)

        return definitions

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        for tool in self._voice_tools:
            if getattr(tool, 'name', None) == tool_name:
                if hasattr(tool, '_execute'):
                    return await tool._execute(**arguments)
                elif hasattr(tool, 'execute'):
                    result = tool.execute(**arguments)
                    if asyncio.iscoroutine(result):
                        return await result
                    return result
                elif hasattr(tool, '_arun'):
                    return await tool._arun(**arguments)

        raise ValueError(f"Tool not found: {tool_name}")

    async def ask_voice_stream(
        self,
        audio_input: Union[bytes, AsyncIterator[bytes]],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[VoiceResponse]:
        """
        Process voice input and stream voice responses.

        This is the main entry point for voice interactions. It accepts
        audio input (either as a complete buffer or streaming chunks)
        and yields multimodal responses with both text and audio.

        Args:
            audio_input: Audio data - either complete bytes or async iterator of chunks
            session_id: Session identifier for conversation continuity
            user_id: User identifier
            **kwargs: Additional options

        Yields:
            VoiceResponse objects containing text and/or audio data
        """
        session_id = session_id or str(uuid.uuid4())

        # Create voice session
        session = VoiceSession(
            config=self.voice_config,
            system_prompt=self.system_prompt,
            tools=self.get_tool_definitions() if self._voice_tools else None,
            tool_executor=self.execute_tool if self._voice_tools else None
        )

        try:
            # Handle different input types
            if isinstance(audio_input, bytes):
                # Single audio buffer - wrap in async iterator
                async def single_chunk_iterator():
                    yield audio_input

                async for response in session.run(single_chunk_iterator()):
                    yield response
            else:
                # Streaming audio - pass iterator directly
                async for response in session.run(audio_input):
                    yield response

        except Exception as e:
            self.logger.error(f"Error in voice stream: {e}")
            yield VoiceResponse(
                text=f"I'm sorry, I encountered an error: {str(e)}",
                is_complete=True,
                metadata={"error": str(e)}
            )

    async def ask_voice(
        self,
        audio_input: bytes,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> VoiceResponse:
        """
        Process voice input and return a complete voice response.

        Non-streaming version that waits for the complete response.

        Args:
            audio_input: Complete audio buffer (PCM 16-bit, 16kHz, mono)
            session_id: Session identifier
            user_id: User identifier
            **kwargs: Additional options

        Returns:
            Complete VoiceResponse with text and audio
        """
        full_text = ""
        full_audio = b""
        tool_calls = []
        metadata = {}

        async for response in self.ask_voice_stream(
            audio_input=audio_input,
            session_id=session_id,
            user_id=user_id,
            **kwargs
        ):
            if response.text:
                full_text += response.text
            if response.audio_data:
                full_audio += response.audio_data
            if response.tool_calls:
                tool_calls.extend(response.tool_calls)
            if response.metadata:
                metadata.update(response.metadata)

        return VoiceResponse(
            text=full_text,
            audio_data=full_audio if full_audio else None,
            is_complete=True,
            tool_calls=tool_calls,
            metadata=metadata
        )

    # Override ask_stream to support voice input
    async def ask_stream(
        self,
        question: Union[str, bytes],  # Can be text or audio
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[Union[str, VoiceResponse]]:
        """
        Extended ask_stream that supports both text and voice input.

        If question is bytes (audio), delegates to ask_voice_stream.
        If question is str (text), uses parent implementation.

        Args:
            question: Text prompt or audio bytes
            session_id: Session identifier
            user_id: User identifier
            **kwargs: Additional options

        Yields:
            Text chunks (for text input) or VoiceResponse (for voice input)
        """
        if isinstance(question, bytes):
            # Voice input - use voice streaming
            async for response in self.ask_voice_stream(
                audio_input=question,
                session_id=session_id,
                user_id=user_id,
                **kwargs
            ):
                yield response
        else:
            # Text input - use parent implementation if available
            if hasattr(super(), 'ask_stream'):
                async for chunk in super().ask_stream(
                    question=question,
                    session_id=session_id,
                    user_id=user_id,
                    **kwargs
                ):
                    yield chunk
            else:
                # Fallback for standalone testing
                yield f"Text response to: {question}"


# Convenience function for creating voice-enabled bots
def create_voice_bot(
    name: str = "Voice Assistant",
    system_prompt: Optional[str] = None,
    tools: Optional[List[AbstractTool]] = None,
    voice_name: str = "Puck",
    language: str = "en-US",
    **kwargs
) -> VoiceBot:
    """
    Factory function to create a voice-enabled bot.

    Args:
        name: Bot name
        system_prompt: System instructions
        tools: Available tools
        voice_name: Voice to use (Aoede, Charon, Fenrir, Kore, Puck)
        language: Language code
        **kwargs: Additional bot options

    Returns:
        Configured VoiceBot instance
    """
    config = VoiceConfig(
        voice_name=voice_name,
        language=language
    )

    return VoiceBot(
        name=name,
        system_prompt=system_prompt,
        tools=tools,
        voice_config=config,
        **kwargs
    )
