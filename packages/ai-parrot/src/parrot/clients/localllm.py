"""LocalLLM client for AI-Parrot.

Extends OpenAIClient to support local/self-hosted OpenAI-compatible LLM
servers such as Ollama, vLLM, llama.cpp, and LM Studio.
"""
from typing import List, Optional, Union
from enum import Enum
from logging import getLogger

from openai import AsyncOpenAI
from navconfig import config

from .gpt import OpenAIClient, STRUCTURED_OUTPUT_COMPATIBLE_MODELS
from ..models.localllm import LocalLLMModel

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
        if self.client is None:
            self.client = await self.get_client()
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
