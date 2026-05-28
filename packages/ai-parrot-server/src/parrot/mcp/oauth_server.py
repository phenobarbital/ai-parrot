"""OAuth server-side classes for MCP — extracted from parrot.mcp.oauth in FEAT-203.

These classes require ai-parrot-server to be installed. They provide the
full OAuth2 Authorization Server implementation, API key management,
external OAuth validator, and OAuth routes mixin for MCP server transports.
"""
import os
import sys
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import asyncio
import time
import base64
import hashlib
import secrets
import json
from urllib.parse import urlencode
from aiohttp import web, ClientSession
# Consumer-side classes imported from core
from parrot.mcp.oauth import (
    _b64url,
    _now,
    TokenStore,
    InMemoryTokenStore,
    RedisTokenStore,
    VaultTokenStore,
)

@dataclass
class APIKeyRecord:
    """Record for an issued API key."""
    key: str
    user_id: str
    created_at: float
    expires_at: Optional[float] = None
    scopes: list[str] = field(default_factory=list)
    description: str = ""


class APIKeyStore:
    """
    In-memory API key store with session logging.

    Provides API key issuance, validation, and session tracking for
    MCP server authentication.
    """

    def __init__(self):
        self._keys: Dict[str, APIKeyRecord] = {}
        self._sessions: list[Dict[str, Any]] = []

    def issue_key(
        self,
        user_id: str,
        scopes: Optional[list[str]] = None,
        ttl: Optional[int] = None,
        description: str = ""
    ) -> APIKeyRecord:
        """
        Issue a new API key for a user.

        Args:
            user_id: User identifier
            scopes: Optional list of scopes for the key
            ttl: Time-to-live in seconds (None for no expiration)
            description: Human-readable description

        Returns:
            APIKeyRecord with the issued key
        """
        key = f"mcp_key_{secrets.token_urlsafe(32)}"
        now = _now()
        expires_at = (now + ttl) if ttl else None

        record = APIKeyRecord(
            key=key,
            user_id=user_id,
            created_at=now,
            expires_at=expires_at,
            scopes=scopes or [],
            description=description,
        )
        self._keys[key] = record
        return record

    def add_key(
        self,
        key: str,
        user_id: str,
        scopes: Optional[list[str]] = None,
        description: str = ""
    ) -> APIKeyRecord:
        """
        Register an existing API key.

        Args:
            key: The existing API key string
            user_id: User identifier
            scopes: Optional list of scopes for the key
            description: Human-readable description

        Returns:
            APIKeyRecord for the added key
        """
        now = _now()
        
        record = APIKeyRecord(
            key=key,
            user_id=user_id,
            created_at=now,
            expires_at=None,
            scopes=scopes or [],
            description=description,
        )
        self._keys[key] = record
        return record

    def validate_key(self, key: str) -> Optional[APIKeyRecord]:
        """
        Validate an API key.

        Args:
            key: The API key to validate

        Returns:
            APIKeyRecord if valid, None if invalid or expired
        """
        if not key:
            return None

        record = self._keys.get(key)
        if not record:
            return None

        # Check expiration
        if record.expires_at and record.expires_at <= _now():
            return None

        return record

    def revoke_key(self, key: str) -> bool:
        """
        Revoke an API key.

        Args:
            key: The API key to revoke

        Returns:
            True if revoked, False if key not found
        """
        if key in self._keys:
            del self._keys[key]
            return True
        return False

    def log_session_start(self, key: str, user_id: str, timestamp: float) -> None:
        """
        Log the start of a session using an API key.

        Args:
            key: The API key used
            user_id: User identifier
            timestamp: Session start timestamp
        """
        self._sessions.append({
            "key": key[:16] + "...",  # Truncate for security
            "user_id": user_id,
            "started_at": timestamp,
            "started_at_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp)
            ),
        })

    def get_sessions(
        self, user_id: Optional[str] = None, limit: int = 100
    ) -> list[Dict[str, Any]]:
        """
        Get session logs.

        Args:
            user_id: Optional filter by user ID
            limit: Maximum number of sessions to return

        Returns:
            List of session records
        """
        sessions = self._sessions
        if user_id:
            sessions = [s for s in sessions if s["user_id"] == user_id]
        return sessions[-limit:]

    def list_keys(self, user_id: Optional[str] = None) -> list[APIKeyRecord]:
        """
        List all API keys.

        Args:
            user_id: Optional filter by user ID

        Returns:
            List of API key records
        """
        keys = list(self._keys.values())
        if user_id:
            keys = [k for k in keys if k.user_id == user_id]
        return keys


