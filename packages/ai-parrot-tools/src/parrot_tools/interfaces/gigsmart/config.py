"""GigSmart configuration — credentials and API settings.

Loads OAuth credentials and endpoint URLs from environment variables.
The ``GigSmartConfig`` dataclass is the single source of truth for all
client configuration; other modules receive it by dependency injection.

Environment variables:
    GIGSMART_CLIENT_ID:     OAuth 2.1 client identifier (required)
    GIGSMART_CLIENT_SECRET: OAuth 2.1 client secret (required)
    GIGSMART_ENV:           ``"production"`` (default) or ``"sandbox"``
    GIGSMART_ENDPOINT_URL:  Override the GraphQL endpoint URL
    GIGSMART_LOG_PII:       Set to ``"1"`` to enable PII in log output
    GIGSMART_REFRESH_TOKEN: Pre-configured OAuth refresh token (optional)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from parrot_tools.interfaces.gigsmart.exceptions import GigSmartError

# ---------------------------------------------------------------------------
# Default endpoints
# ---------------------------------------------------------------------------

_DEFAULT_ENDPOINT_URL = "https://api.gigsmart.com/graphql"
_DEFAULT_TOKEN_URL = "https://api.gigsmart.com/oauth/token"
_DEFAULT_AUTHORIZE_URL = "https://api.gigsmart.com/oauth/authorize"


@dataclass
class GigSmartConfig:
    """Configuration for the GigSmart API client.

    All fields can be provided explicitly (useful for testing) or loaded
    from environment variables via :meth:`from_env`.

    Args:
        client_id: OAuth 2.1 client identifier.
        client_secret: OAuth 2.1 client secret.
        environment: Target environment — ``"production"`` or ``"sandbox"``.
        endpoint_url: GraphQL API endpoint URL.
        token_url: OAuth token endpoint URL.
        authorize_url: OAuth authorisation endpoint URL.
        request_timeout: Per-request timeout in seconds.
        max_concurrent_requests: Maximum number of parallel HTTP requests.
        log_pii: When ``True``, PII (names, addresses) may appear in logs.
        refresh_token: Pre-configured OAuth refresh token, if available.
    """

    client_id: str
    client_secret: str
    environment: str = "production"
    endpoint_url: str = _DEFAULT_ENDPOINT_URL
    token_url: str = _DEFAULT_TOKEN_URL
    authorize_url: str = _DEFAULT_AUTHORIZE_URL
    request_timeout: float = 30.0
    max_concurrent_requests: int = 8
    log_pii: bool = False
    refresh_token: str | None = None

    @classmethod
    def from_env(cls) -> "GigSmartConfig":
        """Build a ``GigSmartConfig`` from environment variables.

        Reads ``GIGSMART_CLIENT_ID`` and ``GIGSMART_CLIENT_SECRET`` (both
        required) plus optional overrides for all other fields.

        Returns:
            A fully-populated ``GigSmartConfig`` instance.

        Raises:
            GigSmartError: If ``GIGSMART_CLIENT_ID`` or
                ``GIGSMART_CLIENT_SECRET`` is missing from the environment.
        """
        client_id = os.getenv("GIGSMART_CLIENT_ID")
        if not client_id:
            raise GigSmartError(
                "GIGSMART_CLIENT_ID environment variable is required but not set."
            )

        client_secret = os.getenv("GIGSMART_CLIENT_SECRET")
        if not client_secret:
            raise GigSmartError(
                "GIGSMART_CLIENT_SECRET environment variable is required but not set."
            )

        environment = os.getenv("GIGSMART_ENV", "production")
        endpoint_url = os.getenv("GIGSMART_ENDPOINT_URL", _DEFAULT_ENDPOINT_URL)
        log_pii = os.getenv("GIGSMART_LOG_PII", "0").strip() == "1"
        refresh_token = os.getenv("GIGSMART_REFRESH_TOKEN") or None

        request_timeout_raw = os.getenv("GIGSMART_REQUEST_TIMEOUT")
        request_timeout = float(request_timeout_raw) if request_timeout_raw else 30.0

        max_concurrent_raw = os.getenv("GIGSMART_MAX_CONCURRENT_REQUESTS")
        max_concurrent = int(max_concurrent_raw) if max_concurrent_raw else 8

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            environment=environment,
            endpoint_url=endpoint_url,
            log_pii=log_pii,
            refresh_token=refresh_token,
            request_timeout=request_timeout,
            max_concurrent_requests=max_concurrent,
        )
