"""GigSmart interface package — aiohttp-based GraphQL transport with OAuth 2.1.

Public exports expose the three core components (client, config, auth) and all
typed exception classes for use from the toolkit layer and application code.
"""

from parrot_tools.interfaces.gigsmart.client import GigSmartClient
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.auth import GigSmartAuth
from parrot_tools.interfaces.gigsmart.exceptions import (
    GigSmartError,
    GigSmartAuthError,
    GigSmartValidationError,
    GigSmartRateLimitError,
    GigSmartNotFoundError,
    GigSmartTransportError,
    GigSmartGraphQLError,
    GigSmartConflictError,
)

__all__ = [
    # Core components
    "GigSmartClient",
    "GigSmartConfig",
    "GigSmartAuth",
    # Exceptions
    "GigSmartError",
    "GigSmartAuthError",
    "GigSmartValidationError",
    "GigSmartRateLimitError",
    "GigSmartNotFoundError",
    "GigSmartTransportError",
    "GigSmartGraphQLError",
    "GigSmartConflictError",
]
