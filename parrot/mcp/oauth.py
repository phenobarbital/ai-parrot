import os
import sys
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


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _now() -> int:
    return int(time.time())


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


class TokenStore:
    """Abstract token store interface."""
    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
    async def delete(self, user_id: str, server_name: str) -> None: ...

class InMemoryTokenStore(TokenStore):
    """Simple in-memory token store (not persistent)."""
    def __init__(self):
        self._data = {}

    async def get(self, user_id, server_name):
        return self._data.get((user_id, server_name))

    async def set(self, user_id, server_name, token):
        self._data[(user_id, server_name)] = token

    async def delete(self, user_id, server_name):
        self._data.pop((user_id, server_name), None)

class RedisTokenStore(TokenStore):
    """Redis-based token store."""
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def _key(user_id: str, server_name: str) -> str:
        return f"mcp:oauth:{server_name}:{user_id}"

    async def get(self, user_id, server_name):
        raw = await self.redis.get(self._key(user_id, server_name))
        return json.loads(raw) if raw else None

    async def set(self, user_id, server_name, token):
        # store with TTL ~ refresh time + cushion if you want, or none
        await self.redis.set(self._key(user_id, server_name), json.dumps(token))

    async def delete(self, user_id, server_name):
        await self.redis.delete(self._key(user_id, server_name))


# ---- Simple Dynamic Client Registration ----

@dataclass
class RegisteredClient:
    """Represents a registered OAuth client."""
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
        self._clients: Dict[str, RegisteredClient] = {}

    def register(self, metadata: Dict[str, Any]) -> RegisteredClient:
        if "redirect_uris" not in metadata:
            raise ValueError("redirect_uris is required for client registration")

        client_id = metadata.get("client_id") or secrets.token_urlsafe(16)
        client_secret = metadata.get("client_secret") or secrets.token_urlsafe(32)
        client_name = metadata.get("client_name") or metadata.get("client_name", "mcp-client")
        redirect_uris = metadata["redirect_uris"]
        scopes = metadata.get("scope", "") or metadata.get("scopes", [])
        if isinstance(scopes, str):
            scopes = scopes.split()

        client = RegisteredClient(
            client_id=client_id,
            client_secret=client_secret,
            client_name=client_name,
            redirect_uris=redirect_uris,
            scopes=scopes,
        )
        self._clients[client_id] = client
        return client

    def get(self, client_id: str) -> Optional[RegisteredClient]:
        return self._clients.get(client_id)


