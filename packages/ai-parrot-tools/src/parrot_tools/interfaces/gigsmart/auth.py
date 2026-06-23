"""GigSmart OAuth 2.1 authentication — token lifecycle management.

Supports two grant types:

* **client_credentials** (server-to-server) — read-only scopes, 15 min tokens.
  Tokens are obtained via HTTP Basic auth to ``/oauth/token``.
* **auth_code + PKCE** (user-facing) — full read+write access, 1 h tokens.
  Requires a user authorisation step; exchange code at ``/oauth/token`` with
  ``code_verifier``.

Pre-configured refresh tokens (from ``GIGSMART_REFRESH_TOKEN``) allow headless
agents to obtain write access without an interactive OAuth flow.

Token caching is in-memory; an ``asyncio.Lock`` prevents concurrent refreshes.
Write-scope enforcement raises ``GigSmartAuthError`` when a write operation is
attempted with a token that only has read scopes.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import aiohttp

from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import GigSmartAuthError, GigSmartError

# ---------------------------------------------------------------------------
# Scope classification
# ---------------------------------------------------------------------------

#: Scopes that are only obtainable via the auth_code grant (not client_credentials).
_WRITE_ONLY_SCOPES: frozenset[str] = frozenset({
    "write:gigs",
    "write:engagements",
    "write:organizations",
    "write:positions",
    "write:locations",
    "write:messages",
    "read:messages",  # messages read also auth_code only per spec
})

# ---------------------------------------------------------------------------
# Token store (in-process cache)
# ---------------------------------------------------------------------------


class _TokenCache:
    """In-process cache for a single OAuth token."""

    def __init__(self) -> None:
        self.access_token: str | None = None
        self.expires_at: datetime | None = None
        self.scopes: frozenset[str] = frozenset()
        self.refresh_token: str | None = None
        self.grant_type: str | None = None  # "client_credentials" | "auth_code"

    def is_valid(self) -> bool:
        """Return True when a token is cached and has not expired."""
        if not self.access_token or not self.expires_at:
            return False
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return remaining > 0

    def needs_refresh(self, threshold_seconds: int = 120) -> bool:
        """Return True when the token will expire within *threshold_seconds*."""
        if not self.access_token or not self.expires_at:
            return True
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return remaining < threshold_seconds

    def store(
        self,
        access_token: str,
        expires_in: int,
        scopes: list[str],
        refresh_token: str | None,
        grant_type: str,
    ) -> None:
        """Persist a fresh token response into the cache."""
        self.access_token = access_token
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        self.scopes = frozenset(scopes)
        self.refresh_token = refresh_token
        self.grant_type = grant_type


# ---------------------------------------------------------------------------
# GigSmartAuth
# ---------------------------------------------------------------------------


class GigSmartAuth:
    """OAuth 2.1 token lifecycle manager for the GigSmart API.

    Args:
        config: GigSmartConfig instance carrying client credentials and endpoints.

    Example::

        auth = GigSmartAuth(config)
        token = await auth.get_token(scopes=["read:gigs"])
        headers = await auth.build_headers()
    """

    def __init__(self, config: GigSmartConfig) -> None:
        self._config = config
        self._cache = _TokenCache()
        self._lock = asyncio.Lock()
        self._session: aiohttp.ClientSession | None = None
        self.logger = logging.getLogger(__name__)

        # If a pre-configured refresh token is available, seed the cache
        # so the first call uses a token-refresh flow rather than re-auth.
        if config.refresh_token:
            self._cache.refresh_token = config.refresh_token
            self._cache.grant_type = "auth_code"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def get_token(self, scopes: list[str] | None = None) -> str:
        """Return a valid access token, refreshing proactively if needed.

        Args:
            scopes: Optional list of OAuth scopes required for this call.
                If not specified, uses the token's cached scopes.

        Returns:
            The current access token string.

        Raises:
            GigSmartAuthError: If token acquisition fails or the requested
                scopes are unavailable for the configured grant type.
        """
        async with self._lock:
            if self._cache.needs_refresh():
                await self._acquire_token(scopes=scopes)
            return self._cache.access_token  # type: ignore[return-value]

    async def build_headers(self) -> dict[str, str]:
        """Return HTTP headers with a valid Bearer token.

        Returns:
            A dict containing the ``Authorization`` header.
        """
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def ensure_scope(self, scope: str) -> None:
        """Assert that the current token grants *scope*, raising otherwise.

        Validates both that the token has the scope and that the grant type
        supports it (write scopes require auth_code, not client_credentials).

        Args:
            scope: A single scope string to check, e.g. ``"write:gigs"``.

        Raises:
            GigSmartAuthError: When the current grant type does not allow
                the requested write scope.
        """
        # Write scopes require auth_code grant
        if scope in _WRITE_ONLY_SCOPES:
            grant = self._cache.grant_type
            if grant == "client_credentials":
                raise GigSmartAuthError(
                    f"write scope '{scope}' requires auth_code grant; "
                    "client_credentials tokens only provide read access."
                )

        # If token is cached and valid, check scope membership
        if self._cache.is_valid() and self._cache.scopes:
            if scope not in self._cache.scopes:
                raise GigSmartAuthError(
                    f"Scope '{scope}' not granted by the current access token "
                    f"(token scopes: {sorted(self._cache.scopes)!r})."
                )

    async def refresh_token(self) -> str:
        """Force a token refresh using the cached refresh_token.

        Returns:
            The new access token string.

        Raises:
            GigSmartAuthError: If no refresh token is available or the
                refresh request fails.
        """
        async with self._lock:
            await self._do_refresh()
            return self._cache.access_token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # PKCE helpers (static — usable without instance)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Generate a PKCE ``(code_verifier, code_challenge)`` pair.

        The code challenge uses SHA-256 hashed, base64url-encoded verifier
        (``code_challenge_method=S256``).

        Returns:
            A ``(code_verifier, code_challenge)`` tuple of URL-safe strings.
        """
        # 43-128 characters: use 64 random bytes → 86 base64url chars
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return code_verifier, code_challenge

    def build_authorize_url(
        self,
        redirect_uri: str,
        scopes: list[str],
        code_challenge: str,
        state: str | None = None,
    ) -> str:
        """Build the OAuth authorisation URL for the auth_code + PKCE flow.

        Args:
            redirect_uri: The URI where the user will be sent after authorisation.
            scopes: List of OAuth scopes to request.
            code_challenge: The PKCE code challenge (base64url SHA-256 of verifier).
            state: Optional opaque state string for CSRF protection.

        Returns:
            The fully-formed authorisation URL string.
        """
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if state:
            params["state"] = state
        return f"{self._config.authorize_url}?{urlencode(params)}"

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> str:
        """Exchange an authorisation code for an access token (auth_code+PKCE).

        Args:
            code: The authorisation code received from the redirect.
            redirect_uri: Must match the URI used in :meth:`build_authorize_url`.
            code_verifier: The PKCE code verifier generated alongside the challenge.

        Returns:
            The new access token string.

        Raises:
            GigSmartAuthError: If the exchange fails.
        """
        async with self._lock:
            await self._do_code_exchange(code, redirect_uri, code_verifier)
            return self._cache.access_token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Private token acquisition methods
    # ------------------------------------------------------------------

    async def _acquire_token(self, scopes: list[str] | None = None) -> None:
        """Choose and execute the correct token acquisition strategy."""
        # Prefer refresh if we have a refresh token
        if self._cache.refresh_token:
            try:
                await self._do_refresh()
                return
            except GigSmartAuthError:
                # Fall through to re-auth if refresh fails
                self.logger.warning("GigSmartAuth: refresh token failed; re-authenticating.")

        # Fall back to client_credentials
        await self._do_client_credentials(scopes=scopes)

    async def _do_client_credentials(self, scopes: list[str] | None = None) -> None:
        """Obtain a token via the client_credentials grant."""
        data: dict[str, str] = {"grant_type": "client_credentials"}
        if scopes:
            data["scope"] = " ".join(scopes)

        auth = aiohttp.BasicAuth(
            login=self._config.client_id,
            password=self._config.client_secret,
        )

        response_json = await self._post_token(data, auth=auth)
        access_token_val = response_json.get("access_token")
        if not access_token_val:
            raise GigSmartAuthError(
                f"Token endpoint response missing 'access_token': {list(response_json.keys())}"
            )
        self._cache.store(
            access_token=access_token_val,
            expires_in=response_json.get("expires_in", 900),
            scopes=response_json.get("scope", "").split(),
            refresh_token=response_json.get("refresh_token"),
            grant_type="client_credentials",
        )
        self.logger.debug("GigSmartAuth: acquired client_credentials token.")

    async def _do_refresh(self) -> None:
        """Refresh the access token using the stored refresh_token."""
        refresh_tok = self._cache.refresh_token
        if not refresh_tok:
            raise GigSmartAuthError("No refresh token available.")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_tok,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }
        response_json = await self._post_token(data)
        access_token_val = response_json.get("access_token")
        if not access_token_val:
            raise GigSmartAuthError(
                f"Token endpoint response missing 'access_token': {list(response_json.keys())}"
            )
        self._cache.store(
            access_token=access_token_val,
            expires_in=response_json.get("expires_in", 3600),
            scopes=response_json.get("scope", "").split(),
            refresh_token=response_json.get("refresh_token", refresh_tok),
            grant_type="auth_code",
        )
        self.logger.debug("GigSmartAuth: refreshed access token.")

    async def _do_code_exchange(
        self, code: str, redirect_uri: str, code_verifier: str
    ) -> None:
        """Exchange auth code for tokens (auth_code + PKCE)."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "code_verifier": code_verifier,
        }
        response_json = await self._post_token(data)
        access_token_val = response_json.get("access_token")
        if not access_token_val:
            raise GigSmartAuthError(
                f"Token endpoint response missing 'access_token': {list(response_json.keys())}"
            )
        self._cache.store(
            access_token=access_token_val,
            expires_in=response_json.get("expires_in", 3600),
            scopes=response_json.get("scope", "").split(),
            refresh_token=response_json.get("refresh_token"),
            grant_type="auth_code",
        )
        self.logger.debug("GigSmartAuth: obtained auth_code token via code exchange.")

    async def _post_token(
        self,
        data: dict[str, str],
        auth: aiohttp.BasicAuth | None = None,
    ) -> dict:
        """POST to the token endpoint and return the parsed JSON response.

        Args:
            data: URL-encoded form fields for the token request.
            auth: Optional HTTP Basic auth credentials.

        Returns:
            Parsed JSON response dict.

        Raises:
            GigSmartAuthError: On HTTP 4xx responses from the token endpoint.
            GigSmartError: On network errors or unexpected response format.
        """
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._config.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

        kwargs: dict = {
            "url": self._config.token_url,
            "data": data,
        }
        if auth:
            kwargs["auth"] = auth

        try:
            async with self._session.post(**kwargs) as resp:
                body = await resp.json(content_type=None)
                if resp.status == 401 or resp.status == 403:
                    raise GigSmartAuthError(
                        f"Token endpoint returned {resp.status}: "
                        f"{body.get('error_description', body.get('error', 'unauthorised'))}",
                        status_code=resp.status,
                    )
                if resp.status >= 400:
                    raise GigSmartError(
                        f"Token endpoint error {resp.status}: {body}",
                        status_code=resp.status,
                    )
                return body
        except aiohttp.ClientError as exc:
            raise GigSmartError(f"Network error reaching token endpoint: {exc}") from exc

    async def close(self) -> None:
        """Close the persistent token-fetch session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "GigSmartAuth":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
