from typing import Optional, Dict, Any
import os
import sys
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
