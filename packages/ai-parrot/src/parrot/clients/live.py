"""
GeminiLiveClient - Live/Realtime API Client for AI-Parrot

Inherits from AbstractClient to maintain consistency with the AI-Parrot
ecosystem while supporting the unique requirements of voice streaming.

Key Features:
- Inherits from AbstractClient (same as GoogleGenAIClient, AnthropicClient, etc.)
- Reuses tool_manager and the preset system
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

import asyncio
import base64
import contextlib
import inspect
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Dict,
    List,
    Optional,
    Union,
    Sequence,
)

from google import genai
from google.genai import types
from google.oauth2 import service_account
from navconfig import config

from ..memory.render import HistoryMessage
# FEAT-524: ids are no longer ask() parameters; they come from the per-call
# ContextVars BaseBot binds (FEAT-228).
from parrot.observability.context import current_session_id, current_user_id
from ..models.google import ALL_VOICE_PROFILES, GoogleVoiceModel
from ..models.voice import (
    AudioFormat, VoiceCapabilities, VoiceProvider, VoiceStreamOptions,
)
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.manager import ToolManager

# Import from parrot framework
from .base import AbstractClient

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

    # Speaker attribution (FEAT-408, canonicalized lowercase in FEAT-418)
    role: Optional[str] = None
    """Speaker this frame is attributed to: "user" or "assistant" (canonical
    lowercase form, FEAT-418). GeminiLiveClient sets this on every
    model-originated and user-transcription frame as of FEAT-418
    (previously always None here; user transcription instead traveled via
    the now-removed metadata["user_transcription"])."""

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
            "role": self.role,
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
        if hasattr(tool, 'get_schema'):
            full_schema = tool.get_schema()
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
    ) -> tuple[types.FunctionResponse, Optional[Dict[str, Any]]]:
        """
        Execute a tool call and return a (FunctionResponse, display_data) tuple.
        """
        tool_name = function_call.name
        tool_id = function_call.id
        tool_args = dict(function_call.args) if function_call.args else {}

        # Merge context into arguments if provided
        if context:
            # Securely inject context variables, overriding any LLM-provided values
            # This prevents the LLM from hallucinating session IDs (e.g. "sess456")
            for key, value in context.items():
                if value is not None:
                    # We unconditionally overwrite LLM-provided args with trusted context
                    tool_args[key] = value

        try:
            tool = self.tool_map.get(tool_name)

            if tool is None:
                return types.FunctionResponse(
                    name=tool_name,
                    id=tool_id,
                    response={"error": f"Tool '{tool_name}' not found"}
                )

            # Execute the tool
            if isinstance(tool, AbstractTool):
                # FEAT-380 (TASK-1956, Q4): route through AbstractTool.execute()
                # instead of the private `_execute()` — restores permission
                # checks (Layer 2), the credential broker, secret/PII
                # redaction, and lifecycle events (FEAT-176), none of which
                # the private call went through. `execute()` always returns
                # a standardized `ToolResult` (never raises for expected
                # failure modes — `status='forbidden'`/`'error'` are both
                # handled generically by the `else` branch below), so
                # `voice_text`/`display_data` are read from THIS ToolResult's
                # own fields further down, uncompressed — this path does not
                # go through `ToolManager.execute_tool()` (and therefore not
                # through the compression stage), because that method's
                # return contract only exposes the post-compression
                # `result.result` payload, discarding `voice_text`/
                # `display_data` entirely; routing through it here would
                # silently break the voice UX. See TASK-1956 Completion Note.
                result = await tool.execute(**tool_args)
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
            display_data = None
            
            if isinstance(result, ToolResult):
                if result.status == "success":
                    
                    # Extract display data if available
                    if result.display_data:
                        display_data = result.display_data
                        
                    # Use voice_text as the primary response if available
                    if result.voice_text:
                        response_data = {"output": result.voice_text}
                    # Ensure response is always a dict
                    elif isinstance(result.result, dict):
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
            ), display_data

        except Exception as e:
            if self.logger:
                self.logger.error(f"Tool execution error for {tool_name}: {e}")
            return types.FunctionResponse(
                name=tool_name,
                id=tool_id,
                response={"error": str(e)}
            ), None


# =============================================================================
# GeminiLiveClient - Main Client Implementation
# =============================================================================

class GeminiLiveClient(AbstractClient):
    """
    Client for Gemini Live API voice interactions.

    Inherits from AbstractClient to maintain consistency with the AI-Parrot
    ecosystem. Reuses tool_manager and credential
    patterns from GoogleGenAIClient.

    Key features:
    - Inherits tool_manager from AbstractClient (FEAT-524: clients are
      memory-less; live.py keeps its own realtime session model instead)
    - Uses same credential system (api_key, vertexai, credentials_file)
    - Integrates AbstractTool via LiveToolAdapter
    - Returns LiveVoiceResponse with usage metadata

    Cross-loop reuse:
        The base per-loop cache (``AbstractClient._ensure_client``) transparently
        builds a new ``genai.Client`` for each event loop this wrapper is used
        from. That cache is safe for the setup client.

        The LiveConnect WebSocket session, however, is created inside the
        ``async with`` body of a specific call and **cannot be migrated to a
        different loop**. Always open LiveConnect (and consume its stream) on
        a single loop. Do not attempt to resume a Live session from a
        background task running on a fresh loop — use a new session instead.

        ``close()`` is inherited from ``AbstractClient`` and tears down every
        cached ``genai.Client``. Entries whose owning loop is no longer
        running are dropped without awaiting.

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

        # Session resumption handle (FEAT-418, TASK-2168). Retained across
        # stream_voice() calls on this client instance so a reconnect can
        # resume with context instead of a cold start. Cleared when a
        # handle is rejected/expired by the server.
        self._resumption_handle: Optional[str] = None

        # Silence websockets.client debug logs
        logging.getLogger("websockets.client").setLevel(logging.INFO)

    @property
    def voice_capabilities(self) -> VoiceCapabilities:
        """Describe what Gemini Live natively supports today (FEAT-418).

        This descriptor reflects *current* behavior only — flags below are
        flipped to ``True`` by later FEAT-418 tasks as each capability is
        actually implemented. ``supports_top_p``/``supports_per_call_inference``
        are ``True`` as of TASK-2166 (per-call ``temperature``/``max_tokens``/
        ``top_p`` now reach ``_build_live_config()``); ``supports_per_call_voice``
        is ``True`` as of TASK-2167 (per-call voice override, validated
        against ``voice_catalog`` with a warned fallback) — canonical
        ``role`` also lands in TASK-2167; ``emits_reconnect_signal``/
        ``supports_session_resumption`` are ``True`` as of TASK-2168
        (``GoAway``/1008-close now also set
        ``metadata["reconnect_required"]``, and a session-resumption
        handle is requested on every connect and retained across
        reconnects). The provider conformance kit (TASK-2176) asserts
        descriptor-vs-behavior consistency, so this must never claim a
        capability ahead of the code that provides it.

        Returns:
            A frozen ``VoiceCapabilities`` instance for
            ``VoiceProvider.GOOGLE_LIVE``.
        """
        return VoiceCapabilities(
            provider=VoiceProvider.GOOGLE_LIVE,
            native_stt_only=True,
            supports_top_p=True,
            supports_per_call_voice=True,
            supports_per_call_inference=True,
            parallel_tool_execution=True,
            emits_reconnect_signal=True,
            supports_session_resumption=True,
            # google-genai's own docs attribute the Live API's fixed
            # session-length limit to NOT using context-window
            # compression; this client's _build_live_config() always
            # requests context_window_compression with a sliding window
            # (unconditional, pre-dates this task), so no fixed ceiling
            # applies here — None per spec §3 Module 5 ("or None if the
            # provider documents none under context-window compression").
            max_session_seconds=None,
            max_output_tokens=self.max_tokens,
            input_formats=frozenset({AudioFormat.PCM_16K}),
            output_formats=frozenset({AudioFormat.PCM_24K}),
            input_sample_rates=frozenset({16000}),
            output_sample_rates=frozenset({24000}),
            voice_catalog=frozenset(
                profile.voice_name for profile in ALL_VOICE_PROFILES
            ),
            default_voice="Puck",
        )

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

    def _resolve_voice_name(self, requested: Optional[str]) -> str:
        """Resolve the effective voice name for a call (FEAT-418).

        Validates ``requested`` against ``voice_capabilities.voice_catalog``
        (seeded from ``parrot.models.google.ALL_VOICE_PROFILES``). An
        out-of-catalog name warns once and falls back to the constructor's
        ``self.voice_name`` rather than being passed through to the Live
        API unvalidated — never mutates ``self.voice_name``, so concurrent
        sessions on this client cannot interfere with each other.

        Args:
            requested: The per-call voice override, or ``None`` to use the
                constructor's default.

        Returns:
            The voice name to use for this call.
        """
        if requested is None:
            return self.voice_name
        if requested in self.voice_capabilities.voice_catalog:
            return requested
        self.logger.warning(
            "GeminiLiveClient: voice %r is not in the known catalog; "
            "falling back to %r",
            requested, self.voice_name,
        )
        return self.voice_name

    def _build_live_config(
        self,
        system_prompt: Optional[str] = None,
        response_modalities: Optional[List[str]] = None,
        stt_only: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        enable_input_transcription: bool = True,
        enable_output_transcription: bool = True,
        voice: Optional[str] = None,
    ) -> types.LiveConnectConfig:
        """Build the LiveConnectConfig for a session.

        Args:
            system_prompt: Optional system instructions for the model.
            response_modalities: Override the response modalities list.
            stt_only: When True, configure for Speech-to-Text-only mode:
                input transcription is enabled but no model response is
                generated (response_modalities set to empty list so Gemini
                transcribes without answering).  Default False = full-duplex.
            temperature: Per-call sampling temperature. Falls back to the
                constructor's ``self.temperature`` when ``None`` (FEAT-418
                — previously this method always used the constructor
                value, ignoring any per-call override).
            max_tokens: Per-call max output tokens. Falls back to the
                constructor's ``self.max_tokens`` when ``None`` (FEAT-418).
            top_p: Per-call nucleus-sampling value. Falls back to the
                constructor's ``self.top_p`` when ``None``. Previously
                ``top_p`` never reached ``LiveConnectConfig`` at all
                (FEAT-418).
            enable_input_transcription: Whether to request input audio
                transcription. Default ``True`` matches today's
                unconditional behavior (FEAT-418 — previously this method
                had no such parameter; ``stream_voice()`` forwarding it
                raised ``TypeError``).
            enable_output_transcription: Whether to request output audio
                transcription. Default ``True`` matches today's behavior.
                ``stt_only=True`` still wins over this flag: output
                transcription stays disabled in STT-only mode regardless
                of this value (preserves ``live.py:711`` semantics).
            voice: Per-call voice name override (FEAT-418). Falls back to
                the constructor's ``self.voice_name`` when ``None`` and
                does NOT mutate ``self.voice_name`` — resolved locally so
                concurrent sessions on one client don't interfere.
                Validated against ``voice_capabilities.voice_catalog``; an
                out-of-catalog name warns and falls back to
                ``self.voice_name`` rather than being passed through
                unvalidated.
        """
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        top_p = top_p if top_p is not None else self.top_p
        resolved_voice_name = self._resolve_voice_name(voice)
        # Speech configuration
        speech_config = types.SpeechConfig(
            language_code=self.language,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=resolved_voice_name
                )
            )
        )

        if stt_only:
            # STT-only: suppress model response by requesting no output modalities.
            # Gemini will still transcribe input audio via input_audio_transcription.
            # We explicitly pass an empty list — the caller never overrides this in
            # STT-only mode, so response_modalities kwarg is ignored.
            modalities: List[str] = []
            self.logger.info("GeminiLiveClient: STT-only mode — model response suppressed")
        else:
            # Full-duplex (default): Native Audio requires AUDIO modality.
            modalities = response_modalities or ["AUDIO"]

        live_config = types.LiveConnectConfig(
            response_modalities=modalities,
            speech_config=speech_config,
            temperature=temperature,
            max_output_tokens=max_tokens,
            top_p=top_p,
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
            # Input transcription, gated by enable_input_transcription
            # (FEAT-418 — previously unconditional regardless of mode).
            input_audio_transcription=(
                types.AudioTranscriptionConfig() if enable_input_transcription else None
            ),
            # Output transcription only makes sense in full-duplex, and
            # stt_only still wins over enable_output_transcription
            # (preserves live.py:711 semantics — FEAT-418).
            output_audio_transcription=(
                None if stt_only or not enable_output_transcription
                else types.AudioTranscriptionConfig()
            ),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            # Session resumption (FEAT-418, TASK-2168): always requested so
            # the server sends session_resumption_update messages; passing
            # the retained handle (if any) lets a reconnect resume with
            # context instead of starting cold. ``handle=None`` on the
            # first connect starts a fresh, resumable session.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resumption_handle,
            ),
        )

        # System prompt
        if system_prompt:
            live_config.system_instruction = system_prompt

        # Tools (if enabled) — not useful in STT-only mode but harmless to register.
        if self.enable_tools:
            adapter = self._get_tool_adapter()
            if declarations := adapter.get_function_declarations():
                live_config.tools = [types.Tool(function_declarations=declarations)]
                self.logger.debug(
                    f"Registered {len(declarations)} tools for Live session"
                )
        return live_config

    async def stream_voice(
        self,
        audio_iterator: AsyncIterator[bytes],
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stt_only: bool = False,
        options: Optional[VoiceStreamOptions] = None,
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
            stt_only: When True, run in STT-only mode: Gemini transcribes input
                but does NOT generate a model response (no response_chunk, no audio
                output).  Only ``role="user"`` transcription frames are emitted
                (FEAT-418 — previously carried in
                ``metadata["user_transcription"]``, now removed).
                Default False = full-duplex (unchanged behavior).
            options: Optional ``VoiceStreamOptions`` projection (FEAT-418).
                ``temperature``/``max_tokens``/``top_p``/``voice``/
                ``enable_input_transcription``/``enable_output_transcription``
                are derived from it when not explicitly present in
                ``**kwargs`` — an explicit kwarg always wins over
                ``options``.
            **kwargs: Additional configuration. ``temperature``,
                ``max_tokens``, ``top_p``, ``voice`` (per-call voice
                override, validated against the descriptor's
                ``voice_catalog``), ``enable_input_transcription``,
                ``enable_output_transcription`` are recognized here and
                take precedence over ``options`` (FEAT-418).

        Yields:
            LiveVoiceResponse objects with audio, text, and usage metadata.
            In STT-only mode, only transcription metadata frames are yielded.
        """
        await self._ensure_client()

        session_id = session_id or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        # FEAT-416 (TASK-2148): gate concurrent tool execution on the
        # VoiceConfig-derived flag (VoiceBot wires this in TASK-2151).
        # Default False preserves current sequential behavior exactly. If
        # the Google SDK only ever sends one function_call per turn, the
        # TaskGroup path is simply never taken (len(function_calls) > 1
        # guard below) — correct either way (spec §8 Q3).
        parallel_tool_execution = kwargs.get("parallel_tool_execution", False)

        # FEAT-418: resolve per-call inference/transcription/voice overrides.
        # Precedence: explicit kwarg > options field > _build_live_config's
        # own fallback to the constructor value (temperature/max_tokens/
        # top_p/voice) or default True (transcription flags).
        live_config_overrides: Dict[str, Any] = {}
        for field_name in (
            "temperature", "max_tokens", "top_p",
            "enable_input_transcription", "enable_output_transcription",
            "voice",
        ):
            if field_name in kwargs:
                live_config_overrides[field_name] = kwargs[field_name]
            elif options is not None:
                live_config_overrides[field_name] = getattr(options, field_name)

        live_config = self._build_live_config(
            system_prompt=system_prompt,
            stt_only=stt_only,
            response_modalities=kwargs.get('response_modalities'),
            **live_config_overrides,
        )

        # In AUDIO mode, model_turn.parts text is the model's internal
        # reasoning ("thinking"), NOT the spoken words.  The actual spoken
        # transcript arrives via output_transcription frames.  We must
        # suppress the thinking text from LiveVoiceResponse.text so that
        # downstream consumers (VoiceBot.ask_stream, memory, frontend)
        # see the real spoken words.
        is_audio_mode = not stt_only and "AUDIO" in (
            live_config.response_modalities or []
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
                        # self.logger.debug(f"Received message: {response}")
                        # Handle server content (audio/text responses)
                        if response.server_content:
                            server_content = response.server_content

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
                                    role="assistant",
                                )
                                continue

                            # Process model turn.
                            # In STT-only mode the config requests no response
                            # modalities so Gemini should not produce a model turn;
                            # guard here as a defense-in-depth safety net.
                            if (
                                not stt_only
                                and hasattr(server_content, 'model_turn')
                                and server_content.model_turn
                            ):
                                for part in server_content.model_turn.parts:
                                    # Text
                                    if hasattr(part, 'text') and part.text:
                                        if is_audio_mode:
                                            # In AUDIO mode, model_turn text
                                            # is the model's internal reasoning
                                            # ("thinking"), NOT the spoken
                                            # response.  The actual spoken text
                                            # arrives via output_transcription
                                            # frames.  Expose as metadata so
                                            # consumers can optionally display
                                            # it, but keep text="" to prevent
                                            # it from being persisted as the
                                            # assistant's reply.
                                            yield LiveVoiceResponse(
                                                text="",
                                                is_complete=False,
                                                metadata={"thinking": part.text},
                                                session_id=session_id,
                                                turn_id=turn_id,
                                                user_id=user_id,
                                                role="assistant",
                                            )
                                        else:
                                            # TEXT mode — model_turn text IS
                                            # the actual response.
                                            accumulated_text += part.text
                                            yield LiveVoiceResponse(
                                                text=part.text,
                                                is_complete=False,
                                                session_id=session_id,
                                                turn_id=turn_id,
                                                user_id=user_id,
                                                role="assistant",
                                            )

                                    # Audio (inline_data)
                                    if hasattr(part, 'inline_data') and part.inline_data:
                                        audio_chunk = part.inline_data.data
                                        accumulated_audio += audio_chunk
                                        duration = self._estimate_audio_duration(audio_chunk)
                                        usage.output_audio_duration_ms += duration

                                        yield LiveVoiceResponse(
                                            text="",
                                            audio_data=audio_chunk,
                                            is_complete=False,
                                            session_id=session_id,
                                            turn_id=turn_id,
                                            user_id=user_id,
                                            role="assistant",
                                        )
                            elif stt_only and hasattr(server_content, 'model_turn') and server_content.model_turn:
                                self.logger.debug(
                                    "STT-only: model_turn received but suppressed (double-brain guard)"
                                )

                            # Handle input transcription (user's speech)
                            # It's in server_content, not at response level!
                            #
                            # FEAT-418: emit the transcript as a canonical
                            # role="user" text response instead of the
                            # provider-specific metadata["user_transcription"]
                            # key (removed — no deprecation window, spec §5).
                            if hasattr(server_content, 'input_transcription') and server_content.input_transcription:
                                text = getattr(server_content.input_transcription, 'text', '')
                                if text:
                                    self.logger.info(f"User transcription: {text}")
                                    turn_metadata.input_transcription = text
                                    yield LiveVoiceResponse(
                                        text=text,
                                        is_complete=False,
                                        session_id=session_id,
                                        turn_id=turn_id,
                                        user_id=user_id,
                                        role="user",
                                    )

                            # Handle output transcription (model's speech)
                            # It's in server_content, not at response level!
                            if hasattr(server_content, 'output_transcription') and server_content.output_transcription:
                                text = getattr(server_content.output_transcription, 'text', '')
                                if text:
                                    self.logger.info(f"Model transcription: {text}")
                                    # Accumulate (not overwrite) — Gemini
                                    # sends multi-chunk transcriptions.
                                    if turn_metadata.output_transcription:
                                        turn_metadata.output_transcription += text
                                    else:
                                        turn_metadata.output_transcription = text
                                    # Also accumulate into accumulated_text so
                                    # interruption responses carry the spoken
                                    # words (not thinking text).
                                    accumulated_text += text
                                    # Yield as canonical assistant text so
                                    # VoiceBot.ask_stream and downstream
                                    # consumers receive the actual spoken words.
                                    yield LiveVoiceResponse(
                                        text=text,
                                        is_complete=False,
                                        session_id=session_id,
                                        turn_id=turn_id,
                                        user_id=user_id,
                                        role="assistant",
                                    )

                            # Check for turn complete (After processing content)
                            if getattr(server_content, 'turn_complete', False):
                                self.logger.debug(f"Turn complete received for {turn_id}")
                                turn_metadata.ended_at = datetime.now()
                                usage.response_time_ms = turn_metadata.duration_ms

                                yield LiveVoiceResponse(
                                    text="",  # accumulated_text was already yielded in chunks
                                    audio_data=None,
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

                        # Handle tool calls
                        if hasattr(response, 'tool_call') and response.tool_call:
                            self.logger.info(f"Tool call received: {response.tool_call}")
                            adapter = self._get_tool_adapter()
                            function_calls = list(response.tool_call.function_calls)

                            async def _run_one_tool_call(
                                fc, turn_id=turn_id, adapter=adapter,
                                session_id=session_id, user_id=user_id,
                            ):
                                # Bind the enclosing loop's turn_id/adapter/
                                # session_id/user_id as defaults (evaluated
                                # once, at definition time) rather than
                                # reading them as free variables — avoids
                                # ruff/flake8-bugbear B023's late-binding
                                # closure warning; this coroutine is always
                                # fully awaited (or collected via TaskGroup)
                                # within the same outer-loop iteration it was
                                # defined in, so the values never actually
                                # change underneath it, but binding them
                                # explicitly makes that guarantee visible.
                                start = datetime.now()

                                # Create tool call object early
                                tool_call = LiveToolCall(
                                    id=fc.id or str(uuid.uuid4()),  # Ensure ID exists
                                    name=fc.name,
                                    arguments=dict(fc.args) if fc.args else {},
                                )

                                # Pass session context to tool execution
                                tool_context = {
                                    "session_id": session_id,
                                    "user_id": str(user_id) if user_id is not None else None,
                                    "turn_id": turn_id,
                                }
                                # Merge context into args for logging visibility
                                effective_args = dict(fc.args) if fc.args else {}
                                effective_args.update(tool_context)

                                self.logger.info(f"Executing tool: {fc.name} with args: {effective_args}")

                                try:
                                    func_response, display_data = await adapter.execute_tool(
                                        fc,
                                        context=tool_context
                                    )
                                except Exception as exc:
                                    # adapter.execute_tool() already catches
                                    # tool-execution errors internally and
                                    # returns an error-shaped FunctionResponse;
                                    # this is defense-in-depth so one failing
                                    # tool never cancels its TaskGroup siblings
                                    # (FEAT-416 TASK-2148 acceptance criterion).
                                    func_response = types.FunctionResponse(
                                        name=fc.name, id=fc.id,
                                        response={"error": str(exc)},
                                    )
                                    display_data = None
                                tool_call.execution_time_ms = (datetime.now() - start).total_seconds() * 1000
                                tool_call.result = func_response.response
                                return tool_call, func_response, display_data

                            # FEAT-416 (TASK-2148): execute concurrently via
                            # asyncio.TaskGroup when parallel_tool_execution
                            # is set and there's more than one function call
                            # in this turn; otherwise (default, or a single
                            # call) behavior is exactly the previous
                            # sequential await-in-a-loop.
                            if parallel_tool_execution and len(function_calls) > 1:
                                async with asyncio.TaskGroup() as tg:
                                    tasks = [
                                        tg.create_task(_run_one_tool_call(fc))
                                        for fc in function_calls
                                    ]
                                tool_results = [t.result() for t in tasks]

                                # All tool results must reach the model
                                # before it resumes — send them together
                                # in one call (parallel path only).
                                await session.send_tool_response(
                                    function_responses=[
                                        func_response for _, func_response, _ in tool_results
                                    ]
                                )
                            else:
                                # Sequential (default, or a single call):
                                # preserve the previous behavior exactly —
                                # execute and send each tool's response
                                # immediately, one at a time. Code-review
                                # fix: batching the send here (as the
                                # parallel path does) would have changed
                                # the wire-level cadence of
                                # send_tool_response() calls to Gemini for
                                # a multi-tool *sequential* turn — an
                                # existing case Gemini already supports
                                # independent of this feature — with no
                                # test coverage to confirm Gemini tolerates
                                # that change.
                                tool_results = []
                                for fc in function_calls:
                                    result = await _run_one_tool_call(fc)
                                    tool_results.append(result)
                                    await session.send_tool_response(
                                        function_responses=[result[1]]
                                    )

                            for tool_call, _func_response, display_data in tool_results:
                                usage.tool_calls_executed += 1
                                usage.tool_execution_time_ms += tool_call.execution_time_ms

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

                                # Prepare metadata with display_data if present
                                metadata = {}
                                if display_data:
                                    metadata["display_data"] = display_data

                                # Yield tool call event
                                yield LiveVoiceResponse(
                                    text="",
                                    tool_calls=[tool_call],
                                    is_complete=False,
                                    session_id=session_id,
                                    turn_id=turn_id,
                                    user_id=user_id,
                                    metadata=metadata,
                                )

                        # Handle usage metadata if available
                        if hasattr(response, 'usage_metadata') and response.usage_metadata:
                            usage = LiveCompletionUsage.from_gemini_usage(response.usage_metadata)

                        # Retain the session resumption handle (FEAT-418,
                        # TASK-2168) so the NEXT stream_voice() call (a
                        # reconnect, driven by VoiceSession's existing loop)
                        # can resume with context instead of a cold start.
                        if (
                            hasattr(response, 'session_resumption_update')
                            and response.session_resumption_update
                        ):
                            update = response.session_resumption_update
                            if getattr(update, 'resumable', False) and getattr(update, 'new_handle', None):
                                self._resumption_handle = update.new_handle
                                self.logger.debug(
                                    "Session resumption handle updated for %s", session_id
                                )

                        # Handle GoAway (session ending). FEAT-418: also set
                        # metadata["reconnect_required"]=True (keeping
                        # go_away for handler.py:298, which still reacts to
                        # it) so VoiceSession's reconnect loop
                        # (voice/session.py:196-199) fires for Gemini the
                        # same way it already does for Nova.
                        if hasattr(response, 'go_away') and response.go_away:
                            self.logger.info("Received GoAway from server")
                            yield LiveVoiceResponse(
                                text="",
                                is_complete=True,
                                metadata={
                                    "go_away": True,
                                    "reason": str(response.go_away),
                                    "reconnect_required": True,
                                },
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

            # FEAT-418 (TASK-2168): a rejected/expired session-resumption
            # handle. The google-genai SDK does not expose a typed
            # exception for this, so detection is heuristic — only
            # triggered when a resumption was actually attempted (a handle
            # was set for this connect). Clear the stale handle and signal
            # a cold reconnect via the existing reconnect_required path
            # (VoiceSession's loop calls stream_voice() again; the next
            # _build_live_config() call passes handle=None).
            if self._resumption_handle and any(
                keyword in error_str for keyword in ("resumption", "handle", "expired")
            ):
                self.logger.warning(
                    "GeminiLiveClient: session resumption handle rejected/expired "
                    "(%s); clearing and falling back to a cold reconnect.", e,
                )
                self._resumption_handle = None
                yield LiveVoiceResponse(
                    text="",
                    is_complete=True,
                    metadata={"resumed": False, "reconnect_required": True},
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                )
                return

            # Check for WebSocket 1008 (Policy Violation) which Gemini sends on session close sometimes
            # or "Operation is not implemented" which can happen if session state is invalid
            if "1008" in error_str and ("policy violation" in error_str or "operation is not implemented" in error_str):
                self.logger.info(f"Session closed by server (1008): {e}")
                yield LiveVoiceResponse(
                    text="",
                    is_complete=True,
                    metadata={
                        "go_away": True,
                        "reason": "Server closed session (1008)",
                        "reconnect_required": True,
                    },
                    session_id=session_id,
                    turn_id=turn_id,
                    user_id=user_id,
                )
                return

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
        history: Optional[Sequence[HistoryMessage]] = None,
        **kwargs
    ) -> AsyncIterator[LiveVoiceResponse]:
        """
        Send text input and receive voice response.

        Useful for testing or text-to-speech scenarios.

        Args:
            question: Text input to send
            system_prompt: Optional system instructions
            history: Accepted for ``AbstractClient`` conformance (FEAT-524) but
                NOT replayed — the Gemini Live API maintains its own realtime
                session, which spec §1 keeps out of scope.
            **kwargs: Additional configuration

        Yields:
            LiveVoiceResponse objects with audio output
        """
        await self._ensure_client()

        # FEAT-524: ids come from the ContextVars BaseBot binds, not kwargs.
        del history  # not replayed; the Live API owns the session (see docstring)
        user_id = current_user_id.get()
        session_id = current_session_id.get() or str(uuid.uuid4())
        turn_id = str(uuid.uuid4())

        # FEAT-176: lifecycle event — BeforeClientCallEvent
        import time as _lc_time_live
        _lc_tc_live = self._emit_before_call(
            client_name="gemini-live",
            model=self.model or "",
            temperature=None,
            system_prompt=system_prompt,
            has_tools=False,
            parent_trace=None,
        )
        _lc_t0_live = _lc_time_live.perf_counter()

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

                            # Pass session context to tool execution
                            tool_context = {
                                "session_id": session_id,
                                "user_id": str(user_id) if user_id is not None else None,
                                "turn_id": turn_id,
                            }
                            func_response, display_data = await adapter.execute_tool(
                                fc,
                                context=tool_context
                            )
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

                            # Prepare metadata with display_data if present
                            metadata = {}
                            if display_data:
                                metadata["display_data"] = display_data

                            yield LiveVoiceResponse(
                                text="",
                                tool_calls=[tool_call],
                                is_complete=False,
                                session_id=session_id,
                                turn_id=turn_id,
                                user_id=user_id,
                                metadata=metadata
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
            # FEAT-176: lifecycle event — ClientCallFailedEvent
            await self._emit_failed_call(
                _lc_tc_live, client_name="gemini-live", model=self.model or "",
                duration_ms=(_lc_time_live.perf_counter() - _lc_t0_live) * 1000,
                exc=e,
            )
            yield LiveVoiceResponse(
                text="",
                is_complete=True,
                metadata={"error": str(e)},
                session_id=session_id,
                turn_id=turn_id,
                user_id=user_id,
            )
            return

        # FEAT-176: lifecycle event — AfterClientCallEvent
        await self._emit_after_call(
            _lc_tc_live, client_name="gemini-live", model=self.model or "",
            duration_ms=(_lc_time_live.perf_counter() - _lc_t0_live) * 1000,
            input_tokens=None, output_tokens=None, finish_reason=None,
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

    async def invoke(self, *args, **kwargs):
        """Not supported: GeminiLiveClient is a realtime voice client.

        Defined only to satisfy AbstractClient's @abstractmethod contract so the
        class can be instantiated. Use stream_voice() for the realtime flow.
        """
        raise NotImplementedError(
            "GeminiLiveClient is realtime voice — use stream_voice(); "
            "invoke() is not supported."
        )

    async def resume(self, *args, **kwargs):
        """Not supported: GeminiLiveClient does not implement suspend/resume."""
        raise NotImplementedError(
            "GeminiLiveClient does not support suspend/resume."
        )

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
