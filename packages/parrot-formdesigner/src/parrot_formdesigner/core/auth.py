"""Authentication configuration models for form submission forwarding.

This module defines the AuthConfig discriminated union used by SubmitAction
to configure how outbound HTTP requests are authenticated when forwarding
form submissions to external endpoints.

Credentials are always resolved from environment variables at forwarding
time — never stored as raw secrets in the form schema.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


def _get_env(var_name: str) -> str:
    """Resolve an environment variable, trying navconfig first.

    Tries ``navconfig.config.get(var_name)`` first. Falls back to
    ``os.environ.get(var_name)`` if navconfig is not available.

    Args:
        var_name: Name of the environment variable to resolve.

    Returns:
        The resolved value string.

    Raises:
        ValueError: When the environment variable is not found in either source.
    """
    # Try navconfig first (project-standard env resolver)
    try:
        from navconfig import config  # type: ignore[import]
        value = config.get(var_name)
        if value is not None:
            return str(value)
    except (ImportError, Exception):
        pass  # navconfig not available — fall back to os.environ

    # Fall back to standard os.environ
    value = os.environ.get(var_name)
    if value is not None:
        return value

    raise ValueError(
        f"Environment variable '{var_name}' not found. "
        "Set it before starting the application."
    )


class NoAuth(BaseModel):
    """No authentication — default, backward-compatible.

    Attributes:
        type: Discriminator literal, always ``"none"``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["none"] = "none"

    def resolve(self) -> dict[str, str]:
        """Return empty auth headers (no authentication).

        Returns:
            An empty dict — no headers are added.
        """
        return {}


class BearerAuth(BaseModel):
    """Bearer token authentication resolved from an environment variable.

    The token is read from the environment at forwarding time — never
    stored in the form schema.

    Attributes:
        type: Discriminator literal, always ``"bearer"``.
        token_env: Name of the environment variable holding the Bearer token.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["bearer"] = "bearer"
    token_env: str = Field(
        ..., description="Environment variable name for the Bearer token"
    )

    def resolve(self) -> dict[str, str]:
        """Resolve the Bearer token from env and return Authorization header.

        Returns:
            Dict with ``{"Authorization": "Bearer <token>"}``.

        Raises:
            ValueError: When the env var named by ``token_env`` is not set.
        """
        token = _get_env(self.token_env)
        return {"Authorization": f"Bearer {token}"}


class ApiKeyAuth(BaseModel):
    """API key authentication resolved from an environment variable.

    The key is read from the environment at forwarding time — never
    stored in the form schema.

    Attributes:
        type: Discriminator literal, always ``"api_key"``.
        key_env: Name of the environment variable holding the API key.
        header_name: HTTP header to inject the key into. Defaults to ``"X-API-Key"``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["api_key"] = "api_key"
    key_env: str = Field(
        ..., description="Environment variable name for the API key"
    )
    header_name: str = Field(
        default="X-API-Key",
        description="HTTP header name for the key",
    )

    def resolve(self) -> dict[str, str]:
        """Resolve the API key from env and return the configured header.

        Returns:
            Dict with ``{header_name: key_value}``.

        Raises:
            ValueError: When the env var named by ``key_env`` is not set.
        """
        key = _get_env(self.key_env)
        return {self.header_name: key}


# Discriminated union — Pydantic resolves the concrete type via the ``type`` field.
AuthConfig = NoAuth | BearerAuth | ApiKeyAuth
