"""vLLM client for AI-Parrot.

Extends LocalLLMClient to support vLLM-specific features including
guided output (JSON schema, regex, choices), LoRA adapters, extended
sampling parameters, and batch processing.
"""

import asyncio
import os
from enum import Enum
from logging import getLogger
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    List,
    Optional,
    Type,
    Union,
)

import aiohttp
from pydantic import BaseModel

from .localllm import LocalLLMClient
from ..models.vllm import (
    pydantic_to_guided_json,
    VLLMServerInfo,
)
from ..models.responses import AIMessage

logger = getLogger(__name__)


class vLLMClient(LocalLLMClient):
    """vLLM client with vLLM-specific features.

    Extends LocalLLMClient to add:
    - Guided output (JSON schema, regex, choices)
    - LoRA adapter support per request
    - Extended sampling parameters (top_k, min_p, repetition_penalty)
    - Health check and server info endpoints
    - Batch processing for high throughput

    Args:
        base_url: vLLM server URL. Defaults to VLLM_BASE_URL env or
            "http://localhost:8000/v1".
        api_key: Optional API key. Defaults to VLLM_API_KEY env.
        timeout: Request timeout in seconds (default 120).
        **kwargs: Additional arguments passed to LocalLLMClient.

    Example:
        >>> client = vLLMClient()
        >>> response = await client.ask("Hello!")

        >>> # With guided JSON output
        >>> schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        >>> response = await client.ask("Extract name", guided_json=schema)

        >>> # With Pydantic structured output
        >>> class Person(BaseModel):
        ...     name: str
        ...     age: int
        >>> response = await client.ask("Extract person", structured_output=Person)
    """

    client_type: str = "vllm"
    client_name: str = "vllm"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 120,
        **kwargs
    ):
        """Initialize vLLMClient.

        Args:
            base_url: vLLM server URL. Falls back to VLLM_BASE_URL env,
                then LOCAL_LLM_BASE_URL, then "http://localhost:8000/v1".
            api_key: Optional API key. Falls back to VLLM_API_KEY env.
            timeout: Request timeout in seconds.
            **kwargs: Additional arguments for LocalLLMClient.
        """
        # Resolve vLLM-specific env vars first, then fall back to LocalLLM vars
        resolved_url = (
            base_url
            or os.getenv("VLLM_BASE_URL")
            or os.getenv("LOCAL_LLM_BASE_URL")
            or "http://localhost:8000/v1"
        )
        resolved_key = (
            api_key
            or os.getenv("VLLM_API_KEY")
            or os.getenv("LOCAL_LLM_API_KEY")
        )

        super().__init__(
            base_url=resolved_url,
            api_key=resolved_key,
            **kwargs
        )
        self.timeout = timeout

    async def ask(
        self,
        prompt: str,
        model: Optional[Union[str, Enum]] = None,
        # Standard parameters
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        # vLLM-specific: Guided output (mutually exclusive)
        guided_json: Optional[Dict[str, Any]] = None,
        guided_regex: Optional[str] = None,
        guided_choice: Optional[List[str]] = None,
        guided_grammar: Optional[str] = None,
        structured_output: Optional[Type[BaseModel]] = None,
        # vLLM-specific: LoRA
        lora_adapter: Optional[str] = None,
        # vLLM-specific: Extended sampling
        top_k: int = -1,
        min_p: float = 0.0,
        repetition_penalty: float = 1.0,
        length_penalty: float = 1.0,
        **kwargs
    ) -> AIMessage:
        """Send a prompt to vLLM with optional guided output and LoRA support.

        Args:
            prompt: The prompt to send to the model.
            model: Model identifier. Defaults to client's configured model.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            guided_json: JSON schema for constrained generation.
            guided_regex: Regex pattern for constrained generation.
            guided_choice: List of valid output choices.
            guided_grammar: BNF grammar for constrained generation.
            structured_output: Pydantic model class to convert to guided_json.
            lora_adapter: Name of LoRA adapter to use for this request.
            top_k: Top-k sampling (-1 to disable).
            min_p: Minimum probability threshold (0.0 to 1.0).
            repetition_penalty: Repetition penalty (>1.0 discourages).
            length_penalty: Length penalty for beam search.
            **kwargs: Additional arguments passed to parent ask().

        Returns:
            AIMessage with the model's response.

        Raises:
            ValueError: If multiple guided constraints are specified.
            ConnectionError: If the server is unreachable.
            TimeoutError: If the request exceeds timeout.
        """
        # Convert structured_output to guided_json if provided
        if structured_output is not None and guided_json is None:
            guided_json = pydantic_to_guided_json(structured_output)

        # Validate mutually exclusive guided parameters
        guided_count = sum([
            guided_json is not None,
            guided_regex is not None,
            guided_choice is not None,
            guided_grammar is not None,
        ])
        if guided_count > 1:
            raise ValueError(
                "Only one guided constraint can be specified: "
                "guided_json, guided_regex, guided_choice, or guided_grammar"
            )

        # Build extra_body with vLLM-specific parameters
        extra_body = kwargs.pop("extra_body", {}) or {}

        # Add guided output constraint
        if guided_json is not None:
            extra_body["guided_json"] = guided_json
        elif guided_regex is not None:
            extra_body["guided_regex"] = guided_regex
        elif guided_choice is not None:
            extra_body["guided_choice"] = guided_choice
        elif guided_grammar is not None:
            extra_body["guided_grammar"] = guided_grammar

        # Add LoRA adapter request
        if lora_adapter is not None:
            extra_body["lora_request"] = {"lora_name": lora_adapter}

        # Add extended sampling parameters (only non-default values)
        if top_k != -1:
            extra_body["top_k"] = top_k
        if min_p > 0.0:
            extra_body["min_p"] = min_p
        if repetition_penalty != 1.0:
            extra_body["repetition_penalty"] = repetition_penalty
        if length_penalty != 1.0:
            extra_body["length_penalty"] = length_penalty

        # Resolve model
        if model is None:
            model = self.model or self._default_model
        elif isinstance(model, Enum):
            model = model.value

        # Pass extra_body to parent ask()
        return await super().ask(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body if extra_body else None,
            **kwargs
        )

    async def ask_stream(
        self,
        prompt: str,
        model: Optional[Union[str, Enum]] = None,
        # Standard parameters
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        # vLLM-specific: Guided output
        guided_json: Optional[Dict[str, Any]] = None,
        guided_regex: Optional[str] = None,
        guided_choice: Optional[List[str]] = None,
        guided_grammar: Optional[str] = None,
        structured_output: Optional[Type[BaseModel]] = None,
        # vLLM-specific: LoRA
        lora_adapter: Optional[str] = None,
        # vLLM-specific: Extended sampling
        top_k: int = -1,
        min_p: float = 0.0,
        repetition_penalty: float = 1.0,
        length_penalty: float = 1.0,
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Stream response from vLLM with optional guided output and LoRA support.

        Args:
            prompt: The prompt to send to the model.
            model: Model identifier. Defaults to client's configured model.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Maximum tokens to generate.
            guided_json: JSON schema for constrained generation.
            guided_regex: Regex pattern for constrained generation.
            guided_choice: List of valid output choices.
            guided_grammar: BNF grammar for constrained generation.
            structured_output: Pydantic model class to convert to guided_json.
            lora_adapter: Name of LoRA adapter to use for this request.
            top_k: Top-k sampling (-1 to disable).
            min_p: Minimum probability threshold (0.0 to 1.0).
            repetition_penalty: Repetition penalty (>1.0 discourages).
            length_penalty: Length penalty for beam search.
            **kwargs: Additional arguments passed to parent ask_stream().

        Yields:
            Text chunks from the streaming response.

        Raises:
            ValueError: If multiple guided constraints are specified.
            ConnectionError: If the server is unreachable.
            TimeoutError: If the request exceeds timeout.
        """
        # Convert structured_output to guided_json if provided
        if structured_output is not None and guided_json is None:
            guided_json = pydantic_to_guided_json(structured_output)

        # Validate mutually exclusive guided parameters
        guided_count = sum([
            guided_json is not None,
            guided_regex is not None,
            guided_choice is not None,
            guided_grammar is not None,
        ])
        if guided_count > 1:
            raise ValueError(
                "Only one guided constraint can be specified: "
                "guided_json, guided_regex, guided_choice, or guided_grammar"
            )

        # Build extra_body with vLLM-specific parameters
        extra_body = kwargs.pop("extra_body", {}) or {}

        # Add guided output constraint
        if guided_json is not None:
            extra_body["guided_json"] = guided_json
        elif guided_regex is not None:
            extra_body["guided_regex"] = guided_regex
        elif guided_choice is not None:
            extra_body["guided_choice"] = guided_choice
        elif guided_grammar is not None:
            extra_body["guided_grammar"] = guided_grammar

        # Add LoRA adapter request
        if lora_adapter is not None:
            extra_body["lora_request"] = {"lora_name": lora_adapter}

        # Add extended sampling parameters (only non-default values)
        if top_k != -1:
            extra_body["top_k"] = top_k
        if min_p > 0.0:
            extra_body["min_p"] = min_p
        if repetition_penalty != 1.0:
            extra_body["repetition_penalty"] = repetition_penalty
        if length_penalty != 1.0:
            extra_body["length_penalty"] = length_penalty

        # Resolve model
        if model is None:
            model = self.model or self._default_model
        elif isinstance(model, Enum):
            model = model.value

        # Pass extra_body to parent ask_stream()
        async for chunk in super().ask_stream(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body if extra_body else None,
            **kwargs
        ):
            yield chunk

    def _get_base_url_root(self) -> str:
        """Get the base URL without the /v1 suffix.

        Returns:
            Base URL root for non-OpenAI endpoints.
        """
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base

    async def health_check(self) -> bool:
        """Check vLLM server health via /health endpoint.

        vLLM exposes a /health endpoint that returns 200 when the server
        is ready to accept requests.

        Returns:
            True if the server is healthy, False otherwise.
        """
        base = self._get_base_url_root()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/health",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.debug("vLLM health check failed: %s", e)
            return False

    async def server_info(self) -> VLLMServerInfo:
        """Get vLLM server version and configuration.

        Queries the /version endpoint for server metadata.

        Returns:
            VLLMServerInfo with server version and configuration.

        Raises:
            ConnectionError: If the server is unreachable or returns an error.
        """
        base = self._get_base_url_root()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/version",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return VLLMServerInfo(
                            version=data.get("version"),
                            model_id=data.get("model_id"),
                            gpu_memory_utilization=data.get("gpu_memory_utilization"),
                            max_model_len=data.get("max_model_len"),
                            tensor_parallel_size=data.get("tensor_parallel_size"),
                        )
                    raise ConnectionError(
                        f"Failed to get vLLM server info: HTTP {resp.status}"
                    )
        except aiohttp.ClientError as e:
            raise ConnectionError(
                f"Cannot connect to vLLM server at {base}: {e}"
            ) from e

    async def list_models(self) -> List[str]:
        """List available models on the vLLM server.

        Queries the /v1/models endpoint via the OpenAI SDK.

        Returns:
            List of model ID strings available on the server.

        Raises:
            ConnectionError: If the server is unreachable.
        """
        try:
            await self._ensure_client()
            models = await self.client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            raise ConnectionError(
                f"Cannot list models from vLLM server at {self.base_url}: {e}"
            ) from e

    async def batch_process(
        self,
        requests: List[Dict[str, Any]],
        **kwargs
    ) -> List[AIMessage]:
        """Process multiple requests concurrently for optimal throughput.

        vLLM excels at batching requests, and this method leverages
        asyncio.gather to send multiple requests in parallel.

        Args:
            requests: List of request dicts, each containing:
                - prompt (str): Required prompt text
                - model (str, optional): Model identifier
                - temperature (float, optional): Sampling temperature
                - max_tokens (int, optional): Max tokens to generate
                - guided_json (dict, optional): JSON schema constraint
                - guided_regex (str, optional): Regex constraint
                - guided_choice (list, optional): Choice constraint
                - lora_adapter (str, optional): LoRA adapter name
                - Plus any other parameters accepted by ask()
            **kwargs: Default parameters applied to all requests.

        Returns:
            List of AIMessage responses in the same order as requests.

        Raises:
            ValueError: If requests list is empty.

        Example:
            >>> requests = [
            ...     {"prompt": "What is 2+2?"},
            ...     {"prompt": "What is 3+3?", "temperature": 0.5},
            ...     {"prompt": "Extract name", "guided_json": name_schema},
            ... ]
            >>> responses = await client.batch_process(requests)
        """
        if not requests:
            raise ValueError("requests list cannot be empty")

        tasks = []
        for req in requests:
            # Extract prompt without mutating original dict
            prompt = req.get("prompt", "")
            # Merge kwargs with req, excluding prompt from req
            req_params = {k: v for k, v in req.items() if k != "prompt"}
            merged = {**kwargs, **req_params}
            tasks.append(self.ask(prompt=prompt, **merged))

        return await asyncio.gather(*tasks)