class OAuthManager:
    """
    Manages Authorization Code + PKCE flow, token storage, auto refresh,
    and supplies a token string for headers.
    """
    def __init__(
        self,
        *,
        user_id: str,
        server_name: str,
        client_id: str,
        auth_url: str,
        token_url: str,
        scopes: list[str],
        redirect_host: str = "127.0.0.1",
        redirect_port: int = 8765,
        redirect_path: str = "/mcp/oauth/callback",
        token_store: TokenStore,
        client_secret: str | None = None,  # if provider requires it
        extra_token_params: dict | None = None,
        http_timeout: float = 15.0,
    ):
        self.user_id = user_id
        self.server_name = server_name
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.token_url = token_url
        self.scopes = scopes
        self.redirect_host = redirect_host
        self.redirect_port = redirect_port
        self.redirect_path = redirect_path
        self.redirect_uri = f"http://{redirect_host}:{redirect_port}{redirect_path}"
        self.token_store = token_store
        self.extra_token_params = extra_token_params or {}
        self.http_timeout = http_timeout

        self._state = secrets.token_urlsafe(24)
        self._verifier = _b64url(os.urandom(32))
        self._challenge = _b64url(hashlib.sha256(self._verifier.encode()).digest())
        self._token: dict | None = None
        self._ready = asyncio.Event()

    def token_supplier(self) -> Optional[str]:
        # Synchronous hook invoked by the HTTP client layer.
        # We return the current access_token if not expired; otherwise None (caller should await ensure_token()).
        if not self._token:
            return None
        # If near expiry (e.g., within 60s), signal refresh needed
        if self._token.get("expires_at") and self._token["expires_at"] - _now() < 60:
            return None
        return self._token.get("access_token")

    async def ensure_token(self) -> str:
        """
        Ensures a fresh access token exists:
         - Load from store
         - If expired and refresh_token present -> refresh
         - Else run interactive authorization (PKCE) with local callback
        Returns access_token.
        """
        # 1) Load cached
        cached = await self.token_store.get(self.user_id, self.server_name)
        if cached:
            self._token = cached

        # 2) If valid, return
        if self._is_token_valid(self._token):
            return self._token["access_token"]

        # 3) Try refresh
        if self._token and self._token.get("refresh_token"):
            ok = await self._refresh()
            if ok:
                return self._token["access_token"]

        # 4) Interactive auth
        await self._authorize_interactive()
        return self._token["access_token"]

    def _is_token_valid(self, tok: Optional[dict]) -> bool:
        if not tok:
            return False
        exp = tok.get("expires_at")
        return bool(tok.get("access_token")) and exp and exp > _now() + 30

    async def _authorize_interactive(self):
        app = web.Application()
        app.add_routes([web.get(self.redirect_path, self._handle_callback)])

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.redirect_host, self.redirect_port)
        await site.start()

        # Build auth URL
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": self._state,
            "code_challenge": self._challenge,
            "code_challenge_method": "S256",
        }
        url = f"{self.auth_url}?{urlencode(params)}"

        # Print URL (or open in browser)
        print(f"[OAuth] Please authenticate here:\n{url}", flush=True, file=sys.stderr)

        try:
            await asyncio.wait_for(self._ready.wait(), timeout=300)  # 5 minutes
        finally:
            await runner.cleanup()

        if not self._token:
            raise RuntimeError("OAuth failed: no token captured")

        await self.token_store.set(self.user_id, self.server_name, self._token)

    async def _handle_callback(self, request: web.Request):
        if request.query.get("state") != self._state:
            return web.Response(status=400, text="Invalid OAuth state")
        code = request.query.get("code")
        if not code:
            return web.Response(status=400, text="Missing code")

        # Exchange
        async with ClientSession() as sess:
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": self._verifier,
                **self.extra_token_params,
            }
            if self.client_secret:
                data["client_secret"] = self.client_secret

            async with sess.post(self.token_url, data=data, timeout=self.http_timeout) as resp:
                tok = await resp.json()
                if resp.status != 200:
                    return web.Response(status=resp.status, text=str(tok))

        self._token = self._normalize_token(tok)
        self._ready.set()
        return web.Response(text="Authentication complete. You can close this window.")

    async def _refresh(self) -> bool:
        async with ClientSession() as sess:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id": self.client_id,
                **self.extra_token_params,
            }
            if self.client_secret:
                data["client_secret"] = self.client_secret

            async with sess.post(self.token_url, data=data, timeout=self.http_timeout) as resp:
                tok = await resp.json()
                if resp.status != 200 or "access_token" not in tok:
                    return False

        self._token = self._normalize_token(tok, prev=self._token)
        await self.token_store.set(self.user_id, self.server_name, self._token)
        return True

    def _normalize_token(self, tok: Dict[str, Any], prev: Dict[str, Any] | None = None) -> Dict[str, Any]:
        # Expect providers to return: access_token, token_type, expires_in, refresh_token?
        expires_in = int(tok.get("expires_in", 3600))
        out = {
            "access_token": tok["access_token"],
            "token_type": tok.get("token_type", "Bearer"),
            "expires_in": expires_in,
            "expires_at": _now() + expires_in,
            "refresh_token": tok.get("refresh_token") or (prev.get("refresh_token") if prev else None),
            "scope": tok.get("scope"),
            "raw": tok,
        }
        return out


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
