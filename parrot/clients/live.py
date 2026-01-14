"""
GeminiLiveClient - Live/Realtime API Client for AI-Parrot

Inherits from AbstractClient to maintain consistency with the AI-Parrot
ecosystem while supporting the unique requirements of voice streaming.

Key Features:
- Inherits from AbstractClient (same as GoogleGenAIClient, AnthropicClient, etc.)
- Reuses tool_manager, conversation_memory, preset system
- Uses same credential pattern as GoogleGenAIClient
- Supports AbstractTool integration via LiveToolAdapter
- Returns LiveVoiceResponse with CompletionUsage metadata

Usage:
    client = GeminiLiveClient(
        model=GoogleVoiceModel.DEFAULT,
        voice_name="Puck",
        tools=[my_tool],  # AbstractTool instances
    )

    async with client:
        async for response in client.stream_voice(audio_iterator):
            print(response.text, response.usage)

Location: parrot/clients/live.py
"""
from __future__ import annotations
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Union,
)
import uuid
import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import base64
import inspect
from google import genai
from google.genai import types
from google.oauth2 import service_account
from navconfig import config
# Import from parrot framework
from .base import AbstractClient
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.manager import ToolManager
from ..memory import ConversationMemory, InMemoryConversation
from ..models.google import GoogleVoiceModel

# =============================================================================
# Response Models with Usage Metadata
# =============================================================================

@dataclass
class LiveCompletionUsage:
    """
    Usage tracking for Gemini Live API responses.

    Compatible with CompletionUsage from parrot.models.basic
    """
    # Core token metrics
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Aliases for Gemini naming
    input_tokens: int = 0
    output_tokens: int = 0

    # Audio-specific metrics
    input_audio_duration_ms: float = 0.0
    output_audio_duration_ms: float = 0.0

    # Timing
    response_time_ms: float = 0.0
    first_token_time_ms: float = 0.0

    # Tool execution
    tool_calls_executed: int = 0
    tool_execution_time_ms: float = 0.0

    # Provider metadata
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Sync aliases
        if self.input_tokens and not self.prompt_tokens:
            self.prompt_tokens = self.input_tokens
        if self.output_tokens and not self.completion_tokens:
            self.completion_tokens = self.output_tokens
        if not self.total_tokens:
            self.total_tokens = self.prompt_tokens + self.completion_tokens

    @classmethod
    def from_gemini_usage(cls, usage_metadata: Any) -> "LiveCompletionUsage":
        """Create from Gemini usage metadata when available."""
        if usage_metadata is None:
            return cls()

        return cls(
            prompt_tokens=getattr(usage_metadata, 'prompt_token_count', 0) or 0,
            completion_tokens=getattr(usage_metadata, 'candidates_token_count', 0) or 0,
            total_tokens=getattr(usage_metadata, 'total_token_count', 0) or 0,
            input_tokens=getattr(usage_metadata, 'prompt_token_count', 0) or 0,
            output_tokens=getattr(usage_metadata, 'candidates_token_count', 0) or 0,
            extra=usage_metadata.__dict__ if hasattr(usage_metadata, '__dict__') else {}
        )


@dataclass
class LiveToolCall:
    """Represents a tool call from Gemini Live API."""
    id: str
    name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms
        }


@dataclass
class VoiceTurnMetadata:
    """Metadata for a single voice turn/response."""
    turn_id: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    input_transcription: Optional[str] = None
    output_transcription: Optional[str] = None
    tool_calls_count: int = 0
    was_interrupted: bool = False

    @property
    def duration_ms(self) -> float:
        if self.ended_at:
            return (self.ended_at - self.started_at).total_seconds() * 1000
        return 0.0


