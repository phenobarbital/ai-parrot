"""MCP Server Registry — declarative catalog of pre-built MCP server helpers.

This module defines the data models and registry that describe each
``add_*_mcp_server`` helper method on :class:`~parrot.mcp.integration.MCPEnabledMixin`.
The registry is declarative (not reflection-based), so descriptions, param types,
and categories are explicit rather than inferred from signatures.

Usage::

    from parrot.mcp.registry import MCPServerRegistry, MCPParamType

    registry = MCPServerRegistry()
    servers = registry.list_servers()
    desc = registry.get_server("perplexity")
    params = registry.validate_params("perplexity", {"api_key": "sk-..."})
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class MCPParamType(str, Enum):
    """Type hint for an MCP server parameter.

    The ``SECRET`` variant signals that the frontend should mask the input
    field and that the value must be stored in the Vault rather than
    persisted in DocumentDB plaintext.
    """

    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    SECRET = "secret"


class MCPServerParam(BaseModel):
    """Describes a single parameter accepted by an MCP server helper.

    Attributes:
        name: Parameter name (matches the Python keyword argument).
        type: Expected value type; use ``SECRET`` for credentials.
        required: Whether the caller must supply a value.
        default: Default value used when ``required`` is ``False``.
        description: Human-readable explanation shown in the catalog.
    """

    name: str
    type: MCPParamType = MCPParamType.STRING
    required: bool = True
    default: Optional[Any] = None
    description: str = ""


class MCPServerDescriptor(BaseModel):
    """Catalog entry describing a single pre-built MCP server helper.

    Attributes:
        name: Registry slug used as the identifier in API requests
            (e.g. ``"perplexity"``).
        display_name: Human-friendly label for UI display.
        description: What the MCP server does.
        method_name: Name of the ``MCPEnabledMixin`` method to call
            (e.g. ``"add_perplexity_mcp_server"``).
        params: Ordered list of accepted parameters.
        category: Grouping label for the catalog
            (e.g. ``"search"``, ``"media"``, ``"dev-tools"``).
    """

    name: str = Field(..., description="Registry slug, e.g. 'perplexity'")
    display_name: str = Field(..., description="Human-friendly name")
    description: str = Field(..., description="What this MCP server does")
    method_name: str = Field(..., description="MCPEnabledMixin method to call")
    params: List[MCPServerParam] = Field(default_factory=list)
    category: str = Field(default="general", description="e.g. 'search', 'media'")


class UserMCPServerConfig(BaseModel):
    """Persisted configuration for a user-activated MCP server.

    This document is stored in the ``user_mcp_configs`` DocumentDB collection.
    Secret parameters (API keys, tokens) are **never** stored here — they live
    in the Vault; ``vault_credential_name`` points to the Vault entry.

    Attributes:
        server_name: Registry slug of the activated server.
        agent_id: Agent the server is scoped to.
        user_id: Owner of this configuration.
        params: Non-secret configuration parameters.
        vault_credential_name: Name of the Vault credential that holds
            any secret values (``None`` if no secrets are required).
        active: Soft-delete flag; ``False`` means this config is deactivated.
        created_at: ISO-8601 timestamp of initial creation.
        updated_at: ISO-8601 timestamp of last update.
    """

    server_name: str = Field(..., description="Registry slug")
    agent_id: str
    user_id: str
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret params (secrets stored in Vault)",
    )
    vault_credential_name: Optional[str] = Field(
        None,
        description="Name of the Vault credential holding secrets",
    )
    active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ActivateMCPServerRequest(BaseModel):
    """Request body for the POST (activate) endpoint.

    Attributes:
        server: Registry slug of the server to activate
            (e.g. ``"perplexity"``).
        params: All parameters, including secrets.  The handler separates
            secret params before storing them in the Vault.
    """

    server: str = Field(..., description="Registry slug, e.g. 'perplexity'")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters including secrets",
    )


# ---------------------------------------------------------------------------
# Declarative Registry
# ---------------------------------------------------------------------------

_REGISTRY: List[MCPServerDescriptor] = [
    MCPServerDescriptor(
        name="perplexity",
        display_name="Perplexity AI",
        description=(
            "Web search, conversational AI, deep research, and reasoning "
            "via Perplexity models."
        ),
        method_name="add_perplexity_mcp_server",
        category="search",
        params=[
            MCPServerParam(
                name="api_key",
                type=MCPParamType.SECRET,
                required=True,
                description="Perplexity API key from perplexity.ai/account/api",
            ),
        ],
    ),
    MCPServerDescriptor(
        name="fireflies",
        display_name="Fireflies.ai",
        description=(
            "Transcription, meeting notes, and conversation intelligence "
            "via the Fireflies.ai API."
        ),
        method_name="add_fireflies_mcp_server",
        category="productivity",
        params=[
            MCPServerParam(
                name="api_key",
                type=MCPParamType.SECRET,
                required=True,
                description="Fireflies API key from app.fireflies.ai/account",
            ),
        ],
    ),
    MCPServerDescriptor(
        name="chrome-devtools",
        display_name="Chrome DevTools",
        description=(
            "Browser automation and debugging via the Chrome DevTools Protocol "
            "remote debugging interface."
        ),
        method_name="add_chrome_devtools_mcp_server",
        category="dev-tools",
        params=[
            MCPServerParam(
                name="browser_url",
                type=MCPParamType.STRING,
                required=False,
                default="http://127.0.0.1:9222",
                description=(
                    "Chrome remote debugging URL "
                    "(default: http://127.0.0.1:9222)"
                ),
            ),
        ],
    ),
    MCPServerDescriptor(
        name="google-maps",
        display_name="Google Maps",
        description=(
            "Place search, directions, geocoding, and mapping via the "
            "Google Maps Platform."
        ),
        method_name="add_google_maps_mcp_server",
        category="maps",
        params=[],
    ),
    MCPServerDescriptor(
        name="alphavantage",
        display_name="Alpha Vantage",
        description=(
            "Real-time and historical financial data including stocks, forex, "
            "crypto, and economic indicators via Alpha Vantage."
        ),
        method_name="add_alphavantage_mcp_server",
        category="finance",
        params=[
            MCPServerParam(
                name="api_key",
                type=MCPParamType.SECRET,
                required=False,
                default=None,
                description=(
                    "Alpha Vantage API key (optional; falls back to "
                    "ALPHAVANTAGE_API_KEY env var)"
                ),
            ),
        ],
    ),
    MCPServerDescriptor(
        name="genmedia",
        display_name="Google GenMedia",
        description=(
            "AI image and video generation via Google Cloud's generative "
            "media APIs (Imagen, Veo, etc.)."
        ),
        method_name="add_genmedia_mcp_servers",
        category="media",
        params=[],
    ),
    MCPServerDescriptor(
        name="quic",
        display_name="QUIC MCP Server",
        description=(
            "Connect to a remote MCP server over the QUIC transport protocol "
            "for low-latency, encrypted communication."
        ),
        method_name="add_quic_mcp_server",
        category="transport",
        params=[
            MCPServerParam(
                name="name",
                type=MCPParamType.STRING,
                required=True,
                description="Unique name for this MCP server connection",
            ),
            MCPServerParam(
                name="host",
                type=MCPParamType.STRING,
                required=True,
                description="Hostname or IP address of the QUIC MCP server",
            ),
            MCPServerParam(
                name="port",
                type=MCPParamType.INTEGER,
                required=True,
                description="Port number of the QUIC MCP server",
            ),
            MCPServerParam(
                name="cert_path",
                type=MCPParamType.STRING,
                required=False,
                default=None,
                description=(
                    "Path to TLS certificate file for mutual TLS "
                    "(optional, for self-signed certs)"
                ),
            ),
        ],
    ),
    MCPServerDescriptor(
        name="websocket",
        display_name="WebSocket MCP Server",
        description=(
            "Connect to a remote MCP server over WebSocket, optionally "
            "with API-key or OAuth authentication."
        ),
        method_name="add_websocket_mcp_server",
        category="transport",
        params=[
            MCPServerParam(
                name="name",
                type=MCPParamType.STRING,
                required=True,
                description="Unique name for this MCP server connection",
            ),
            MCPServerParam(
                name="url",
                type=MCPParamType.STRING,
                required=True,
                description="WebSocket URL of the remote MCP server",
            ),
            MCPServerParam(
                name="auth_type",
                type=MCPParamType.STRING,
                required=False,
                default=None,
                description=(
                    "Authentication scheme to use "
                    "(e.g. 'api_key', 'bearer', 'basic')"
                ),
            ),
            MCPServerParam(
                name="auth_config",
                type=MCPParamType.STRING,
                required=False,
                default=None,
                description=(
                    "JSON-encoded authentication configuration dict "
                    "matching the chosen auth_type"
                ),
            ),
            MCPServerParam(
                name="headers",
                type=MCPParamType.STRING,
                required=False,
                default=None,
                description=(
                    "JSON-encoded dict of extra HTTP headers to send "
                    "during the WebSocket handshake"
                ),
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# MCPServerRegistry
# ---------------------------------------------------------------------------


class MCPServerRegistry:
    """Catalog of pre-built MCP server helpers available for user activation.

    Wraps the module-level ``_REGISTRY`` list with lookup and validation
    methods.  The registry is declarative — all entries are hand-authored
    above, not generated by reflection.

    Example::

        registry = MCPServerRegistry()
        desc = registry.get_server("perplexity")
        params = registry.validate_params("perplexity", {"api_key": "sk-..."})
    """

    def list_servers(self) -> List[MCPServerDescriptor]:
        """Return all registered MCP server descriptors.

        Returns:
            List of :class:`MCPServerDescriptor` instances, one per helper.
        """
        return list(_REGISTRY)

    def get_server(self, name: str) -> Optional[MCPServerDescriptor]:
        """Look up a single server descriptor by its registry slug.

        Args:
            name: Registry slug (e.g. ``"perplexity"``).

        Returns:
            The matching :class:`MCPServerDescriptor`, or ``None`` if not found.
        """
        for desc in _REGISTRY:
            if desc.name == name:
                return desc
        return None

    def validate_params(
        self,
        name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate user-supplied parameters against the descriptor schema.

        Checks that all required parameters are present.  Fills in default
        values for optional parameters that are absent from ``params``.

        Args:
            name: Registry slug of the server to validate against.
            params: User-supplied parameter mapping.

        Returns:
            Cleaned parameter dict with defaults applied.

        Raises:
            ValueError: If the server slug is not found, or if any required
                parameter is missing from ``params``.
        """
        desc = self.get_server(name)
        if desc is None:
            raise ValueError(
                f"MCP server '{name}' not found in registry. "
                f"Available servers: {[s.name for s in _REGISTRY]}"
            )

        cleaned: Dict[str, Any] = dict(params)
        missing: List[str] = []

        for param in desc.params:
            if param.name not in cleaned:
                if param.required:
                    missing.append(param.name)
                else:
                    if param.default is not None:
                        cleaned[param.name] = param.default

        if missing:
            raise ValueError(
                f"Missing required parameter(s) for MCP server '{name}': "
                + ", ".join(f"'{p}'" for p in missing)
            )

        return cleaned
