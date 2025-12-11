from typing import Any, Dict, Optional, Tuple
from .base import AbstractClient
from .claude import AnthropicClient
from .google import GoogleGenAIClient
from .gpt import OpenAIClient
from .groq import GroqClient
from .grok import GrokClient


SUPPORTED_CLIENTS = {
    "claude": AnthropicClient,
    "anthropic": AnthropicClient,
    "google": GoogleGenAIClient,
    "openai": OpenAIClient,
    "groq": GroqClient,
    "grok": GrokClient,
    "xai": GrokClient
}


class LLMFactory:
    """
    Factory for creating LLM client instances from string specifications.

    Supports formats:
    - "provider:model" → e.g. "groq:llama-3.3-70b-versatile"
    - "provider" → uses default model for provider
    - Direct client class or instance
    """
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:
        """
        Parse LLM string in format 'provider:model' or 'provider'.

        Args:
            llm: String like "groq:llama-3.3-70b" or "anthropic"

        Returns:
            Tuple of (provider, model_or_None)

        Examples:
            >>> LLMFactory.parse_llm_string("groq:llama-3.3-70b-versatile")
            ('groq', 'llama-3.3-70b-versatile')
            >>> LLMFactory.parse_llm_string("anthropic")
            ('anthropic', None)
        """
        if ':' in llm:
            provider, model = llm.split(':', 1)
            return provider.strip(), model.strip()
        return llm.strip(), None

    @staticmethod
    def create(
        llm: str,
        model_args: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        **kwargs
    ) -> AbstractClient:
        """
        Create an LLM client instance from string specification.

        Args:
            llm: LLM specification string ("provider:model" or "provider")
            model_args: Dict with temperature, top_k, top_p, max_tokens, etc.
            tool_manager: Optional ToolManager to attach
            **kwargs: Additional parameters for client initialization

        Returns:
            Initialized AbstractClient instance

        Examples:
            >>> # Create with explicit model
            >>> client = LLMFactory.create(
            ...     llm="groq:llama-3.3-70b-versatile",
            ...     model_args={"temperature": 0.0}
            ... )

            >>> # Create with default model
            >>> client = LLMFactory.create(
            ...     llm="anthropic",
            ...     model_args={"temperature": 0.7, "max_tokens": 4096}
            ... )
        """
        if not isinstance(llm, str):
            raise ValueError(
                f"LLMFactory.create expects string, got {type(llm).__name__}"
            )

        # Parse provider and model
        provider, model = LLMFactory.parse_llm_string(llm)
        provider = provider.lower()

        # Validate provider
        if provider not in SUPPORTED_CLIENTS:
            raise ValueError(
                f"Unsupported LLM provider: '{provider}'. "
                f"Supported: {list(SUPPORTED_CLIENTS.keys())}"
            )

        # Get client class
        client_class = SUPPORTED_CLIENTS[provider]

        # Prepare initialization params
        init_params = {}

        # Add model if specified
        if model:
            init_params['model'] = model

        # Add model_args parameters
        if model_args:
            init_params.update({
                'temperature': model_args.get('temperature'),
                'top_k': model_args.get('top_k'),
                'top_p': model_args.get('top_p'),
                'max_tokens': model_args.get('max_tokens'),
            })
            # Remove None values
            init_params = {k: v for k, v in init_params.items() if v is not None}

        # Add tool_manager if provided
        if tool_manager:
            init_params['tool_manager'] = tool_manager

        # Merge additional kwargs
        init_params.update(kwargs)

        # Create and return client instance
        return client_class(**init_params)