# ---- External OAuth2 Integration ----

class ExternalOAuthValidator:
    """
    Validates tokens against external OAuth2 servers using RFC 7662 introspection.

    Use this for integrating with external identity providers like Azure AD,
    Keycloak, Okta, etc.
    """

    def __init__(
        self,
        introspection_endpoint: str,
        client_id: str,
        client_secret: str,
        resource_server_url: Optional[str] = None,
        http_timeout: float = 15.0,
    ):
        """
        Initialize external OAuth validator.

        Args:
            introspection_endpoint: Token introspection endpoint URL
            client_id: Client ID for introspection requests
            client_secret: Client secret for introspection requests
            resource_server_url: Expected audience/resource URL
            http_timeout: HTTP request timeout in seconds
        """
        self.introspection_endpoint = introspection_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.resource_server_url = resource_server_url
        self.http_timeout = http_timeout
        self._token_cache: Dict[str, Dict[str, Any]] = {}

    async def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate a token via introspection.

        Args:
            token: Bearer token to validate

        Returns:
            Token info dict if valid, None if invalid
        """
        if not token:
            return None

        try:
            info = await self.get_token_info(token)
            if not info.get("active", False):
                return None

            # Validate audience if configured
            if self.resource_server_url:
                aud = info.get("aud", [])
                if isinstance(aud, str):
                    aud = [aud]
                if self.resource_server_url not in aud:
                    return None

            return info
        except Exception:
            return None

    async def get_token_info(self, token: str) -> Dict[str, Any]:
        """
        Get token info from introspection endpoint (RFC 7662).

        Args:
            token: Bearer token to introspect

        Returns:
            Token introspection response

        Raises:
            Exception on HTTP or validation errors
        """
        # Check cache first
        cached = self._token_cache.get(token)
        if cached and cached.get("_cached_until", 0) > _now():
            return cached

        # Prepare introspection request
        params = {
            "token": token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        async with ClientSession() as session:
            async with session.post(
                self.introspection_endpoint,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.http_timeout,
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise RuntimeError(
                        f"Introspection failed: {response.status} - {text}"
                    )

                info = await response.json()

        # Cache with TTL
        if info.get("active"):
            exp = info.get("exp", _now() + 60)
            info["_cached_until"] = min(exp, _now() + 300)  # Max 5 min cache
            self._token_cache[token] = info

        return info

    def clear_cache(self) -> None:
        """Clear the token cache."""
        self._token_cache.clear()


# ---- OAuth Client Models ----

@dataclass
class OAuthClient:
    client_id: str
    client_secret: str
    client_name: str
    redirect_uris: list[str]
    scopes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class ClientRegistry:
    """
    Minimal in-memory Dynamic Client Registration (RFC 7591) registry.
    Suitable for local development / proxy-style OAuth flows.
    """

    def __init__(self):
        self._clients: Dict[str, OAuthClient] = {}

    def register(self, metadata: Dict[str, Any]) -> OAuthClient:
        if "redirect_uris" not in metadata:
            raise ValueError("redirect_uris is required for client registration")

        client_id = metadata.get("client_id") or secrets.token_urlsafe(16)
        client_secret = metadata.get("client_secret") or secrets.token_urlsafe(32)
        client_name = metadata.get("client_name") or metadata.get("client_name", "mcp-client")
        redirect_uris = metadata["redirect_uris"]
        scopes = metadata.get("scope", "") or metadata.get("scopes", [])
        if isinstance(scopes, str):
            scopes = scopes.split()

        client = OAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            client_name=client_name,
            redirect_uris=redirect_uris,
            scopes=scopes,
        )
        self._clients[client_id] = client
        return client

    def get(self, client_id: str) -> Optional[OAuthClient]:
        return self._clients.get(client_id)


class OAuthAuthorizationServer:
    """In-memory OAuth 2.0 authorization server for MCP transports."""

    def __init__(
        self,
        *,
        default_scopes: Optional[list[str]] = None,
        allow_dynamic_registration: bool = True,
        token_ttl: int = 3600,
        code_ttl: int = 600,
    ):
        self.registry = ClientRegistry()
        self.default_scopes = default_scopes or ["mcp:access"]
        self.allow_dynamic_registration = allow_dynamic_registration
        self.token_ttl = token_ttl
        self.code_ttl = code_ttl
        self._codes: Dict[str, Dict[str, Any]] = {}
        self._tokens: Dict[str, Dict[str, Any]] = {}

    def register_routes(self, app: web.Application) -> None:
        app.router.add_get("/.well-known/oauth-authorization-server", self._handle_discovery)
        app.router.add_post("/oauth/register", self._handle_registration)
        app.router.add_get("/oauth/authorize", self._handle_authorize)
        app.router.add_post("/oauth/token", self._handle_token)

    def bearer_token_from_header(self, header: Optional[str]) -> Optional[str]:
        if not header:
            return None
        if not header.lower().startswith("bearer "):
            return None
        return header.split(" ", 1)[1].strip()

    def is_token_valid(self, token: Optional[str]) -> bool:
        if not token:
            return False
        stored = self._tokens.get(token)
        if not stored:
            return False
        return stored.get("expires_at", 0) > _now()

    def _build_base_url(self, request: web.Request) -> str:
        return f"{request.scheme}://{request.host}"

    async def _handle_discovery(self, request: web.Request) -> web.Response:
        base_url = self._build_base_url(request)
        metadata = {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "registration_endpoint": f"{base_url}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
            "scopes_supported": self.default_scopes,
        }
        return web.json_response(metadata)

    async def _handle_registration(self, request: web.Request) -> web.Response:
        if not self.allow_dynamic_registration:
            return web.json_response({"error": "registration_not_supported"}, status=400)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_request"}, status=400)

        try:
            client = self.registry.register(data)
        except Exception as exc:  # pragma: no cover - defensive
            return web.json_response(
                {
                    "error": "invalid_client_metadata",
                    "error_description": str(exc),
                },
                status=400,
            )

        return web.json_response(
            {
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "client_id_issued_at": int(client.created_at),
                "client_secret_expires_at": 0,
                "client_name": client.client_name,
                "redirect_uris": client.redirect_uris,
                "scope": " ".join(client.scopes or self.default_scopes),
            },
            status=201,
        )

    async def _handle_authorize(self, request: web.Request) -> web.StreamResponse:
        params = request.query
        client_id = params.get("client_id")
        redirect_uri = params.get("redirect_uri")
        state = params.get("state")
        response_type = params.get("response_type")
        code_challenge = params.get("code_challenge")
        code_challenge_method = params.get("code_challenge_method", "plain")

        if response_type != "code":
            return web.Response(status=400, text="unsupported response_type")

        client = self.registry.get(client_id) if client_id else None
        if not client:
            return web.Response(status=400, text="Invalid Client ID")

        if redirect_uri not in client.redirect_uris:
            return web.Response(status=400, text="Invalid Redirect URI")

        scopes = params.get("scope", "").split()
        if not scopes:
            scopes = client.scopes or self.default_scopes

        code = self._issue_code(
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scopes,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        target = f"{redirect_uri}?code={code}"
        if state:
            target += f"&state={state}"
        return web.HTTPFound(target)

    async def _handle_token(self, request: web.Request) -> web.Response:
        data = await request.post()
        grant_type = data.get("grant_type")
        code = data.get("code")
        client_id = data.get("client_id")

        if grant_type != "authorization_code":
            return web.json_response({"error": "unsupported_grant_type"}, status=400)

        record = self._codes.pop(code, None)
        if not record:
            return web.json_response({"error": "invalid_grant"}, status=400)

        if record["expires_at"] <= _now():
            return web.json_response({"error": "invalid_grant"}, status=400)

        if client_id != record["client_id"]:
            return web.json_response({"error": "invalid_client"}, status=400)

        if record.get("code_challenge"):
            verifier = data.get("code_verifier")
            if not verifier:
                return web.json_response({"error": "invalid_request"}, status=400)
            computed = _b64url(hashlib.sha256(verifier.encode()).digest())
            if computed != record["code_challenge"]:
                return web.json_response({"error": "invalid_grant"}, status=400)

        token_payload = self._issue_token(client_id=client_id, scope=record["scope"])
        return web.json_response(token_payload)

    def _issue_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scope: list[str],
        code_challenge: Optional[str],
        code_challenge_method: Optional[str],
    ) -> str:
        code = f"auth_code_{secrets.token_urlsafe(10)}"
        self._codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "expires_at": _now() + self.code_ttl,
        }
        return code

    def _issue_token(self, *, client_id: str, scope: list[str]) -> Dict[str, Any]:
        access_token = f"mcp_token_{secrets.token_urlsafe(32)}"
        expires_at = _now() + self.token_ttl
        payload = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": self.token_ttl,
            "expires_at": expires_at,
            "scope": " ".join(scope or self.default_scopes),
            "client_id": client_id,
        }
        self._tokens[access_token] = payload
        return payload


class OAuthRoutesMixin:
    """Shared OAuth/DCR utilities for HTTP and SSE transports."""

    def _init_oauth_support(self):
        self.client_registry = ClientRegistry()
        self._auth_codes: Dict[str, Dict[str, Any]] = {}

    def _oauth_paths(self) -> Dict[str, str]:
        base = self.base_path.rstrip("/")
        base = base if base else ""
        return {
            "discovery": f"{base}/.well-known/oauth-authorization-server",
            "register": f"{base}/oauth/register",
            "authorize": f"{base}/oauth/authorize",
            "token": f"{base}/oauth/token",
        }

    def _add_oauth_routes(self, router: web.UrlDispatcher):
        paths = self._oauth_paths()
        router.add_get(paths["discovery"], self._handle_discovery)
        router.add_post(paths["register"], self._handle_registration)
        router.add_get(paths["authorize"], self._handle_authorize)
        router.add_post(paths["token"], self._handle_token)

    async def _handle_discovery(self, request: web.Request) -> web.Response:
        """RFC 8414: Authorization Server Metadata."""
        base_url = f"{request.scheme}://{request.host}"
        paths = self._oauth_paths()
        metadata = {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}{paths['authorize']}",
            "token_endpoint": f"{base_url}{paths['token']}",
            "registration_endpoint": f"{base_url}{paths['register']}",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        }
        return web.json_response(metadata)

    async def _handle_registration(self, request: web.Request) -> web.Response:
        """RFC 7591: Dynamic Client Registration."""
        try:
            data = await request.json()
            client = self.client_registry.register(data)
            self.logger.info(
                "Dynamically registered client: %s (%s)",
                client.client_name,
                client.client_id,
            )
            return web.json_response(
                {
                    "client_id": client.client_id,
                    "client_secret": client.client_secret,
                    "client_id_issued_at": int(client.created_at),
                    "client_secret_expires_at": 0,
                    "client_name": client.client_name,
                    "redirect_uris": client.redirect_uris,
                    "scope": " ".join(client.scopes),
                },
                status=201,
            )
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error(f"DCR Error: {e}")
            return web.json_response(
                {"error": "invalid_client_metadata", "error_description": str(e)},
                status=400,
            )

    async def _handle_authorize(self, request: web.Request) -> web.Response:
        """Simplified OAuth 2.0 Authorization Endpoint (auto-approves)."""
        params = request.query
        client_id = params.get("client_id")
        redirect_uri = params.get("redirect_uri")
        state = params.get("state")
        code_challenge = params.get("code_challenge")
        code_challenge_method = params.get("code_challenge_method", "S256")

        client = self.client_registry.get(client_id) if client_id else None
        if not client:
            return web.Response(text="Invalid Client ID", status=400)

        if redirect_uri not in client.redirect_uris:
            return web.Response(text="Invalid Redirect URI", status=400)

        auth_code = f"auth_code_{secrets.token_urlsafe(16)}"
        self._auth_codes[auth_code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scopes": client.scopes,
            "issued_at": time.time(),
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }

        target = f"{redirect_uri}?code={auth_code}"
        if state:
            target += f"&state={state}"

        return web.HTTPFound(target)

    async def _handle_token(self, request: web.Request) -> web.Response:
        """OAuth 2.0 Token Endpoint (authorization_code)."""
        data = await request.post()
        grant_type = data.get("grant_type")
        code = data.get("code")
        client_id = data.get("client_id")
        client_secret = data.get("client_secret")

        if grant_type != "authorization_code":
            return web.json_response({"error": "unsupported_grant_type"}, status=400)

        record = self._auth_codes.pop(code, None)
        if not record:
            return web.json_response({"error": "invalid_grant"}, status=400)

        if client_id != record["client_id"]:
            return web.json_response({"error": "invalid_client"}, status=400)

        # Validate client secret if provided in registry
        client = self.client_registry.get(client_id)
        if client and client.client_secret and client_secret and client_secret != client.client_secret:
            return web.json_response({"error": "invalid_client"}, status=401)

        access_token = f"mcp_token_{secrets.token_urlsafe(32)}"

        return web.json_response(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": " ".join(record.get("scopes") or []),
            }
        )
