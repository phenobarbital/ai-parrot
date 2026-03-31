"""Integration tests for client-level fallback across all providers.

Validates the standardized fallback pattern end-to-end:
- All clients define _fallback_model
- All clients detect capacity errors consistently
- Non-capacity errors are never treated as capacity errors
- Fallback only triggers once (no cascading)
- Bot-level retry loops are removed
"""
import inspect
import importlib

import pytest
from parrot.clients.base import AbstractClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CLIENT_SPECS = [
    ("parrot.clients.google.client", "GoogleGenAIClient", "gemini-3.1-flash-lite-preview"),
    ("parrot.clients.claude", "AnthropicClient", "claude-sonnet-4.5"),
    ("parrot.clients.gpt", "OpenAIClient", "gpt-4.1-nano"),
]

CAPACITY_ERROR_MESSAGES = [
    "429 Too Many Requests",
    "503 Service Unavailable",
    "The model is overloaded",
    "Rate limit exceeded",
    "rate_limit_exceeded",
    "Service unavailable",
    "too many requests",
]

NON_CAPACITY_ERROR_MESSAGES = [
    "401 Unauthorized - Invalid API key",
    "400 Bad Request - Invalid parameters",
    "404 Not Found - Model does not exist",
    "403 Forbidden",
    "500 Internal Server Error - unexpected null",
]


def _load_client_class(module_path: str, class_name: str):
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _make_instance(module_path: str, class_name: str):
    cls = _load_client_class(module_path, class_name)
    return cls.__new__(cls)


# ---------------------------------------------------------------------------
# Cross-client fallback model defaults
# ---------------------------------------------------------------------------

class TestFallbackDecisionLogic:
    """Cross-client _is_capacity_error and _should_use_fallback tests."""

    @pytest.mark.parametrize("module_path,class_name,fallback_model", CLIENT_SPECS)
    def test_each_client_has_fallback_model(self, module_path, class_name, fallback_model):
        """Every client defines its _fallback_model with the correct default."""
        instance = _make_instance(module_path, class_name)
        assert instance._fallback_model == fallback_model

    @pytest.mark.parametrize("module_path,class_name,fallback_model", CLIENT_SPECS)
    def test_each_client_has_is_capacity_error(self, module_path, class_name, fallback_model):
        """Every client has _is_capacity_error method."""
        cls = _load_client_class(module_path, class_name)
        assert hasattr(cls, '_is_capacity_error')
        assert callable(getattr(cls, '_is_capacity_error'))

    @pytest.mark.parametrize("module_path,class_name,fallback_model", CLIENT_SPECS)
    def test_each_client_has_should_use_fallback(self, module_path, class_name, fallback_model):
        """Every client has _should_use_fallback method."""
        cls = _load_client_class(module_path, class_name)
        assert hasattr(cls, '_should_use_fallback')
        assert callable(getattr(cls, '_should_use_fallback'))


# ---------------------------------------------------------------------------
# Base capacity error detection consistency
# ---------------------------------------------------------------------------

def _make_base_client(**attrs):
    """Create a concrete AbstractClient subclass instance for testing."""
    from parrot.clients.gpt import OpenAIClient
    client = OpenAIClient.__new__(OpenAIClient)
    client._fallback_model = None
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


class TestBaseCapacityErrorConsistency:
    """Verify the base class detects all common capacity patterns."""

    @pytest.mark.parametrize("error_msg", CAPACITY_ERROR_MESSAGES)
    def test_capacity_errors_detected(self, error_msg):
        """Base _is_capacity_error detects common capacity patterns."""
        client = _make_base_client()
        assert client._is_capacity_error(Exception(error_msg)) is True

    @pytest.mark.parametrize("error_msg", NON_CAPACITY_ERROR_MESSAGES)
    def test_non_capacity_errors_ignored(self, error_msg):
        """Base _is_capacity_error ignores non-capacity errors."""
        client = _make_base_client()
        assert client._is_capacity_error(Exception(error_msg)) is False


# ---------------------------------------------------------------------------
# No double/cascading fallback
# ---------------------------------------------------------------------------

class TestNoDoubleFallback:
    """Verify fallback only happens once — no cascading."""

    @pytest.mark.parametrize("module_path,class_name,fallback_model", CLIENT_SPECS)
    def test_fallback_model_does_not_fallback_again(self, module_path, class_name, fallback_model):
        """When current model IS the fallback, _should_use_fallback returns False."""
        instance = _make_instance(module_path, class_name)
        error = Exception("429 Rate limit exceeded")
        assert instance._should_use_fallback(fallback_model, error) is False

    @pytest.mark.parametrize("module_path,class_name,fallback_model", CLIENT_SPECS)
    def test_no_fallback_when_fallback_not_set(self, module_path, class_name, fallback_model):
        """When _fallback_model is None, no fallback occurs."""
        instance = _make_instance(module_path, class_name)
        instance._fallback_model = None
        error = Exception("429 Rate limit exceeded")
        assert instance._should_use_fallback("some-model", error) is False


# ---------------------------------------------------------------------------
# Response metadata on fallback
# ---------------------------------------------------------------------------

class TestFallbackMetadata:
    """Verify fallback metadata fields exist on AIMessage."""

    def test_ai_message_has_metadata_field(self):
        """AIMessage has a metadata dict field."""
        from parrot.models.responses import AIMessage
        fields = AIMessage.model_fields
        assert 'metadata' in fields

    def test_ai_message_metadata_default_is_dict(self):
        """AIMessage.metadata defaults to empty dict."""
        from parrot.models.responses import AIMessage
        field = AIMessage.model_fields['metadata']
        assert field.default_factory is not None