@dataclass
class LiveVoiceResponse:
    """
    Response from GeminiLiveClient voice interaction.

    Enhanced version of VoiceResponse with CompletionUsage metadata
    for consistency with other AbstractClient implementations.
    """
    # Content
    text: str = ""
    audio_data: Optional[bytes] = None
    audio_format: str = "audio/pcm;rate=24000"

    # State
    is_complete: bool = False
    is_interrupted: bool = False

    # Tool calls
    tool_calls: List[LiveToolCall] = field(default_factory=list)

    # Usage metadata - consistent with CompletionUsage
    usage: Optional[LiveCompletionUsage] = None

    # Turn metadata
    turn_metadata: Optional[VoiceTurnMetadata] = None

    # Session info
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    user_id: Optional[str] = None

    # Extra metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_websocket_message(self) -> Dict[str, Any]:
        """Format for WebSocket transmission."""

        return {
            "type": "voice_response",
            "text": self.text,
            "audio_base64": base64.b64encode(self.audio_data).decode() if self.audio_data else None,
            "audio_format": self.audio_format,
            "is_complete": self.is_complete,
            "is_interrupted": self.is_interrupted,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens if self.usage else 0,
                "completion_tokens": self.usage.completion_tokens if self.usage else 0,
                "total_tokens": self.usage.total_tokens if self.usage else 0,
                "response_time_ms": self.usage.response_time_ms if self.usage else 0,
            } if self.usage else None,
            "metadata": self.metadata,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
        }


# =============================================================================
# Live Tool Adapter - Convert AbstractTool to Live API format
# =============================================================================

