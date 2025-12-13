import os
import base64
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable

@dataclass
class MCPClientConfig:
    """Complete configuration for external MCP server connection."""
    name: str

    # Connection parameters
    url: Optional[str] = None  # For HTTP/SSE servers
    command: Optional[str] = None  # For stdio servers
    args: Optional[List[str]] = None  # Command arguments
    env: Optional[Dict[str, str]] = None  # Environment variables

    # Authentication
    auth_type: Optional[str] = None  # "oauth", "bearer", "basic", "api_key", "none"
    auth_config: Dict[str, Any] = field(default_factory=dict)
    # A token supplier hook the HTTP client will call to add headers (set by OAuthManager)
    token_supplier: Optional[Callable[[], Optional[str]]] = None

    # Transport type
    transport: str = "auto"  # "auto", "stdio", "http", "sse" or "unix"
    base_path: Optional[str] = None  # Base path for HTTP/SSE endpoints
    events_path: Optional[str] = None  # SSE events path
    # URL for Unix socket (for unix transport)
    socket_path: Optional[str] = None

    # Additional headers for HTTP transports
    headers: Dict[str, str] = field(default_factory=dict)

    # Connection settings
    timeout: float = 30.0
    retry_count: int = 3
    startup_delay: float = 0.5

    # Tool filtering
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None

    # Process management
    kill_timeout: float = 5.0

    # QUIC Configuration
    quic_config: Any = None


class MCPAuthHandler:
    """Handles various authentication types for MCP servers."""

    def __init__(self, auth_type: str, auth_config: Dict[str, Any]):
        self.auth_type = auth_type.lower() if auth_type else None
        self.auth_config = auth_config
        self.logger = logging.getLogger("MCPAuthHandler")

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers based on auth type."""
        if not self.auth_type or self.auth_type == "none":
            return {}

        if self.auth_type == "bearer":
            return await self._get_bearer_headers()
        elif self.auth_type == "oauth":
            return await self._get_oauth_headers()
        elif self.auth_type == "basic":
            return await self._get_basic_headers()
        elif self.auth_type == "api_key":
            return await self._get_api_key_headers()
        else:
            self.logger.warning(f"Unknown auth type: {self.auth_type}")
            return {}

    async def _get_bearer_headers(self) -> Dict[str, str]:
        """Get Bearer token headers."""
        token = self.auth_config.get("token") or self.auth_config.get("access_token")
        if not token:
            raise ValueError("Bearer authentication requires 'token' or 'access_token' in auth_config")

        return {"Authorization": f"Bearer {token}"}

    async def _get_oauth_headers(self) -> Dict[str, str]:
        """Get OAuth headers (simplified - assumes token is already available)."""
        access_token = self.auth_config.get("access_token")
        if not access_token:
            # In a full implementation, you'd handle the OAuth flow here
            raise ValueError("OAuth authentication requires 'access_token' in auth_config")

        return {"Authorization": f"Bearer {access_token}"}

    async def _get_basic_headers(self) -> Dict[str, str]:
        """Get Basic authentication headers."""
        username = self.auth_config.get("username")
        password = self.auth_config.get("password")

        if not username or not password:
            raise ValueError("Basic authentication requires 'username' and 'password' in auth_config")

        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}

    async def _get_api_key_headers(self) -> Dict[str, str]:
        """Get API key headers."""
        api_key = self.auth_config.get("api_key")
        header_name = self.auth_config.get("header_name", "X-API-Key")
        use_bearer_prefix = self.auth_config.get("use_bearer_prefix", False)

        if not api_key:
            raise ValueError("API key authentication requires 'api_key' in auth_config")

        # Add Bearer prefix if requested (e.g., for Fireflies API)
        value = f"Bearer {api_key}" if use_bearer_prefix else api_key
        return {header_name: value}


class MCPConnectionError(Exception):
    """MCP connection related errors."""
    pass