# ---------------------------------------------------------------------------
# Bot-level no retry (using BaseBot where implementation lives)
# ---------------------------------------------------------------------------

class TestBotLevelNoRetry:
    """Verify AbstractBot.conversation/ask no longer have retry loops."""

    def test_conversation_no_retry_loop(self):
        from parrot.bots.base import BaseBot
        source = inspect.getsource(BaseBot.conversation)
        assert "for attempt in range" not in source
        assert "retries + 1" not in source
        assert "kwargs.get('retries'" not in source

    def test_ask_no_retry_loop(self):
        from parrot.bots.base import BaseBot
        source = inspect.getsource(BaseBot.ask)
        assert "for attempt in range" not in source
        assert "retries + 1" not in source
        assert "kwargs.get('retries'" not in source

    def test_conversation_still_closes_llm(self):
        from parrot.bots.base import BaseBot
        source = inspect.getsource(BaseBot.conversation)
        assert "self._llm.close()" in source

    def test_ask_preserves_exception_handling(self):
        from parrot.bots.base import BaseBot
        source = inspect.getsource(BaseBot.ask)
        assert "CancelledError" in source


# ---------------------------------------------------------------------------
# Provider-specific capacity error detection (SDK types)
# ---------------------------------------------------------------------------

class TestProviderSpecificCapacityErrors:
    """Test that each client detects its provider's native error types."""

    def test_openai_detects_rate_limit_error_instance(self):
        from openai import RateLimitError
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = RateLimitError.__new__(RateLimitError)
        assert client._is_capacity_error(error) is True

    def test_openai_detects_api_error_502(self):
        from openai import APIError
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = APIError.__new__(APIError)
        error.status_code = 502
        assert client._is_capacity_error(error) is True

    def test_openai_detects_api_error_503(self):
        from openai import APIError
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = APIError.__new__(APIError)
        error.status_code = 503
        assert client._is_capacity_error(error) is True

    def test_openai_ignores_api_error_400(self):
        from openai import APIError
        from parrot.clients.gpt import OpenAIClient
        client = OpenAIClient.__new__(OpenAIClient)
        error = APIError.__new__(APIError)
        error.status_code = 400
        assert client._is_capacity_error(error) is False

    def test_anthropic_detects_rate_limit_error(self):
        from anthropic import RateLimitError
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client._fallback_model = 'claude-sonnet-4.5'
        error = RateLimitError.__new__(RateLimitError)
        assert client._is_capacity_error(error) is True

    def test_anthropic_detects_api_status_error_429(self):
        from anthropic import APIStatusError
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client._fallback_model = 'claude-sonnet-4.5'
        error = APIStatusError.__new__(APIStatusError)
        error.status_code = 429
        assert client._is_capacity_error(error) is True

    def test_anthropic_detects_api_status_error_529(self):
        from anthropic import APIStatusError
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client._fallback_model = 'claude-sonnet-4.5'
        error = APIStatusError.__new__(APIStatusError)
        error.status_code = 529
        assert client._is_capacity_error(error) is True

    def test_anthropic_ignores_api_status_error_400(self):
        from anthropic import APIStatusError
        from parrot.clients.claude import AnthropicClient
        client = AnthropicClient.__new__(AnthropicClient)
        client._fallback_model = 'claude-sonnet-4.5'
        error = APIStatusError.__new__(APIStatusError)
        error.status_code = 400
        assert client._is_capacity_error(error) is False

    def test_google_detects_503_string(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        error = Exception("503 Service Unavailable")
        assert client._is_capacity_error(error) is True

    def test_google_detects_high_demand(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        error = Exception("Model experiencing high demand")
        assert client._is_capacity_error(error) is True

    def test_google_ignores_auth_error(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        error = Exception("403 Forbidden - Invalid API key")
        assert client._is_capacity_error(error) is False


# ---------------------------------------------------------------------------
# Google Gemini-only constraint
# ---------------------------------------------------------------------------

class TestGoogleGeminiConstraint:
    """Google fallback only applies to Gemini models."""

    def test_gemini_model_can_fallback(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("gemini-2.5-pro", error) is True

    def test_non_gemini_model_cannot_fallback(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("custom-vertex-model", error) is False

    def test_empty_model_cannot_fallback(self):
        from parrot.clients.google.client import GoogleGenAIClient
        client = GoogleGenAIClient.__new__(GoogleGenAIClient)
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("", error) is False


# ---------------------------------------------------------------------------
# Old method names removed
# ---------------------------------------------------------------------------

class TestLegacyMethodsRemoved:
    """Verify old Google fallback method names no longer exist."""

    def test_no_high_demand_fallback_model(self):
        from parrot.clients.google.client import GoogleGenAIClient
        assert not hasattr(GoogleGenAIClient, '_high_demand_fallback_model')

    def test_no_is_high_demand_error(self):
        from parrot.clients.google.client import GoogleGenAIClient
        assert not hasattr(GoogleGenAIClient, '_is_high_demand_error')

    def test_no_resolve_high_demand_fallback_model(self):
        from parrot.clients.google.client import GoogleGenAIClient
        assert not hasattr(GoogleGenAIClient, '_resolve_high_demand_fallback_model')

    def test_no_high_demand_references_in_source(self):
        """No _high_demand references remain in the Google client source."""
        source = inspect.getsource(
            importlib.import_module("parrot.clients.google.client")
        )
        assert "_high_demand" not in source
