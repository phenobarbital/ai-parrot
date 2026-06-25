"""Typed exception hierarchy for GigSmart API errors.

Follows the ``MassiveAPIError`` pattern from ``parrot_tools/massive/client.py``.
Maps to the GraphQL error classification table in the spec (§7).
"""

from __future__ import annotations


class GigSmartError(Exception):
    """Base exception for all GigSmart API errors.

    Args:
        message: Human-readable error description.
        status_code: HTTP status code associated with the error, if any.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GigSmartAuthError(GigSmartError):
    """Authentication or authorisation failure.

    Raised when the API returns ``UNAUTHENTICATED`` or ``FORBIDDEN`` error codes,
    or when a write-scope operation is attempted with a client_credentials token.
    """


class GigSmartValidationError(GigSmartError):
    """Input validation failure.

    Raised when the API returns ``BAD_USER_INPUT`` — the caller supplied
    invalid values for a query argument or mutation field.
    """


class GigSmartRateLimitError(GigSmartError):
    """Rate limit exceeded (HTTP 429 / ``RATE_LIMITED`` extension code).

    Args:
        message: Human-readable error description.
        retry_after: Seconds to wait before retrying, derived from the
            ``Retry-After`` response header. Defaults to 60 when the header
            is absent.
    """

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message, status_code=429)
        self.retry_after: int = retry_after if retry_after is not None else 60


class GigSmartNotFoundError(GigSmartError):
    """Requested resource does not exist.

    Raised when the API returns a ``NOT_FOUND`` extension code.
    """


class GigSmartTransportError(GigSmartError):
    """Network or server-side transport failure.

    Raised on HTTP 5xx responses and unrecoverable network errors.
    This class of error is retryable with exponential backoff.
    """


class GigSmartGraphQLError(GigSmartError):
    """Generic GraphQL protocol error.

    Raised when the response contains ``errors`` that do not match any
    other classified code.

    Args:
        message: Human-readable summary.
        errors: The raw ``errors`` list from the GraphQL response body,
            preserving the full ``extensions`` payload for diagnostics.
    """

    def __init__(
        self,
        message: str,
        errors: list[dict] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.errors: list[dict] = errors or []


class GigSmartConflictError(GigSmartError):
    """Conflict with the current resource state.

    Raised when the API returns a ``CONFLICT`` extension code — for example,
    attempting to hire a worker for an already-filled shift.
    """