class LiveToolAdapter:
    """
    Adapter to convert AI-Parrot AbstractTool instances to Gemini Live API
    function declarations and handle execution/response formatting.

    Reuses patterns from GoogleGenAIClient._prepare_tool_definitions()
    """

    def __init__(
        self,
        tool_manager: Optional[ToolManager] = None,
        tools: Optional[List[Any]] = None,
        logger: Optional[Any] = None
    ):
        """
        Initialize adapter.

        Args:
            tool_manager: ToolManager instance from AbstractClient
            tools: Additional tool instances
            logger: Logger instance
        """
        self.tool_manager = tool_manager
        self.extra_tools = tools or []
        self.tool_map: Dict[str, Any] = {}
        self.logger = logger
        self._build_tool_map()

    def _build_tool_map(self) -> None:
        """Build a map from tool names to tool instances."""
        # From tool_manager
        if self.tool_manager:
            for tool in self.tool_manager.all_tools():
                if hasattr(tool, 'name'):
                    self.tool_map[tool.name] = tool

        # From extra tools
        for tool in self.extra_tools:
            if hasattr(tool, 'name'):
                self.tool_map[tool.name] = tool
            elif hasattr(tool, '__name__'):
                self.tool_map[tool.__name__] = tool

    def _clean_schema_for_google(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean schema for Google/Vertex AI compatibility."""
        def clean_recursive(obj: Any) -> Any:
            if isinstance(obj, dict):
                cleaned = {}
                for key, value in obj.items():
                    # Skip keys not supported by Google
                    if key in ('additionalProperties', '$defs', 'definitions', 'examples', 'default', 'title'):
                        continue
                    cleaned[key] = clean_recursive(value)
                return cleaned
            elif isinstance(obj, list):
                return [clean_recursive(item) for item in obj]
            return obj

        return clean_recursive(schema)

    def _fix_type_case(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Convert type values to uppercase for GenAI compatibility."""
        def fix_recursive(obj: Any) -> Any:
            if isinstance(obj, dict):
                result = {}
                for key, value in obj.items():
                    if key == 'type' and isinstance(value, str):
                        result[key] = value.upper()
                    else:
                        result[key] = fix_recursive(value)
                return result
            elif isinstance(obj, list):
                return [fix_recursive(item) for item in obj]
            return obj

        return fix_recursive(schema)

    def get_function_declarations(self) -> List[types.FunctionDeclaration]:
        """
        Convert all tools to Gemini Live API function declarations.

        Returns:
            List of types.FunctionDeclaration objects
        """
        declarations = []

        # From tool_manager
        if self.tool_manager:
            for tool in self.tool_manager.all_tools():
                try:
                    if declaration := self._tool_to_declaration(tool):
                        declarations.append(declaration)
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Error converting tool {getattr(tool, 'name', 'unknown')}: {e}")

        # From extra tools
        for tool in self.extra_tools:
            try:
                if declaration := self._tool_to_declaration(tool):
                    declarations.append(declaration)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error converting extra tool: {e}")

        return declarations

    def _tool_to_declaration(self, tool: Any) -> Optional[types.FunctionDeclaration]:
        """Convert a single tool to a FunctionDeclaration."""
        # Handle AbstractTool instances
        if hasattr(tool, 'get_tool_schema'):
            full_schema = tool.get_tool_schema()
            tool_name = full_schema.get('name', getattr(tool, 'name', 'unknown'))
            tool_description = full_schema.get('description', getattr(tool, 'description', ''))

            # Extract parameters schema
            params_schema = full_schema.get('parameters', {}).copy()
            params_schema = self._clean_schema_for_google(params_schema)
            params_schema = self._fix_type_case(params_schema)

            if not params_schema:
                params_schema = {"type": "OBJECT", "properties": {}, "required": []}

            return types.FunctionDeclaration(
                name=tool_name,
                description=tool_description,
                parameters=params_schema
            )

        # Handle ToolDefinition
        elif hasattr(tool, 'input_schema'):
            params_schema = self._clean_schema_for_google(tool.input_schema.copy())
            params_schema = self._fix_type_case(params_schema)

            return types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=params_schema
            )

        # Handle callable with metadata
        elif callable(tool) and hasattr(tool, '_tool_metadata'):
            metadata = tool._tool_metadata
            return types.FunctionDeclaration(
                name=metadata['name'],
                description=metadata['description'],
                parameters=self._fix_type_case(metadata.get('schema', {}))
            )

        return None

    async def execute_tool(
        self,
        function_call: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> types.FunctionResponse:
        """
        Execute a tool call and return a FunctionResponse.
        """
        tool_name = function_call.name
        tool_id = function_call.id
        tool_args = dict(function_call.args) if function_call.args else {}

        try:
            tool = self.tool_map.get(tool_name)

            if tool is None:
                return types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Tool '{tool_name}' not found"}
                )

            # Execute the tool
            if hasattr(tool, '_execute'):
                # AbstractTool
                result = await tool._execute(**tool_args)
            elif hasattr(tool, '__call__'):
                # Callable
                called = tool(**tool_args)
                if inspect.iscoroutine(called):
                    result = await called
                else:
                    result = called
            else:
                return types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Tool '{tool_name}' is not executable"}
                )

            # Handle ToolResult from AbstractTool
            if isinstance(result, ToolResult):
                if result.status == "success":
                    # Ensure response is always a dict
                    if isinstance(result.result, dict):
                        response_data = result.result
                    elif isinstance(result.result, str):
                        response_data = {"output": result.result}
                    else:
                        response_data = {"output": str(result.result) if result.result else "Success"}
                else:
                    response_data = {"error": result.error or "Unknown error"}
            else:
                # Wrap non-dict results
                if isinstance(result, dict):
                    response_data = result
                elif isinstance(result, str):
                    response_data = {"output": result}
                else:
                    response_data = {"result": result}

            return types.FunctionResponse(
                name=tool_name,
                id=tool_id,
                response=response_data
            )

        except Exception as e:
            if self.logger:
                self.logger.error(f"Tool execution error for {tool_name}: {e}")
            return types.FunctionResponse(
                name=tool_name,
                id=tool_id,
                response={"error": str(e)}
            )


# =============================================================================
# GeminiLiveClient - Main Client Implementation
# =============================================================================

