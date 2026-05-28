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
from parrot.security.vault_utils import (
    store_vault_credential,
    retrieve_vault_credential,
    delete_vault_credential,
)


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


class VaultTokenStore(TokenStore):
    """Vault-backed token store that encrypts OAuth tokens using AES-GCM.

    Persists tokens in the DocumentDB Vault (via vault_utils) so they survive
    agent restarts. Falls back gracefully when the credential is not found or
    vault keys are unavailable.

    The credential name follows the pattern ``mcp_oauth_{server_name}_{user_id}``.

    Example:
        >>> store = VaultTokenStore()
        >>> await store.set("user@co.com", "netsuite", token_dict)
        >>> token = await store.get("user@co.com", "netsuite")
    """

    _logger = logging.getLogger(__name__)

    @staticmethod
    def _vault_name(user_id: str, server_name: str) -> str:
        """Return the vault credential name for the given user and server.

        Argument order mirrors the ``TokenStore`` interface convention
        ``(user_id, server_name)`` used by ``get``/``set``/``delete``.

        Args:
            user_id: Caller's user identifier.
            server_name: MCP server slug (e.g. ``"netsuite"``).

        Returns:
            Vault credential name string following the pattern
            ``mcp_oauth_{server_name}_{user_id}``.
        """
        return f"mcp_oauth_{server_name}_{user_id}"

    async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve a stored OAuth token from the Vault.

        Args:
            user_id: Owner's user identifier.
            server_name: MCP server slug.

        Returns:
            Decrypted token dict, or ``None`` if not found or vault unavailable.
        """
        vault_name = self._vault_name(user_id, server_name)
        try:
            return await retrieve_vault_credential(user_id, vault_name)
        except KeyError:
            return None
        except RuntimeError as exc:
            self._logger.warning(
                "VaultTokenStore.get: vault keys unavailable for %s/%s — %s",
                user_id,
                server_name,
                exc,
            )
            return None

    async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None:
        """Encrypt and persist an OAuth token in the Vault.

        Degrades gracefully when vault keys are unavailable: logs a warning
        and returns without raising so the in-memory token remains usable.

        Args:
            user_id: Owner's user identifier.
            server_name: MCP server slug.
            token: Token dict to store (e.g. access_token, refresh_token, expires_at).
        """
        vault_name = self._vault_name(user_id, server_name)
        try:
            await store_vault_credential(user_id, vault_name, token)
        except RuntimeError as exc:
            self._logger.warning(
                "VaultTokenStore.set: vault keys unavailable for %s/%s — %s",
                user_id,
                server_name,
                exc,
            )

    async def delete(self, user_id: str, server_name: str) -> None:
        """Remove a stored OAuth token from the Vault.

        Tolerates a missing credential (already deleted) and vault
        unavailability — both are logged at warning level without raising.

        Args:
            user_id: Owner's user identifier.
            server_name: MCP server slug.
        """
        vault_name = self._vault_name(user_id, server_name)
        try:
            await delete_vault_credential(user_id, vault_name)
        except (KeyError, RuntimeError) as exc:
            self._logger.warning(
                "VaultTokenStore.delete: could not delete token for %s/%s — %s",
                user_id,
                server_name,
                exc,
            )


# ---- Simple Dynamic Client Registration ----


class NetSuiteM2MAuth:
    """OAuth2 Client Credentials (M2M) for NetSuite using certificate-based JWT assertion.

    NetSuite M2M requires a signed JWT as the ``client_assertion`` when
    requesting an access token. The JWT is signed with the private key whose
    matching X.509 certificate was uploaded to the NetSuite Integration Record.

    Args:
        client_id: OAuth2 client ID from the NetSuite integration record.
        certificate_id: Certificate ID shown in NetSuite after uploading the
            public certificate.
        private_key_path: Path to the PEM-encoded RSA private key file.
        account_id: NetSuite account ID (e.g. ``"4984231"``).
        token_url: NetSuite token endpoint. Built automatically when ``None``.
        scopes: OAuth2 scopes (default ``["mcp"]``).
        token_store: Optional :class:`TokenStore` for persisting tokens.
    """

    def __init__(
        self,
        *,
        client_id: str,
        certificate_id: str,
        private_key_path: str,
        account_id: str,
        token_url: str | None = None,
        scopes: list[str] | None = None,
        token_store: TokenStore | None = None,
    ):
        self.client_id = client_id
        self.certificate_id = certificate_id
        self.account_id = account_id
        self.scopes = scopes or ["mcp"]
        self.token_store = token_store or InMemoryTokenStore()
        self._logger = logging.getLogger("NetSuiteM2MAuth")

        self.token_url = token_url or (
            f"https://{account_id}.suitetalk.api.netsuite.com"
            "/services/rest/auth/oauth2/v1/token"
        )

        from cryptography.hazmat.primitives import serialization
        with open(private_key_path, "rb") as f:
            self._private_key = serialization.load_pem_private_key(f.read(), password=None)

        self._token: dict | None = None
        self._server_name = "netsuite"

    def _build_assertion(self) -> str:
        """Build a signed JWT client assertion for the token request."""
        import jwt as pyjwt

        now = _now()
        payload = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": self.token_url,
            "iat": now,
            "exp": now + 300,
            "scope": " ".join(self.scopes),
        }
        headers = {"kid": self.certificate_id}
        return pyjwt.encode(payload, self._private_key, algorithm="RS256", headers=headers)

    async def ensure_token(self, user_id: str = "m2m") -> str:
        """Obtain or refresh an access token via Client Credentials grant."""
        stored = await self.token_store.get(user_id, self._server_name)
        if stored and stored.get("expires_at", 0) - _now() > 60:
            self._token = stored
            return stored["access_token"]

        assertion = self._build_assertion()
        async with ClientSession() as sess:
            data = {
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
            }
            async with sess.post(self.token_url, data=data, timeout=30) as resp:
                tok = await resp.json()
                if resp.status != 200 or "access_token" not in tok:
                    raise RuntimeError(
                        f"NetSuite M2M token exchange failed ({resp.status}): {tok}"
                    )

        expires_in = int(tok.get("expires_in", 3600))
        self._token = {
            "access_token": tok["access_token"],
            "token_type": tok.get("token_type", "Bearer"),
            "expires_in": expires_in,
            "expires_at": _now() + expires_in,
            "scope": tok.get("scope"),
            "raw": tok,
        }
        await self.token_store.set(user_id, self._server_name, self._token)
        self._logger.info("NetSuite M2M token acquired (expires in %ds)", expires_in)
        return self._token["access_token"]

    def token_supplier(self) -> str | None:
        """Synchronous hook called by the HTTP transport before each request."""
        if not self._token:
            return None
        if self._token.get("expires_at", 0) - _now() < 60:
            return None
        return self._token.get("access_token")


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

