"""Unit tests for the GigSmart typed exception hierarchy."""

import pytest

from parrot_tools.interfaces.gigsmart.exceptions import (
    GigSmartAuthError,
    GigSmartConflictError,
    GigSmartError,
    GigSmartGraphQLError,
    GigSmartNotFoundError,
    GigSmartRateLimitError,
    GigSmartTransportError,
    GigSmartValidationError,
)


class TestGigSmartExceptions:
    """Tests for the GigSmart exception hierarchy."""

    def test_base_error(self):
        """GigSmartError stores message and status_code correctly."""
        err = GigSmartError("test", status_code=500)
        assert str(err) == "test"
        assert err.status_code == 500
        assert err.message == "test"
        assert isinstance(err, Exception)

    def test_base_error_no_status_code(self):
        """GigSmartError status_code defaults to None."""
        err = GigSmartError("oops")
        assert err.status_code is None

    def test_all_subclass_base(self):
        """Every subclass inherits from GigSmartError."""
        for cls in [
            GigSmartAuthError,
            GigSmartValidationError,
            GigSmartRateLimitError,
            GigSmartNotFoundError,
            GigSmartTransportError,
            GigSmartGraphQLError,
            GigSmartConflictError,
        ]:
            assert issubclass(cls, GigSmartError), f"{cls.__name__} does not subclass GigSmartError"

    def test_all_subclass_exception(self):
        """Every subclass is also an Exception."""
        for cls in [
            GigSmartAuthError,
            GigSmartValidationError,
            GigSmartRateLimitError,
            GigSmartNotFoundError,
            GigSmartTransportError,
            GigSmartGraphQLError,
            GigSmartConflictError,
        ]:
            assert issubclass(cls, Exception), f"{cls.__name__} does not subclass Exception"

    def test_rate_limit_retry_after(self):
        """GigSmartRateLimitError stores retry_after and sets status_code=429."""
        err = GigSmartRateLimitError("rate limited", retry_after=30)
        assert err.retry_after == 30
        assert err.status_code == 429

    def test_rate_limit_default_retry_after(self):
        """GigSmartRateLimitError defaults retry_after to 60 when None."""
        err = GigSmartRateLimitError("rate limited")
        assert err.retry_after == 60
        assert err.status_code == 429

    def test_graphql_error_stores_errors(self):
        """GigSmartGraphQLError stores the raw errors list."""
        errors = [{"message": "not found", "extensions": {"code": "NOT_FOUND"}}]
        err = GigSmartGraphQLError("query failed", errors=errors)
        assert err.errors == errors

    def test_graphql_error_default_empty_list(self):
        """GigSmartGraphQLError defaults errors to an empty list."""
        err = GigSmartGraphQLError("failed")
        assert err.errors == []

    def test_graphql_error_message_and_status(self):
        """GigSmartGraphQLError stores message and optional status_code."""
        err = GigSmartGraphQLError("bad query", status_code=200)
        assert err.message == "bad query"
        assert err.status_code == 200

    def test_catch_as_base_class(self):
        """All subclass instances can be caught as GigSmartError."""
        with pytest.raises(GigSmartError):
            raise GigSmartAuthError("unauthorized", status_code=401)

    def test_auth_error_instantiation(self):
        """GigSmartAuthError instantiates with message and status_code."""
        err = GigSmartAuthError("forbidden", status_code=403)
        assert str(err) == "forbidden"
        assert err.status_code == 403

    def test_conflict_error_instantiation(self):
        """GigSmartConflictError instantiates correctly."""
        err = GigSmartConflictError("conflict", status_code=409)
        assert err.status_code == 409

    def test_transport_error_instantiation(self):
        """GigSmartTransportError instantiates correctly."""
        err = GigSmartTransportError("server error", status_code=503)
        assert err.status_code == 503

    def test_not_found_error_instantiation(self):
        """GigSmartNotFoundError instantiates correctly."""
        err = GigSmartNotFoundError("gig not found", status_code=404)
        assert err.status_code == 404

    def test_validation_error_instantiation(self):
        """GigSmartValidationError instantiates correctly."""
        err = GigSmartValidationError("bad input")
        assert err.message == "bad input"
