import pytest
from parrot.clients.google.client import GoogleGenAIClient


def _make_google_client(**attrs):
    """Create a minimal GoogleGenAIClient instance for testing."""
    client = GoogleGenAIClient.__new__(GoogleGenAIClient)
    # Ensure base class _fallback_model is accessible via class default
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


class TestGoogleFallbackModel:
    def test_fallback_model_default(self):
        """_fallback_model defaults to gemini-3.1-flash-preview-lite."""
        client = _make_google_client()
        assert client._fallback_model == 'gemini-3.1-flash-preview-lite'

    def test_high_demand_fallback_model_removed(self):
        """_high_demand_fallback_model no longer exists as a class attribute."""
        assert not hasattr(GoogleGenAIClient, '_high_demand_fallback_model')

    def test_resolve_high_demand_method_removed(self):
        """_resolve_high_demand_fallback_model no longer exists."""
        assert not hasattr(GoogleGenAIClient, '_resolve_high_demand_fallback_model')

    def test_is_high_demand_error_method_removed(self):
        """_is_high_demand_error no longer exists."""
        assert not hasattr(GoogleGenAIClient, '_is_high_demand_error')


class TestGoogleIsCapacityError:
    def test_detects_503(self):
        client = _make_google_client()
        error = Exception("503 Service Unavailable")
        assert client._is_capacity_error(error) is True

    def test_detects_unavailable(self):
        client = _make_google_client()
        error = Exception("The model is currently unavailable")
        assert client._is_capacity_error(error) is True

    def test_detects_high_demand(self):
        client = _make_google_client()
        error = Exception("The model is experiencing high demand")
        assert client._is_capacity_error(error) is True

    def test_detects_overloaded(self):
        client = _make_google_client()
        error = Exception("model is overloaded, please try again later")
        assert client._is_capacity_error(error) is True

    def test_detects_429(self):
        client = _make_google_client()
        error = Exception("429 RESOURCE_EXHAUSTED")
        assert client._is_capacity_error(error) is True

    def test_detects_resource_exhausted(self):
        client = _make_google_client()
        error = Exception("RESOURCE_EXHAUSTED: quota exceeded")
        assert client._is_capacity_error(error) is True

    def test_no_capacity_error_on_auth(self):
        client = _make_google_client()
        error = Exception("403 Forbidden - Invalid API key")
        assert client._is_capacity_error(error) is False

    def test_no_capacity_error_on_bad_request(self):
        client = _make_google_client()
        error = Exception("400 Bad Request - Invalid parameter")
        assert client._is_capacity_error(error) is False

    def test_no_capacity_error_on_not_found(self):
        client = _make_google_client()
        error = Exception("404 Model not found")
        assert client._is_capacity_error(error) is False


class TestGoogleShouldUseFallback:
    def test_returns_true_for_gemini_model(self):
        client = _make_google_client()
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("gemini-2.5-pro", error) is True

    def test_returns_false_for_non_gemini_model(self):
        client = _make_google_client()
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("custom-model", error) is False

    def test_returns_false_when_same_as_fallback(self):
        client = _make_google_client()
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("gemini-3.1-flash-preview-lite", error) is False

    def test_returns_false_on_auth_error(self):
        client = _make_google_client()
        error = Exception("403 Forbidden")
        assert client._should_use_fallback("gemini-2.5-pro", error) is False

    def test_returns_false_with_empty_model(self):
        client = _make_google_client()
        error = Exception("503 Service Unavailable")
        assert client._should_use_fallback("", error) is False
