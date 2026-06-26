"""MCP OAuth2 configuration models and presets registry.

Provides ``MCPOAuth2Config`` (per-server OAuth2 settings) and
``MCPOAuth2Preset`` (pre-built provider templates). Presets follow the
same in-code registry pattern as ``MCPServerDescriptor``.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MCPOAuth2GrantType(str, Enum):
    """OAuth2 grant types supported for MCP server authentication.

    Attributes:
        AUTHORIZATION_CODE: Standard browser-based OAuth2 flow with PKCE.
        CLIENT_CREDENTIALS: Machine-to-machine flow without user interaction.
    """

    AUTHORIZATION_CODE = "authorization_code"
    CLIENT_CREDENTIALS = "client_credentials"


class MCPOAuth2Config(BaseModel):
    """OAuth2 configuration for a single MCP server connection.

    All fields are optional to support RFC 7591 dynamic client registration:
    when ``client_id`` is ``None`` the MCP SDK's ``OAuthContext`` handles
    dynamic registration automatically.

    Attributes:
        client_id: OAuth2 client ID.  ``None`` signals RFC 7591 dynamic
            registration.
        client_secret: OAuth2 client secret (optional; not used for public
            clients or PKCE-only flows).
        auth_url: Authorization endpoint URL.
        token_url: Token endpoint URL.
        scopes: Requested OAuth2 scopes.
        grant_type: OAuth2 grant type (default: authorization_code).
        redirect_path: Path for the OAuth2 callback route.
        extra_token_params: Additional parameters to include in token requests.

    Example:
        >>> cfg = MCPOAuth2Config(
        ...     client_id="my-app",
        ...     auth_url="https://auth.example.com/authorize",
        ...     token_url="https://auth.example.com/token",
        ...     scopes=["read", "write"],
        ... )
    """

    client_id: Optional[str] = Field(
        default=None,
        description="OAuth2 client ID. None = RFC 7591 dynamic registration.",
    )
    client_secret: Optional[str] = Field(
        default=None,
        description="OAuth2 client secret (optional for public clients).",
    )
    auth_url: Optional[str] = Field(
        default=None,
        description="Authorization endpoint URL.",
    )
    token_url: Optional[str] = Field(
        default=None,
        description="Token endpoint URL.",
    )
    scopes: List[str] = Field(
        default_factory=list,
        description="OAuth2 scopes to request.",
    )
    grant_type: MCPOAuth2GrantType = Field(
        default=MCPOAuth2GrantType.AUTHORIZATION_CODE,
        description="OAuth2 grant type.",
    )
    redirect_path: str = Field(
        default="/api/auth/oauth2/mcp/callback",
        description="Path for the OAuth2 callback route.",
    )
    redirect_base_url: str = Field(
        default="",
        description=(
            "Base URL (scheme + host + port) for the OAuth2 redirect URI, "
            "e.g. 'https://myapp.example.com'. When empty, the NAVIGATOR_BASE_URL "
            "environment variable is used, falling back to 'http://127.0.0.1:8000'. "
            "Set this explicitly in non-local deployments."
        ),
    )
    extra_token_params: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional parameters to send with token requests.",
    )


class MCPOAuth2Preset(BaseModel):
    """Pre-built OAuth2 configuration template for a known MCP provider.

    Presets supply default values for ``MCPOAuth2Config`` fields.  Callers
    typically look up a preset by name, then override individual fields with
    user-supplied values (e.g. ``client_id``).

    Attributes:
        name: Registry slug (e.g. ``"netsuite"``).
        display_name: Human-readable name (e.g. ``"NetSuite"``).
        auth_url: Default authorization endpoint URL (may contain template vars).
        token_url: Default token endpoint URL (may contain template vars).
        scopes: Default scopes for this provider.
        grant_type: Default grant type.
        url_template: Template for the MCP server URL (``{account_id}`` etc.).
        required_params: Parameters the caller MUST supply.
    """

    name: str = Field(..., description="Registry slug, e.g. 'netsuite'.")
    display_name: str = Field(..., description="Human-readable provider name.")
    auth_url: str = Field(..., description="Authorization endpoint URL template.")
    token_url: str = Field(..., description="Token endpoint URL template.")
    scopes: List[str] = Field(default_factory=list, description="Default scopes.")
    grant_type: MCPOAuth2GrantType = Field(
        default=MCPOAuth2GrantType.AUTHORIZATION_CODE,
        description="Default grant type.",
    )
    url_template: Optional[str] = Field(
        default=None,
        description="MCP server URL template (may contain {account_id} etc.).",
    )
    required_params: List[str] = Field(
        default_factory=list,
        description="Parameters the caller must provide.",
    )


# ---------------------------------------------------------------------------
# Built-in presets registry
# ---------------------------------------------------------------------------

_PRESETS: list[MCPOAuth2Preset] = [
    MCPOAuth2Preset(
        name="netsuite",
        display_name="NetSuite",
        auth_url=(
            "https://{account_id}.app.netsuite.com"
            "/app/login/oauth2/authorize.nl"
        ),
        token_url=(
            "https://{account_id}.suitetalk.api.netsuite.com"
            "/services/rest/auth/oauth2/v1/token"
        ),
        scopes=["mcp"],
        grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
        url_template=(
            "https://{account_id}.suitetalk.api.netsuite.com"
            "/services/mcp/v1/..."
        ),
        required_params=["account_id", "client_id"],
    ),
    # NOTE: The Fireflies MCP server currently uses API-key authentication
    # (Authorization: Bearer <api_key>), not a full OAuth2 authorization-code
    # flow.  Use ``add_fireflies_mcp_server()`` with your API key directly.
    # This preset is provided for future use when Fireflies ships OAuth2
    # endpoints; do NOT use it with the current Fireflies MCP integration.
    MCPOAuth2Preset(
        name="fireflies",
        display_name="Fireflies.ai",
        auth_url="https://app.fireflies.ai/oauth/authorize",
        token_url="https://app.fireflies.ai/oauth/token",
        scopes=["read:transcript", "write:transcript"],
        grant_type=MCPOAuth2GrantType.AUTHORIZATION_CODE,
        required_params=["client_id"],
    ),
]


def get_mcp_oauth2_preset(name: str) -> MCPOAuth2Preset | None:
    """Look up an MCP OAuth2 preset by its registry slug.

    Args:
        name: Registry slug of the preset (e.g. ``"netsuite"``).

    Returns:
        The :class:`MCPOAuth2Preset` if found, ``None`` otherwise.

    Example:
        >>> preset = get_mcp_oauth2_preset("netsuite")
        >>> preset.display_name
        'NetSuite'
    """
    return next((p for p in _PRESETS if p.name == name), None)


def list_mcp_oauth2_presets() -> list[MCPOAuth2Preset]:
    """Return all registered MCP OAuth2 presets.

    Returns:
        List of all :class:`MCPOAuth2Preset` instances.

    Example:
        >>> presets = list_mcp_oauth2_presets()
        >>> [p.name for p in presets]
        ['netsuite', 'fireflies']
    """
    return list(_PRESETS)
