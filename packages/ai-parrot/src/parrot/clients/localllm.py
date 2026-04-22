"""LocalLLM client for AI-Parrot.

Extends OpenAIClient to support local/self-hosted OpenAI-compatible LLM
servers such as Ollama, vLLM, llama.cpp, and LM Studio.
"""
from typing import Any, Dict, List, Optional, Union
from enum import Enum
from logging import getLogger

from openai import AsyncOpenAI
from navconfig import config

from .gpt import OpenAIClient, STRUCTURED_OUTPUT_COMPATIBLE_MODELS
from ..models.localllm import LocalLLMModel
from ..models import CompletionUsage, StructuredOutputConfig
from ..models.responses import InvokeResult
from ..exceptions import InvokeError

logger = getLogger(__name__)


class LocalLLMClient(OpenAIClient):
    """Client for local/self-hosted OpenAI-compatible LLM servers.

    Extends OpenAIClient with local-server-friendly defaults:
    - No API key required (optional)
    - Configurable base_url (defaults to vLLM's ``http://localhost:8000/v1``)
    - Higher timeout (120s vs 60s for cloud)
    - Responses API disabled (local servers don't support it)
    - Relaxed structured output model guard

    Supports Ollama, vLLM, llama.cpp, LM Studio, and any server that
    exposes an OpenAI-compatible ``/v1`` API.

    Args:
        api_key: Optional API key. Defaults to None (most local servers
            don't require authentication). Falls back to
            ``LOCAL_LLM_API_KEY`` env var.
        base_url: Base URL of the local server. Defaults to
            ``http://localhost:8000/v1``. Falls back to
            ``LOCAL_LLM_BASE_URL`` env var.
        model: Default model to use. Falls back to ``LOCAL_LLM_MODEL``
            env var, then ``llama3.1:8b``.
        **kwargs: Additional arguments passed to OpenAIClient.

    Example:
        >>> client = LocalLLMClient()
        >>> response = await client.ask("Hello!")

        >>> # Point to Ollama
        >>> client = LocalLLMClient(
        ...     base_url="http://localhost:11434/v1",
        ...     model="llama3.1:8b"
        ... )
    """

    client_type: str = "localllm"
    client_name: str = "localllm"
    model: str = LocalLLMModel.LLAMA3_1_8B.value
    # None — _resolve_invoke_model() falls back to self.model
    _lightweight_model: Optional[str] = None
    _default_model: str = "llama3.1:8b"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ):
        resolved_key = api_key or config.get('LOCAL_LLM_API_KEY') or None
        resolved_url = (
            base_url
            or config.get('LOCAL_LLM_BASE_URL')
            or 'http://localhost:8000/v1'
        )
        resolved_model = (
            model
            or kwargs.pop('model', None)
            or config.get('LOCAL_LLM_MODEL')
            or self._default_model
        )
        kwargs['model'] = resolved_model
        super().__init__(
            api_key=resolved_key,
            base_url=resolved_url,
            **kwargs
        )
        # Re-set after super().__init__ because AbstractClient may overwrite
        self.api_key = resolved_key
        self.base_url = resolved_url

    async def get_client(self) -> AsyncOpenAI:
        """Initialize AsyncOpenAI with local server URL.

        Uses ``"no-key"`` as a placeholder when no API key is provided,
        since some servers require a non-empty bearer token.

        Returns:
            AsyncOpenAI client configured for the local server.
        """
        return AsyncOpenAI(
            api_key=self.api_key or "no-key",
            base_url=self.base_url,
            timeout=config.get('LOCAL_LLM_TIMEOUT', 120),
        )

    def _is_responses_model(self, model_str: str) -> bool:
        """Always returns False.

        Local servers don't support OpenAI's Responses API, so all
        requests go through the Chat Completions path.

        Args:
            model_str: Model identifier string (ignored).

        Returns:
            False, always.
        """
        return False

    async def ask(
        self,
        prompt: str,
        model: Union[str, LocalLLMModel] = None,
        **kwargs
    ):
        """Ask the local LLM a question.

        Overrides OpenAIClient.ask() to use the local default model
        and skip structured output model guards.

        Args:
            prompt: The prompt to send to the model.
            model: Model to use. Defaults to the client's configured model.
            **kwargs: Additional arguments passed to OpenAIClient.ask().

        Returns:
            AIMessage with the model's response.
        """
        if model is None:
            model = self.model or self._default_model
        elif isinstance(model, Enum):
            model = model.value
        return await super().ask(prompt, model=model, **kwargs)

    async def ask_stream(
        self,
        prompt: str,
        model: Union[str, LocalLLMModel] = None,
        **kwargs
    ):
        """Stream the local LLM's response.

        Overrides OpenAIClient.ask_stream() to use the local default model.

        Args:
            prompt: The prompt to send to the model.
            model: Model to use. Defaults to the client's configured model.
            **kwargs: Additional arguments passed to OpenAIClient.ask_stream().

        Yields:
            Text chunks from the streaming response.
        """
        if model is None:
            model = self.model or self._default_model
        elif isinstance(model, Enum):
            model = model.value
        async for chunk in super().ask_stream(prompt, model=model, **kwargs):
            yield chunk

    async def list_models(self) -> List[str]:
        """List models available on the local server.

        Queries the server's ``/v1/models`` endpoint via the OpenAI SDK.

        Returns:
            List of model ID strings available on the server.

        Raises:
            Exception: If the server is unreachable or returns an error.
        """
        await self._ensure_client()
        models = await self.client.models.list()
        return [m.id for m in models.data]

    async def health_check(self) -> bool:
        """Check if the local server is reachable.

        Attempts to list models as a connectivity test.

        Returns:
            True if the server responds, False otherwise.
        """
        try:
            await self.list_models()
            return True
        except Exception:
            return False

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
    ) -> InvokeResult:
        """Lightweight stateless invocation for LocalLLMClient.

        Attempts native OpenAI-compatible ``json_schema`` response_format for
        structured output.  If the local server rejects ``response_format``
        (e.g., vLLM with older models), falls back to schema-in-system-prompt
        (same strategy as AnthropicClient).

        ``_lightweight_model`` is ``None`` so the model falls back to
        ``self.model`` — the user controls which local model to deploy.

        Args:
            prompt: User prompt.
            output_type: Pydantic model or dataclass to parse the response into.
            structured_output: Full :class:`StructuredOutputConfig`; takes
                precedence over ``output_type``.
            model: Model override. Falls back to ``self.model``.
            system_prompt: System prompt override.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            use_tools: Whether to inject registered tools.
            tools: Additional tool definitions.

        Returns:
            :class:`InvokeResult` with parsed output.

        Raises:
            :class:`InvokeError`: On provider errors.
        """
        resolved_prompt = self._resolve_invoke_system_prompt(system_prompt)
        config = self._build_invoke_structured_config(output_type, structured_output)
        resolved_model = self._resolve_invoke_model(model)

        if not self.client:
            raise InvokeError(
                "LocalLLMClient not initialised. Use async context manager.",
                original=RuntimeError("client is None"),
            )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": resolved_prompt},
            {"role": "user", "content": prompt},
        ]

        kwargs: Dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if use_tools:
            tool_defs = self._prepare_tools()
            if tool_defs:
                kwargs["tools"] = tool_defs

        try:
            # Attempt OpenAI-compatible json_schema for structured output
            if config:
                schema = config.get_schema()
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": config.output_type.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                }

            response = await self.client.chat.completions.create(**kwargs)
            raw_text = response.choices[0].message.content or ""

            output: Any = raw_text
            if config:
                if config.custom_parser:
                    output = config.custom_parser(raw_text)
                else:
                    output = await self._parse_structured_output(raw_text, config)

            usage = CompletionUsage.from_openai(response.usage)
            return self._build_invoke_result(
                output, output_type, resolved_model, usage, response
            )
        except InvokeError:
            raise
        except Exception as exc:
            if config and "response_format" in str(exc):
                # Fallback: schema-in-prompt (server doesn't support json_schema)
                return await self._invoke_with_schema_in_prompt(
                    prompt=prompt,
                    config=config,
                    system_prompt=resolved_prompt,
                    model=resolved_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    output_type=output_type,
                )
            raise self._handle_invoke_error(exc)

    async def _invoke_with_schema_in_prompt(
        self,
        prompt: str,
        config: StructuredOutputConfig,
        system_prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        output_type: Optional[type],
    ) -> InvokeResult:
        """Fallback invoke using schema-in-system-prompt (no response_format).

        Used when the local server does not support OpenAI's ``response_format``
        with ``json_schema``.  Appends the schema description to the system
        prompt and asks the model to respond in JSON.

        Args:
            prompt: Original user prompt.
            config: Structured output configuration.
            system_prompt: Already-resolved system prompt.
            model: Resolved model identifier.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            output_type: Target output type for the result.

        Returns:
            :class:`InvokeResult` with parsed output.

        Raises:
            :class:`InvokeError`: On provider errors during fallback call.
        """
        try:
            schema_instruction = config.format_schema_instruction()
            augmented_prompt = system_prompt + "\n\n" + schema_instruction

            messages: List[Dict[str, Any]] = [
                {"role": "system", "content": augmented_prompt},
                {"role": "user", "content": prompt},
            ]
            fallback_kwargs: Dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            response = await self.client.chat.completions.create(**fallback_kwargs)
            raw_text = response.choices[0].message.content or ""

            output: Any = raw_text
            if config.custom_parser:
                output = config.custom_parser(raw_text)
            else:
                output = await self._parse_structured_output(raw_text, config)

            usage = CompletionUsage.from_openai(response.usage)
            return self._build_invoke_result(output, output_type, model, usage, response)
        except InvokeError:
            raise
        except Exception as exc:
            raise self._handle_invoke_error(exc)