class GeminiLiveClient(AbstractClient):
    """
    Client for Gemini Live API voice interactions.

    Inherits from AbstractClient to maintain consistency with the AI-Parrot
    ecosystem. Reuses tool_manager, conversation_memory, and credential
    patterns from GoogleGenAIClient.

    Key features:
    - Inherits tool_manager and conversation_memory from AbstractClient
    - Uses same credential system (api_key, vertexai, credentials_file)
    - Integrates AbstractTool via LiveToolAdapter
    - Returns LiveVoiceResponse with usage metadata

    Usage:
        client = GeminiLiveClient(
            model=GoogleVoiceModel.DEFAULT,
            voice_name="Puck",
            tools=[my_tool],
            use_tools=True,
        )

        async with client:
            async for response in client.stream_voice(audio_iterator):
                print(response.text, response.usage)
    """

    # Class attributes following AbstractClient pattern
    client_type: str = 'google_live'
    client_name: str = 'google_live'
    _default_model: str = GoogleVoiceModel.DEFAULT.value

    def __init__(
        self,
        model: Optional[Union[str, GoogleVoiceModel]] = None,
        # Credentials (same as GoogleGenAIClient)
        api_key: Optional[str] = None,
        vertexai: bool = False,
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials_file: Optional[Union[str, Path]] = None,
        # Voice-specific settings
        voice_name: str = "Puck",
        language: str = "en-US",
        # AbstractClient params
        conversation_memory: Optional[ConversationMemory] = None,
        preset: Optional[str] = None,
        tools: Optional[List[Union[str, AbstractTool]]] = None,
        use_tools: bool = False,
        tool_manager: Optional[ToolManager] = None,
        debug: bool = False,
        **kwargs
    ):
        """
        Initialize GeminiLiveClient.

        Args:
            model: Model identifier (defaults to latest native audio model)
            api_key: Google API key (falls back to GOOGLE_API_KEY env var)
            vertexai: Use Vertex AI instead of Gemini API
            project: Vertex AI project ID
            location: Vertex AI location
            credentials_file: Path to service account credentials
            voice_name: Voice for speech synthesis (Puck, Charon, Kore, etc.)
            language: Language code (en-US, es-ES, etc.)
            conversation_memory: Conversation memory instance
            preset: LLM preset name
            tools: List of tools to register
            use_tools: Enable tool usage
            tool_manager: Existing ToolManager instance
            debug: Enable debug mode
            **kwargs: Additional AbstractClient params (temperature, top_k, etc.)
        """
        # Resolve model
        if model is None:
            model = self._default_model
        elif isinstance(model, GoogleVoiceModel):
            model = model.value
        super().__init__(
            model=model,
            conversation_memory=conversation_memory,
            preset=preset,
            tools=tools,
            use_tools=use_tools,
            tool_manager=tool_manager,
            debug=debug,
            **kwargs
        )

        # Google credentials (same pattern as GoogleGenAIClient)
        self.api_key = api_key or config.get('GOOGLE_API_KEY')
        self.vertexai = vertexai
        self.vertex_project = project or config.get('VERTEX_PROJECT_ID')
        self.vertex_location = location or config.get('VERTEX_REGION')
        if credentials_file:
            self._credentials_file = Path(credentials_file).expanduser()
        else:
            creds = config.get('VERTEX_CREDENTIALS_FILE')
            self._credentials_file = Path(creds).expanduser() if creds else None

        # Voice-specific settings
        self.voice_name = voice_name
        self.language = language

        # Tool adapter (lazy initialization)
        self._tool_adapter: Optional[LiveToolAdapter] = None

    async def get_client(self) -> genai.Client:
        """
        Return the underlying genai.Client instance.

        Required by AbstractClient (abstract method).
        """
        if self.vertexai:
            self.logger.info(
                f"Initializing Vertex AI for project {self.vertex_project} "
                f"in {self.vertex_location}"
            )
            credentials = None
            if self._credentials_file and self._credentials_file.exists():
                credentials = service_account.Credentials.from_service_account_file(
                    str(self._credentials_file)
                )

            return genai.Client(
                vertexai=True,
                project=self.vertex_project,
                location=self.vertex_location,
                credentials=credentials,
                http_options={"api_version": "v1beta"}
            )

        return genai.Client(
            api_key=self.api_key,
            http_options={"api_version": "v1beta"}
        )

    def _get_tool_adapter(self) -> LiveToolAdapter:
        """Get or create the tool adapter."""
        if self._tool_adapter is None:
            self._tool_adapter = LiveToolAdapter(
                tool_manager=self.tool_manager,
                logger=self.logger
            )
        return self._tool_adapter

    def _build_live_config(
        self,
        system_prompt: Optional[str] = None,
        response_modalities: Optional[List[str]] = None,
    ) -> types.LiveConnectConfig:
        """Build the LiveConnectConfig for a session."""
        # Speech configuration
        speech_config = types.SpeechConfig(
            language_code=self.language,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self.voice_name
                )
            )
        )
        # Native Audio only supports AUDIO modality
        modalities = response_modalities or ["AUDIO"]
        live_config = types.LiveConnectConfig(
            response_modalities=modalities,
            speech_config=speech_config,
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=100,
                    silence_duration_ms=500,
                )
            ),
            # Enable transcriptions using proper config objects
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )

        # System prompt
        if system_prompt:
            live_config.system_instruction = system_prompt

        # Tools (if enabled)
        print('ENABLE TOOLS')
        print(self.enable_tools)
        print('Tool manager tools')
        print(self.tool_manager.tools)
        if self.enable_tools:
            adapter = self._get_tool_adapter()
            if declarations := adapter.get_function_declarations():
                live_config.tools = [types.Tool(function_declarations=declarations)]
                self.logger.debug(
                    f"Registered {len(declarations)} tools for Live session"
                )
        print('LIVE CONFIG ')
        print(live_config)
        return live_config

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[LiveVoiceResponse]:
        """
        Stream bidirectional voice interaction.

        This is the main method for voice interactions. It handles:
        - Audio streaming to the model
        - Receiving audio/text responses
        - Tool execution (via tool_manager)
        - Usage tracking

        Args:
            audio_iterator: Async iterator yielding audio chunks (PCM 16-bit, 16kHz)
            system_prompt: Optional system instructions
            session_id: Session identifier for tracking
            user_id: User identifier
            **kwargs: Additional configuration

        Yields:
            LiveVoiceResponse objects with audio, text, and usage metadata
        """
        # Ensure client is initialized
        if not self.client:
            self.client = await self.get_client()

        session_id = session_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        live_config = self._build_live_config(
            system_prompt=system_prompt,
            **{k: v for k, v in kwargs.items() if k in (
                'response_modalities', 'enable_input_transcription', 'enable_output_transcription'
            )}
        )

        # Tracking
        turn_metadata = VoiceTurnMetadata(turn_id=turn_id)
        usage = LiveCompletionUsage()
        accumulated_text = ""
        accumulated_audio = b""
        tool_calls_list: List[LiveToolCall] = []

        self.logger.info(f"Starting voice session {session_id}, turn {turn_id}")

        try:
            async with self.client.aio.live.connect(
                model=self.model,
                config=live_config
            ) as session:
                # Start audio sender task
                sender_task = asyncio.create_task(
                    self._audio_sender(session, audio_iterator)
                )

                try:
                    async for response in session.receive():
                        # Handle server content (audio/text responses)
                        if response.server_content:
                            server_content = response.server_content

                            # Check for turn complete
                            if getattr(server_content, 'turn_complete', False):
                                turn_metadata.ended_at = datetime.now()
                                usage.response_time_ms = turn_metadata.duration_ms

                                yield LiveVoiceResponse(
                                    text=accumulated_text,
                                    audio_data=accumulated_audio or None,
                                    is_complete=True,
                                    tool_calls=tool_calls_list,
                                    usage=usage,
                                    turn_metadata=turn_metadata,
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                )

                                # Reset for next turn
                                turn_id = str(uuid.uuid4())
                                turn_metadata = VoiceTurnMetadata(turn_id=turn_id)
                                accumulated_text = ""
                                accumulated_audio = b""
                                tool_calls_list = []
                                usage = LiveCompletionUsage()
                                continue

                            # Check for interruption
                            if getattr(server_content, 'interrupted', False):
                                turn_metadata.was_interrupted = True
                                yield LiveVoiceResponse(
                                    text=accumulated_text,
                                    audio_data=accumulated_audio or None,
                                    is_complete=True,
                                    is_interrupted=True,
                                    usage=usage,
                                    turn_metadata=turn_metadata,
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                )
                                continue

                            # Process model turn
                            if hasattr(server_content, 'model_turn') and server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    # Text
                                    if hasattr(part, 'text') and part.text:
                                        accumulated_text += part.text
                                        yield LiveVoiceResponse(
                                            text=part.text,
                                            is_complete=False,
                                            session_id=session_id,
                                            turn_id=turn_id,
                                            user_id=user_id,
                                        )

                                    # Audio (inline_data)
                                    if hasattr(part, 'inline_data') and part.inline_data:
                                        audio_chunk = part.inline_data.data
                                        accumulated_audio += audio_chunk
                                        usage.output_audio_duration_ms += self._estimate_audio_duration(audio_chunk)

                                        yield LiveVoiceResponse(
                                            text="",
                                            audio_data=audio_chunk,
                                            is_complete=False,
                                            session_id=session_id,
                                            turn_id=turn_id,
                                            user_id=user_id,
                                        )

                        # Handle input transcription (user's speech)
                        # It's in server_content, not at response level!
                        if hasattr(server_content, 'input_transcription') and server_content.input_transcription:
                            text = getattr(server_content.input_transcription, 'text', '')
                            if text:
                                self.logger.info(f"User transcription: {text}")
                                turn_metadata.input_transcription = text
                                yield LiveVoiceResponse(
                                    text="",
                                    is_complete=False,
                                    metadata={"user_transcription": text},
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                )

                        # Handle output transcription (model's speech)
                        # It's in server_content, not at response level!
                        if hasattr(server_content, 'output_transcription') and server_content.output_transcription:
                            text = getattr(server_content.output_transcription, 'text', '')
                            if text:
                                self.logger.info(f"Model transcription: {text}")
                                turn_metadata.output_transcription = text
                                # Yield immediately so frontend receives it
                                yield LiveVoiceResponse(
                                    text="",
                                    is_complete=False,
                                    metadata={"assistant_transcription": text},
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                )

                        # Handle tool calls
                        if hasattr(response, 'tool_call') and response.tool_call:
                            self.logger.info(f"Tool call received: {response.tool_call}")
                            adapter = self._get_tool_adapter()

                            for fc in response.tool_call.function_calls:
                                self.logger.info(f"Executing tool: {fc.name} with args: {dict(fc.args) if fc.args else {}}")
                                tool_call = LiveToolCall(
                                    id=fc.id,
                                    name=fc.name,
                                    arguments=dict(fc.args) if fc.args else {}
                                )
                                tool_calls_list.append(tool_call)
                                turn_metadata.tool_calls_count += 1

                                # Execute tool via adapter (uses tool_manager)
                                start = datetime.now()
                                func_response = await adapter.execute_tool(fc)
                                tool_call.execution_time_ms = (datetime.now() - start).total_seconds() * 1000
                                tool_call.result = func_response.response

                                usage.tool_calls_executed += 1
                                usage.tool_execution_time_ms += tool_call.execution_time_ms

                                # Send response back to model
                                await session.send_tool_response(
                                    function_responses=[func_response]
                                )

                                # Yield tool call event
                                yield LiveVoiceResponse(
                                    text="",
                                    tool_calls=[tool_call],
                                    is_complete=False,
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                )

                        # Handle usage metadata if available
                        if hasattr(response, 'usage_metadata') and response.usage_metadata:
                            usage = LiveCompletionUsage.from_gemini_usage(response.usage_metadata)

                        # Handle GoAway (session ending)
                        if hasattr(response, 'go_away') and response.go_away:
                            self.logger.info("Received GoAway from server")
                            yield LiveVoiceResponse(
                                text="",
                                is_complete=True,
                                metadata={"go_away": True, "reason": str(response.go_away)},
                                session_id=session_id,
                                turn_id=turn_id,
                                user_id=user_id,
                            )
                            break

                finally:
                    sender_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender_task

        except asyncio.CancelledError:
            self.logger.info(f"Voice session {session_id} cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Voice session error: {e}")

            # Check for unsupported language error
            error_str = str(e).lower()
            is_language_error = "unsupported language" in error_str
            is_retryable = not is_language_error  # Language errors are not retryable

            yield LiveVoiceResponse(
                text="",
                is_complete=True,
                metadata={
                    "error": str(e),
                    "is_retryable": is_retryable,
                    "error_type": "unsupported_language" if is_language_error else "unknown",
                },
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )

    async def _audio_sender(
        self,
        session,
        audio_iterator: AsyncIterator[bytes]
    ) -> None:
        """Send audio chunks to the Gemini session.

        For multi-turn support:
        - Receives audio chunks via iterator
        - When iterator yields None (sentinel), sends audio_stream_end
        - Continues to listen for next turn's audio
        - Only exits when iterator completes (shutdown)
        """
        chunks_sent = 0
        total_bytes = 0
        audio_stream_ended = False

        try:
            async for chunk in audio_iterator:
                if chunk is None:
                    # Sentinel value - end of turn's audio
                    if chunks_sent > 0 and not audio_stream_ended:
                        self.logger.info(
                            f"Turn audio complete: {total_bytes} bytes in {chunks_sent} chunks. "
                            f"Sending audio_stream_end signal..."
                        )
                        try:
                            await asyncio.wait_for(
                                session.send_realtime_input(audio_stream_end=True),
                                timeout=5.0
                            )
                            self.logger.info("audio_stream_end sent successfully")
                            audio_stream_ended = True
                        except asyncio.TimeoutError:
                            self.logger.error("TIMEOUT sending audio_stream_end - Gemini may not respond!")
                        except Exception as e:
                            self.logger.error(f"Error sending audio_stream_end: {e}")
                else:
                    # Real audio chunk
                    await session.send(
                        input={"data": chunk, "mime_type": "audio/pcm"}
                    )
                    chunks_sent += 1
                    total_bytes += len(chunk)
                    # Reset flag for new audio turn
                    audio_stream_ended = False

            # Iterator completed - send final audio_stream_end if needed
            if chunks_sent > 0 and not audio_stream_ended:
                self.logger.info("Audio iterator completed, sending final audio_stream_end...")
                try:
                    await asyncio.wait_for(
                        session.send_realtime_input(audio_stream_end=True),
                        timeout=5.0
                    )
                    self.logger.info("Final audio_stream_end sent successfully")
                except Exception as e:
                    # Expected during session close - downgrade to debug
                    error_str = str(e).lower()
                    if "1011" in str(e) or "closed" in error_str:
                        self.logger.debug(f"Session closed before audio_stream_end: {e}")
                    else:
                        self.logger.error(f"Error sending final audio_stream_end: {e}")

        except asyncio.CancelledError:
            # Even on cancel, try to send audio_stream_end if we sent audio
            if chunks_sent > 0 and not audio_stream_ended:
                try:
                    await asyncio.wait_for(
                        session.send_realtime_input(audio_stream_end=True),
                        timeout=2.0
                    )
                except Exception:
                    pass
        except Exception as e:
            self.logger.error(f"Audio sender error: {e}")

    def _estimate_audio_duration(self, audio_data: bytes) -> float:
        """Estimate audio duration in milliseconds (24kHz 16-bit PCM)."""
        samples = len(audio_data) / 2  # 16-bit = 2 bytes per sample
        return (samples / 24000) * 1000

    async def ask(
        self,
        question: str,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs
    ) -> AsyncIterator[LiveVoiceResponse]:
        """
        Send text input and receive voice response.

        Useful for testing or text-to-speech scenarios.

        Args:
            question: Text input to send
            system_prompt: Optional system instructions
            session_id: Session identifier
            user_id: User identifier
            **kwargs: Additional configuration

        Yields:
            LiveVoiceResponse objects with audio output
        """
        if not self.client:
            self.client = await self.get_client()

        session_id = session_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        live_config = self._build_live_config(
            system_prompt=system_prompt,
            **kwargs
        )

        self.logger.info(
            f"Starting text-to-speech session {session_id}"
        )

        try:
            async with self.client.aio.live.connect(
                model=self.model,
                config=live_config
            ) as session:
                # Send text
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=question)]
                    ),
                    turn_complete=True
                )

                accumulated_audio = b""
                accumulated_text = ""
                tool_calls_list = []

                async for response in session.receive():
                    if response.server_content:
                        server_content = response.server_content



                        if hasattr(server_content, 'model_turn') and server_content.model_turn:
                            for part in server_content.model_turn.parts:
                                if hasattr(part, 'text') and part.text:
                                    accumulated_text += part.text
                                    yield LiveVoiceResponse(
                                        text=part.text,
                                        is_complete=False,
                                        session_id=session_id,
                                        turn_id=turn_id,
                                        user_id=user_id,
                                    )

                                if hasattr(part, 'inline_data') and part.inline_data:
                                    audio_chunk = part.inline_data.data
                                    accumulated_audio += audio_chunk
                                    yield LiveVoiceResponse(
                                        text="",
                                        audio_data=audio_chunk,
                                        is_complete=False,
                                        session_id=session_id,
                                        turn_id=turn_id,
                                        user_id=user_id,
                                    )

                    # Handle tool calls
                    if hasattr(response, 'tool_call') and response.tool_call:
                        adapter = self._get_tool_adapter()

                        for fc in response.tool_call.function_calls:
                            tool_call = LiveToolCall(
                                id=fc.id,
                                name=fc.name,
                                arguments=dict(fc.args) if fc.args else {}
                            )
                            tool_calls_list.append(tool_call)

                            func_response = await adapter.execute_tool(fc)
                            tool_call.result = func_response.response

                            await session.send_tool_response(
                                function_responses=[func_response]
                            )

                            # Reset text accumulator after tool call to capture only the final answer
                            accumulated_text = ""
                            
                            # Inject tool output as initial part of the answer
                            if isinstance(tool_call.result, dict) and "output" in tool_call.result:
                                tool_output_text = str(tool_call.result["output"]) + "\n\n"
                                accumulated_text += tool_output_text
                                yield LiveVoiceResponse(
                                    text=tool_output_text,
                                    is_complete=False,
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                )

                            yield LiveVoiceResponse(
                                text="",
                                tool_calls=[tool_call],
                                is_complete=False,
                                session_id=session_id,
                                turn_id=turn_id,
                                user_id=user_id,
                            )

                        # Check for turn_complete ONLY if we didn't just handle a tool call
                        # If we handled a tool call, we sent a response and expect the model to continue
                        if getattr(server_content, 'turn_complete', False):
                            yield LiveVoiceResponse(
                                text=accumulated_text,
                                audio_data=accumulated_audio or None,
                                is_complete=True,
                                tool_calls=tool_calls_list,
                                session_id=session_id,
                                turn_id=turn_id,
                                user_id=user_id,
                            )
                            break

        except Exception as e:
            self.logger.error(f"Text session error: {e}")
            yield LiveVoiceResponse(
                text="",
                is_complete=True,
                metadata={"error": str(e)},
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )

    async def close(self) -> None:
        """Close the client and clean up resources."""
        if self.client:
            with contextlib.suppress(Exception):
                if hasattr(self.client, '_api_client'):
                    api_client = self.client._api_client
                    if hasattr(api_client, '_aiohttp_session'):
                        await api_client._aiohttp_session.close()

        # Call parent close
        await super().close()
        self.logger.info("GeminiLiveClient closed")

    async def ask_stream(self, *args, **kwargs):
        """Deprecated alias for stream_voice."""
        self.logger.warning("ask_stream() is deprecated. Use stream_voice() instead.")
        async for response in self.stream_voice(*args, **kwargs):
            yield response

    async def batch_ask(self, *args, **kwargs):
        """Deprecated alias for send_text."""
        self.logger.warning("batch_ask() is deprecated. Use send_text() instead.")
        async for response in self.ask(*args, **kwargs):
            yield response

# =============================================================================
# Factory function
# =============================================================================

def create_live_client(
    model: Optional[Union[str, GoogleVoiceModel]] = None,
    voice_name: str = "Puck",
    tools: Optional[List[AbstractTool]] = None,
    use_tools: bool = True,
    **kwargs
) -> GeminiLiveClient:
    """
    Factory function to create a GeminiLiveClient.

    Args:
        model: Model identifier (defaults to latest native audio)
        voice_name: Voice for synthesis
        tools: List of tools to register
        use_tools: Enable tool usage
        **kwargs: Additional client configuration

    Returns:
        Configured GeminiLiveClient instance
    """
    return GeminiLiveClient(
        model=model,
        voice_name=voice_name,
        tools=tools,
        use_tools=use_tools,
        **kwargs
    )


# =============================================================================
# __all__ for clean imports
# =============================================================================
__all__ = [
    # Client
    "GeminiLiveClient",
    "create_live_client",
    # Models
    "GoogleVoiceModel",
    "LiveVoiceResponse",
    "LiveCompletionUsage",
    "LiveToolCall",
    "VoiceTurnMetadata",
    # Adapter
    "LiveToolAdapter",
]
