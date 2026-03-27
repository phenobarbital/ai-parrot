import pytest
from openai import RateLimitError, APIError, BadRequestError
from parrot.clients.gpt import OpenAIClient


def _make_openai_client(**attrs):
    """Create a minimal OpenAIClient instance for testing."""
    client = OpenAIClient.__new__(OpenAIClient)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


class TestOpenAIFallbackModel:
    def test_fallback_model_default(self):
        """_fallback_model defaults to gpt-4.1-nano."""
        client = _make_openai_client()
        assert client._fallback_model == 'gpt-4.1-nano'


class TestOpenAIIsCapacityError:
    def test_detects_rate_limit_string(self):
        client = _make_openai_client()
        error = Exception("429 Rate limit exceeded")
        assert client._is_capacity_error(error) is True

    def test_detects_503_string(self):
        client = _make_openai_client()
        error = Exception("503 Service Unavailable")
        assert client._is_capacity_error(error) is True

    def test_detects_openai_rate_limit_error(self):
        """Detects openai.RateLimitError instances."""
        client = _make_openai_client()
        error = RateLimitError.__new__(RateLimitError)
        # RateLimitError may not have a clean __str__, so test isinstance path
        assert client._is_capacity_error(error) is True

    def test_detects_api_error_502(self):
        """Detects APIError with status_code 502."""
        client = _make_openai_client()
        error = APIError.__new__(APIError)
        error.status_code = 502
        assert client._is_capacity_error(error) is True

    def test_detects_api_error_503(self):
        """Detects APIError with status_code 503."""
        client = _make_openai_client()
        error = APIError.__new__(APIError)
        error.status_code = 503
        assert client._is_capacity_error(error) is True

    def test_no_capacity_error_on_api_error_400(self):
        """APIError with status 400 is NOT a capacity error."""
        client = _make_openai_client()
        error = APIError.__new__(APIError)
        error.status_code = 400
        assert client._is_capacity_error(error) is False

    def test_no_capacity_error_on_auth(self):
        client = _make_openai_client()
        error = Exception("401 Unauthorized - Invalid API key")
        assert client._is_capacity_error(error) is False

    def test_no_capacity_error_on_bad_request(self):
        client = _make_openai_client()
        error = Exception("400 Bad Request - Invalid parameters")
        assert client._is_capacity_error(error) is False

    def test_no_capacity_error_on_not_found(self):
        client = _make_openai_client()
        error = Exception("404 Not Found")
        assert client._is_capacity_error(error) is False


class TestOpenAIShouldUseFallback:
    def test_returns_true_on_capacity_error(self):
        client = _make_openai_client()
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("gpt-4.1", error) is True

    def test_returns_false_when_same_model(self):
        client = _make_openai_client()
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("gpt-4.1-nano", error) is False

    def test_returns_false_on_auth_error(self):
        client = _make_openai_client()
        error = Exception("401 Unauthorized")
        assert client._should_use_fallback("gpt-4.1", error) is False
