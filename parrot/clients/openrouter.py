"""OpenRouter client for AI-Parrot.

Extends OpenAIClient to route requests through OpenRouter's multi-model
API gateway, providing access to 200+ LLM models via a single endpoint.
"""
from typing import Any, Dict, List, Optional
from logging import getLogger

import aiohttp
from openai import AsyncOpenAI
from navconfig import config

from .gpt import OpenAIClient
from ..models.openrouter import (
    OpenRouterModel,
    ProviderPreferences,
    OpenRouterUsage,
)

logger = getLogger(__name__)


class OpenRouterClient(OpenAIClient):
    """Client for OpenRouter's multi-model API gateway.

    Extends OpenAIClient with OpenRouter-specific features:
    - Custom headers (HTTP-Referer, X-Title) for app identification
    - Provider routing preferences (fallback, ordering, filtering)
    - Cost/usage tracking via generation stats endpoint
    - Model listing from OpenRouter's catalog

    Args:
        api_key: OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
        app_name: Application name sent as X-Title header.
        site_url: Site URL sent as HTTP-Referer header.
        provider_preferences: Routing preferences for provider selection.
        **kwargs: Additional arguments passed to OpenAIClient/AbstractClient.

    Example:
        >>> client = OpenRouterClient(
        ...     model="deepseek/deepseek-r1",
        ...     provider_preferences=ProviderPreferences(
        ...         order=["DeepInfra", "Together"]
        ...     )
        ... )
        >>> response = await client.ask("Hello!")
    """

    client_type: str = "openrouter"
    client_name: str = "openrouter"
    _default_model: str = OpenRouterModel.DEEPSEEK_R1.value

    def __init__(
        self,
        api_key: Optional[str] = None,
        app_name: Optional[str] = None,
        site_url: Optional[str] = None,
        provider_preferences: Optional[ProviderPreferences] = None,
        **kwargs
    ):
        self.app_name = app_name or config.get(
            'OPENROUTER_APP_NAME', 'AI-Parrot'
        )
        self.site_url = site_url or config.get(
            'OPENROUTER_SITE_URL', ''
        )
        self.provider_preferences = provider_preferences
        resolved_key = api_key or config.get('OPENROUTER_API_KEY')
        super().__init__(
            api_key=resolved_key,
            base_url="https://openrouter.ai/api/v1",
            **kwargs
        )
        # Re-set after super().__init__ because AbstractClient may overwrite
        self.api_key = resolved_key

    async def get_client(self) -> AsyncOpenAI:
        """Initialize AsyncOpenAI with OpenRouter base_url and custom headers.

        Returns:
            AsyncOpenAI client configured for OpenRouter.
        """
        headers = {
            "HTTP-Referer": self.site_url,
            "X-Title": self.app_name,
        }
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=headers,
            timeout=config.get('OPENAI_TIMEOUT', 60),
        )

    def _build_provider_extra_body(self) -> Optional[Dict[str, Any]]:
        """Build extra_body dict with provider preferences if configured.

        Returns:
            Dict with 'provider' key or None if no preferences set.
        """
        if self.provider_preferences is None:
            return None
        return {
            "provider": self.provider_preferences.model_dump(exclude_none=True)
        }

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs
    ):
        """Override to inject provider preferences via extra_body.

        Args:
            model: Model identifier string.
            messages: Chat messages list.
            use_tools: Whether tools are enabled.
            **kwargs: Additional completion arguments.
        """
        extra = self._build_provider_extra_body()
        if extra:
            existing = kwargs.get("extra_body", {}) or {}
            kwargs["extra_body"] = {**existing, **extra}
        return await super()._chat_completion(
            model=model,
            messages=messages,
            use_tools=use_tools,
            **kwargs
        )

    async def get_generation_stats(
        self, generation_id: str
    ) -> OpenRouterUsage:
        """Fetch cost/usage stats for a specific generation.

        Calls OpenRouter's generation endpoint to retrieve token counts,
        cost, and provider information for a completed generation.

        Args:
            generation_id: The generation ID returned by OpenRouter.

        Returns:
            OpenRouterUsage with cost and token information.

        Raises:
            aiohttp.ClientError: If the HTTP request fails.
        """
        url = f"https://openrouter.ai/api/v1/generation?id={generation_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        gen_data = data.get("data", {})
        return OpenRouterUsage(
            generation_id=gen_data.get("id"),
            model=gen_data.get("model"),
            total_cost=gen_data.get("total_cost"),
            prompt_tokens=gen_data.get("tokens_prompt"),
            completion_tokens=gen_data.get("tokens_completion"),
            native_tokens_prompt=gen_data.get("native_tokens_prompt"),
            native_tokens_completion=gen_data.get("native_tokens_completion"),
            provider_name=gen_data.get("provider_name"),
        )

    async def list_models(self) -> List[Dict[str, Any]]:
        """List all available models from OpenRouter.

        Fetches the model catalog from OpenRouter's API endpoint.

        Returns:
            List of model dicts with id, name, pricing, context_length, etc.

        Raises:
            aiohttp.ClientError: If the HTTP request fails.
        """
        url = "https://openrouter.ai/api/v1/models"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        return data.get("data", [])
