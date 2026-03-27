import pytest
from parrot.clients.base import AbstractClient


class _ConcreteClient(AbstractClient):
    """Minimal concrete subclass for testing base class methods."""

    async def get_client(self):
        return None

    async def ask(self, *args, **kwargs):
        raise NotImplementedError

    async def ask_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def resume(self, *args, **kwargs):
        raise NotImplementedError


def _make_client(**attrs):
    """Create a minimal AbstractClient instance for testing."""
    client = _ConcreteClient.__new__(_ConcreteClient)
    client._fallback_model = None
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


class TestIsCapacityError:
    def test_detects_429(self):
        client = _make_client()
        error = Exception("Error code: 429 - Rate limit exceeded")
        assert client._is_capacity_error(error) is True

    def test_detects_503(self):
        client = _make_client()
        error = Exception("503 Service Unavailable")
        assert client._is_capacity_error(error) is True

    def test_detects_overloaded(self):
        client = _make_client()
        error = Exception("The model is currently overloaded")
        assert client._is_capacity_error(error) is True

    def test_detects_rate_limit(self):
        client = _make_client()
        error = Exception("rate limit exceeded for this model")
        assert client._is_capacity_error(error) is True

    def test_detects_rate_limit_underscore(self):
        client = _make_client()
        error = Exception("rate_limit_exceeded")
        assert client._is_capacity_error(error) is True

    def test_detects_high_demand(self):
        client = _make_client()
        error = Exception("Model under high demand, please retry")
        assert client._is_capacity_error(error) is True

    def test_detects_too_many_requests(self):
        client = _make_client()
        error = Exception("Too many requests")
        assert client._is_capacity_error(error) is True

    def test_detects_service_unavailable(self):
        client = _make_client()
        error = Exception("Service unavailable right now")
        assert client._is_capacity_error(error) is True

    def test_ignores_auth_error(self):
        client = _make_client()
        error = Exception("401 Unauthorized - Invalid API key")
        assert client._is_capacity_error(error) is False

    def test_ignores_bad_request(self):
        client = _make_client()
        error = Exception("400 Bad Request - Invalid parameters")
        assert client._is_capacity_error(error) is False

    def test_ignores_not_found(self):
        client = _make_client()
        error = Exception("404 Not Found - Model does not exist")
        assert client._is_capacity_error(error) is False


class TestShouldUseFallback:
    def test_returns_true_when_conditions_met(self):
        client = _make_client(_fallback_model="fallback-model")
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("primary-model", error) is True

    def test_returns_false_when_no_fallback_model(self):
        client = _make_client(_fallback_model=None)
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("primary-model", error) is False

    def test_returns_false_when_same_model(self):
        client = _make_client(_fallback_model="same-model")
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("same-model", error) is False

    def test_returns_false_when_not_capacity_error(self):
        client = _make_client(_fallback_model="fallback-model")
        error = Exception("401 Unauthorized")
        assert client._should_use_fallback("primary-model", error) is False

    def test_returns_false_when_empty_string_fallback(self):
        client = _make_client(_fallback_model="")
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("primary-model", error) is False
