"""Unit tests for OpenRouter factory registration."""
import pytest
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.openrouter import OpenRouterClient


class TestOpenRouterFactoryRegistration:
    def test_openrouter_in_supported_clients(self):
        """OpenRouter is registered in SUPPORTED_CLIENTS."""
        assert "openrouter" in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS["openrouter"] is OpenRouterClient

    def test_parse_openrouter_string(self):
        """Parser handles openrouter:model/name format."""
        provider, model = LLMFactory.parse_llm_string(
            "openrouter:deepseek/deepseek-r1"
        )
        assert provider == "openrouter"
        assert model == "deepseek/deepseek-r1"

    def test_parse_openrouter_no_model(self):
        """Parser handles bare 'openrouter' string."""
        provider, model = LLMFactory.parse_llm_string("openrouter")
        assert provider == "openrouter"
        assert model is None

    def test_parse_preserves_slash_in_model(self):
        """Model strings with slashes are preserved correctly."""
        provider, model = LLMFactory.parse_llm_string(
            "openrouter:meta-llama/llama-3.3-70b-instruct"
        )
        assert provider == "openrouter"
        assert model == "meta-llama/llama-3.3-70b-instruct"

    def test_factory_create_openrouter_with_model(self):
        """Factory creates OpenRouterClient with specified model."""
        client = LLMFactory.create(
            "openrouter:deepseek/deepseek-r1",
            api_key="test-key"
        )
        assert isinstance(client, OpenRouterClient)
        assert client.model == "deepseek/deepseek-r1"

    def test_factory_create_openrouter_default(self):
        """Factory creates OpenRouterClient with default model."""
        client = LLMFactory.create("openrouter", api_key="test-key")
        assert isinstance(client, OpenRouterClient)
