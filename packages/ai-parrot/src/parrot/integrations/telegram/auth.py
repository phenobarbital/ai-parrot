"""Telegram user authentication — strategies and session management.

Provides an abstract auth strategy interface with concrete implementations
for Navigator Basic Auth and OAuth2 providers.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlencode
import base64
import hashlib
import json
import secrets
import time

import aiohttp
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
)
from navconfig.logging import logging

from .oauth2_providers import get_provider, OAuth2ProviderConfig


logger = logging.getLogger("parrot.Telegram.Auth")


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------

@dataclass
class TelegramUserSession:
    """Cached identity for a Telegram user within a chat session."""

    telegram_id: int
    telegram_username: Optional[str] = None
    telegram_first_name: Optional[str] = None
    telegram_last_name: Optional[str] = None
    # Populated after Navigator login:
    nav_user_id: Optional[str] = None
    nav_session_token: Optional[str] = None
    nav_display_name: Optional[str] = None
    nav_email: Optional[str] = None
    authenticated: bool = False
    authenticated_at: Optional[datetime] = None
    metadata: Dict = field(default_factory=dict)
    # OAuth2-specific fields:
    oauth2_access_token: Optional[str] = None
    oauth2_id_token: Optional[str] = None
    oauth2_provider: Optional[str] = None

    @property
    def user_id(self) -> str:
        """Return nav_user_id if authenticated, else telegram identifier."""
        if self.authenticated and self.nav_user_id:
            return self.nav_user_id
        return f"tg:{self.telegram_id}"

    @property
    def session_id(self) -> str:
        """Stable session key for conversation memory."""
        return f"tg_chat:{self.telegram_id}"

    @property
    def display_name(self) -> str:
        """Human-readable name for display."""
        if self.nav_display_name:
            return self.nav_display_name
        parts = []
        if self.telegram_first_name:
            parts.append(self.telegram_first_name)
        if self.telegram_last_name:
            parts.append(self.telegram_last_name)
        if parts:
            return " ".join(parts)
        if self.telegram_username:
            return f"@{self.telegram_username}"
        return f"User {self.telegram_id}"

    def set_authenticated(
        self,
        nav_user_id: str,
        session_token: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        **extra_meta,
    ) -> None:
        """Mark session as authenticated with Navigator credentials."""
        self.nav_user_id = nav_user_id
        self.nav_session_token = session_token
        self.nav_display_name = display_name
        self.nav_email = email
        self.authenticated = True
        self.authenticated_at = datetime.now()
        if extra_meta:
            self.metadata.update(extra_meta)

    def clear_auth(self) -> None:
        """Clear authentication state (logout)."""
        self.nav_user_id = None
        self.nav_session_token = None
        self.nav_display_name = None
        self.nav_email = None
        self.authenticated = False
        self.authenticated_at = None
        self.metadata.clear()
        # Clear OAuth2 fields
        self.oauth2_access_token = None
        self.oauth2_id_token = None
        self.oauth2_provider = None


# ---------------------------------------------------------------------------
# Navigator Basic-Auth client (unchanged, used internally by BasicAuthStrategy)
# ---------------------------------------------------------------------------

class NavigatorAuthClient:
    """Authenticate Telegram users against Navigator API."""

    def __init__(self, auth_url: str, timeout: int = 15):
        self.auth_url = auth_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def login(
        self, username: str, password: str
    ) -> Optional[Dict]:
        """Authenticate against Navigator API.

        Returns dict with user info on success, None on failure.
        Expected response: {"user_id": ..., "display_name": ..., "token": ...}
        """
        payload = {"username": username, "password": password}
        headers = {
            "Content-Type": "application/json",
            "x-auth-method": "BasicAuth",
        }
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.auth_url,
                    json=payload,
                    headers=headers,
                    ssl=False,  # Allow self-signed certs for local dev
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(
                            f"Navigator login successful for '{username}'"
                        )
                        return data
                    logger.warning(
                        f"Navigator login failed for '{username}': "
                        f"HTTP {resp.status}"
                    )
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Navigator auth request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Navigator auth: {e}")
            return None

    async def validate_token(self, token: str) -> bool:
        """Validate an existing session token (optional future use)."""
        # Placeholder for token validation endpoint
        return bool(token)


# ---------------------------------------------------------------------------
# Auth strategy abstraction
# ---------------------------------------------------------------------------

class AbstractAuthStrategy(ABC):
    """Base class for Telegram authentication strategies.

    Each strategy knows how to:
    - Build a login keyboard (WebApp button) for the Telegram user.
    - Handle the callback data returned from the WebApp.
    - Validate an existing session token.
    """

    @abstractmethod
    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
    ) -> ReplyKeyboardMarkup:
        """Return the keyboard markup with the login button/WebApp.

        Args:
            config: TelegramAgentConfig instance.
            state: CSRF state token for the auth flow.

        Returns:
            aiogram ReplyKeyboardMarkup with the login button.
        """
        ...

    @abstractmethod
    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Process auth callback data returned from the WebApp.

        Args:
            data: Parsed JSON data from ``message.web_app_data``.
            session: The user's Telegram session to populate.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        ...

    @abstractmethod
    async def validate_token(self, token: str) -> bool:
        """Validate an existing session token.

        Args:
            token: The session or access token to validate.

        Returns:
            True if the token is still valid.
        """
        ...


# ---------------------------------------------------------------------------
# Basic-Auth strategy (wraps NavigatorAuthClient)
# ---------------------------------------------------------------------------

class BasicAuthStrategy(AbstractAuthStrategy):
    """Navigator Basic Auth strategy.

    Wraps the existing ``NavigatorAuthClient`` and produces the same WebApp
    keyboard / callback handling that the wrapper used before the strategy
    refactor.

    Args:
        auth_url: Navigator authentication endpoint URL.
        login_page_url: URL of the static login HTML page served to the
            Telegram WebApp.
    """

    def __init__(
        self,
        auth_url: str,
        login_page_url: Optional[str] = None,
    ):
        self.auth_url = auth_url
        self.login_page_url = login_page_url
        self._client = NavigatorAuthClient(auth_url)
        self.logger = logging.getLogger("parrot.Telegram.Auth.Basic")

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
    ) -> ReplyKeyboardMarkup:
        """Build the Navigator login WebApp keyboard.

        Args:
            config: TelegramAgentConfig (used for login_page_url fallback).
            state: CSRF state token (unused for basic auth, kept for interface
                   consistency).

        Returns:
            ReplyKeyboardMarkup with a WebApp button pointing to the login page.

        Raises:
            ValueError: If no login_page_url is configured.
        """
        page_url = self.login_page_url or getattr(config, "login_page_url", None)
        if not page_url:
            raise ValueError(
                "login_page_url is required for BasicAuthStrategy"
            )

        full_url = f"{page_url}?{urlencode({'auth_url': self.auth_url})}"

        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="\U0001f510 Sign in to Navigator",
                    web_app=WebAppInfo(url=full_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Handle Navigator login callback data.

        Expects ``data`` to contain ``user_id``, ``token``, and optionally
        ``display_name`` and ``email``.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
            session: User session to populate on success.

        Returns:
            True if the callback contained valid user info.
        """
        nav_user_id = data.get("user_id")
        if not nav_user_id:
            self.logger.warning("Basic auth callback missing user_id")
            return False

        token = data.get("token", "")
        display_name = data.get("display_name", "")
        email = data.get("email", "")

        session.set_authenticated(
            nav_user_id=str(nav_user_id),
            session_token=token,
            display_name=display_name,
            email=email,
        )

        self.logger.info(
            "User tg:%s authenticated as nav:%s (%s)",
            session.telegram_id,
            nav_user_id,
            display_name,
        )
        return True

    async def validate_token(self, token: str) -> bool:
        """Validate a Navigator session token.

        Args:
            token: The session token to validate.

        Returns:
            True if the token is valid.
        """
        return await self._client.validate_token(token)


# ---------------------------------------------------------------------------
# Azure SSO strategy (delegates to Navigator's /api/v1/auth/azure/ endpoint)
# ---------------------------------------------------------------------------

# Azure session TTL — 4 days per spec.
_AZURE_TOKEN_TTL = timedelta(days=4)


class AzureAuthStrategy(AbstractAuthStrategy):
    """Navigator Azure AD SSO strategy.

    Delegates the full OAuth2 flow to Navigator's /api/v1/auth/azure/ endpoint.
    The bot only captures the JWT token returned via redirect. No signature
    verification is performed; Navigator is the trusted issuer.

    Args:
        auth_url: Navigator base authentication endpoint URL (used for token
            validation via NavigatorAuthClient).
        azure_auth_url: Navigator's Azure SSO endpoint URL.
            E.g. ``https://nav.example.com/api/v1/auth/azure/``.
        login_page_url: URL of the static ``azure_login.html`` page served
            to the Telegram WebApp.
    """

    def __init__(
        self,
        auth_url: str,
        azure_auth_url: str,
        login_page_url: Optional[str] = None,
    ) -> None:
        self.auth_url = auth_url
        self.azure_auth_url = azure_auth_url
        self.login_page_url = login_page_url
        self._client = NavigatorAuthClient(auth_url)
        self.logger = logging.getLogger("parrot.Telegram.Auth.Azure")

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
    ) -> ReplyKeyboardMarkup:
        """Build the Azure SSO WebApp keyboard.

        Args:
            config: TelegramAgentConfig (used for login_page_url fallback).
            state: CSRF state token (kept for interface consistency; Azure flow
                uses Navigator-managed state internally).

        Returns:
            ReplyKeyboardMarkup with a WebApp button pointing to
            ``azure_login.html?azure_auth_url=...``.

        Raises:
            ValueError: If no login_page_url is configured.
        """
        page_url = self.login_page_url or getattr(config, "login_page_url", None)
        if not page_url:
            raise ValueError(
                "login_page_url is required for AzureAuthStrategy"
            )

        full_url = f"{page_url}?{urlencode({'azure_auth_url': self.azure_auth_url})}"

        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text="\U0001f510 Sign in with Azure",
                    web_app=WebAppInfo(url=full_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Process Azure SSO callback: decode JWT and populate session.

        Expects ``data`` to contain ``token`` (the Navigator JWT returned
        after Azure SSO redirect).  Decodes the payload to extract user
        identity fields and calls ``session.set_authenticated()``.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
                Must contain ``{"auth_method": "azure", "token": "<jwt>"}``.
            session: User session to populate on success.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        token = data.get("token")
        if not token:
            self.logger.warning("Azure auth callback missing token")
            return False

        try:
            claims = self._decode_jwt_payload(token)
        except (ValueError, json.JSONDecodeError, Exception) as exc:
            self.logger.warning("Failed to decode Azure JWT: %s", exc)
            return False

        # Extract user identity — handle both user_id and sub claims
        user_id = claims.get("user_id") or claims.get("sub") or ""
        if not user_id:
            self.logger.warning("Azure JWT missing user_id/sub claim")
            return False

        email = claims.get("email", "")
        # Handle both name and first_name/last_name claims
        display_name = claims.get("name") or claims.get("first_name", "")
        if claims.get("last_name"):
            display_name = f"{display_name} {claims['last_name']}".strip()

        session.set_authenticated(
            nav_user_id=str(user_id),
            session_token=token,
            display_name=display_name or None,
            email=email or None,
        )

        self.logger.info(
            "User tg:%s authenticated via Azure as %s (%s)",
            session.telegram_id,
            user_id,
            display_name,
        )
        return True

    async def validate_token(self, token: str) -> bool:
        """Validate a Navigator JWT token.

        Args:
            token: The JWT session token to validate.

        Returns:
            True if the token is valid.
        """
        return await self._client.validate_token(token)

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]:
        """Decode the payload segment of a JWT without signature verification.

        Navigator is the trusted issuer; we only need the claims.

        Args:
            token: A three-part JWT string ``header.payload.signature``.

        Returns:
            Decoded payload as a dictionary.

        Raises:
            ValueError: If the token does not have exactly three parts.
            json.JSONDecodeError: If the payload is not valid JSON.
        """
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid JWT format: expected 3 parts, got {len(parts)}"
            )
        payload_b64 = parts[1]
        # Add base64 padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)


# ---------------------------------------------------------------------------
# OAuth2 strategy (Authorization Code + PKCE)
# ---------------------------------------------------------------------------

# Default token TTL — sessions expire after this duration.
_TOKEN_TTL = timedelta(days=7)

# Pending OAuth2 states expire after this many seconds.
_STATE_TTL_SECONDS = 600  # 10 minutes


class OAuth2AuthStrategy(AbstractAuthStrategy):
    """OAuth2 Authorization Code strategy with PKCE.

    Handles the full OAuth2 flow:
    1. Build an authorization URL (with PKCE code_challenge).
    2. After the user authenticates, exchange the code for tokens.
    3. Fetch user profile from the provider's userinfo endpoint.

    Args:
        config: TelegramAgentConfig with OAuth2 settings populated.
    """

    def __init__(self, config: Any) -> None:
        self._provider: OAuth2ProviderConfig = get_provider(
            getattr(config, "oauth2_provider", "google")
        )
        self._client_id: str = getattr(config, "oauth2_client_id", None) or ""
        self._client_secret: str = getattr(config, "oauth2_client_secret", None) or ""
        self._redirect_uri: str = getattr(config, "oauth2_redirect_uri", None) or ""

        # Validate required fields early
        missing = []
        if not self._client_id:
            missing.append("oauth2_client_id")
        if not self._client_secret:
            missing.append("oauth2_client_secret")
        if not self._redirect_uri:
            missing.append("oauth2_redirect_uri")
        if missing:
            raise ValueError(
                f"OAuth2AuthStrategy requires config fields: {', '.join(missing)}"
            )

        self._scopes: list[str] = (
            config.oauth2_scopes
            if config.oauth2_scopes
            else list(self._provider.default_scopes)
        )
        # Maps state → (code_verifier, created_timestamp)
        self._pending_states: Dict[str, Tuple[str, float]] = {}
        self._http_timeout = aiohttp.ClientTimeout(total=15)
        self.logger = logging.getLogger("parrot.Telegram.Auth.OAuth2")

    # -- PKCE helpers -------------------------------------------------------

    @staticmethod
    def _generate_pkce() -> Tuple[str, str]:
        """Generate a PKCE code_verifier and code_challenge (S256).

        Returns:
            Tuple of (code_verifier, code_challenge).
        """
        code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = (
            base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        )
        return code_verifier, code_challenge

    # -- State management ---------------------------------------------------

    def _store_state(self, state: str, code_verifier: str) -> None:
        """Store a pending OAuth2 state with its PKCE verifier."""
        self._cleanup_expired_states()
        self._pending_states[state] = (code_verifier, time.monotonic())

    def _consume_state(self, state: str) -> Optional[str]:
        """Consume a pending state and return the code_verifier.

        Returns None if the state is unknown or expired.
        """
        self._cleanup_expired_states()
        entry = self._pending_states.pop(state, None)
        if entry is None:
            return None
        code_verifier, _ = entry
        return code_verifier

    def _cleanup_expired_states(self) -> None:
        """Remove states older than ``_STATE_TTL_SECONDS``."""
        now = time.monotonic()
        expired = [
            s for s, (_, ts) in self._pending_states.items()
            if (now - ts) > _STATE_TTL_SECONDS
        ]
        for s in expired:
            del self._pending_states[s]

    # -- AbstractAuthStrategy implementation --------------------------------

    async def build_login_keyboard(
        self,
        config: Any,
        state: str,
    ) -> ReplyKeyboardMarkup:
        """Build the OAuth2 authorization keyboard.

        Generates PKCE challenge, stores the state, and returns a
        ``ReplyKeyboardMarkup`` with a WebApp button pointing to the
        provider's authorization URL.

        Args:
            config: TelegramAgentConfig instance.
            state: CSRF state token for the auth flow.

        Returns:
            aiogram ReplyKeyboardMarkup.
        """
        code_verifier, code_challenge = self._generate_pkce()
        self._store_state(state, code_verifier)

        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
        }
        authorize_url = (
            f"{self._provider.authorization_url}?{urlencode(params)}"
        )

        provider_label = self._provider.name.capitalize()
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(
                    text=f"\U0001f510 Sign in with {provider_label}",
                    web_app=WebAppInfo(url=authorize_url),
                )]
            ],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

    async def handle_callback(
        self,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> bool:
        """Handle the OAuth2 callback from Telegram WebApp.

        Expects ``data`` to contain ``code`` and ``state``.  Exchanges
        the code for tokens, fetches userinfo, and populates the session.

        Args:
            data: Parsed JSON from Telegram WebApp sendData().
            session: User session to populate on success.

        Returns:
            True if authentication succeeded.
        """
        code = data.get("code")
        state = data.get("state")

        if not code or not state:
            self.logger.warning("OAuth2 callback missing code or state")
            return False

        # Validate and consume the state
        code_verifier = self._consume_state(state)
        if code_verifier is None:
            self.logger.warning(
                "OAuth2 callback with unknown or expired state"
            )
            return False

        # Exchange code for tokens
        token_data = await self.exchange_code(code, code_verifier)
        if token_data is None:
            return False

        access_token = token_data.get("access_token", "")
        id_token = token_data.get("id_token", "")

        if not access_token:
            self.logger.warning("Token exchange returned no access_token")
            return False

        # Fetch user profile
        userinfo = await self.fetch_userinfo(access_token)
        if userinfo is None:
            return False

        # Populate session
        user_id = userinfo.get("sub", "")
        display_name = userinfo.get("name", "")
        email = userinfo.get("email", "")

        session.set_authenticated(
            nav_user_id=str(user_id),
            session_token=access_token,
            display_name=display_name,
            email=email,
        )
        session.oauth2_access_token = access_token
        session.oauth2_id_token = id_token
        session.oauth2_provider = self._provider.name

        self.logger.info(
            "User tg:%s authenticated via %s as %s (%s)",
            session.telegram_id,
            self._provider.name,
            user_id,
            display_name,
        )
        return True

    async def validate_token(
        self, token: str, session: Optional[TelegramUserSession] = None,
    ) -> bool:
        """Check that the token is non-empty and the session hasn't exceeded the 7-day TTL.

        Args:
            token: The OAuth2 access token to validate.
            session: Optional user session; when provided, the 7-day TTL
                is enforced via ``authenticated_at``.

        Returns:
            True if the token is valid and (if session given) not expired.
        """
        if not token:
            return False
        if session is not None and self.is_session_expired(session):
            return False
        return True

    def is_session_expired(self, session: TelegramUserSession) -> bool:
        """Check if a session's authentication has exceeded the 7-day TTL.

        Args:
            session: The user session to check.

        Returns:
            True if the session is expired or not authenticated.
        """
        if not session.authenticated or not session.authenticated_at:
            return True
        return (datetime.now() - session.authenticated_at) > _TOKEN_TTL

    # -- HTTP helpers -------------------------------------------------------

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
    ) -> Optional[Dict[str, Any]]:
        """Exchange an authorization code for tokens.

        Args:
            code: The authorization code from the provider redirect.
            code_verifier: PKCE code verifier for this flow.

        Returns:
            Token response dict on success, None on failure.
        """
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code_verifier": code_verifier,
        }
        try:
            async with aiohttp.ClientSession(
                timeout=self._http_timeout
            ) as http:
                async with http.post(
                    self._provider.token_url,
                    data=payload,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    body = await resp.text()
                    self.logger.warning(
                        "Token exchange failed: HTTP %s — %s",
                        resp.status,
                        body[:200],
                    )
                    return None
        except aiohttp.ClientError as exc:
            self.logger.error("Token exchange HTTP error: %s", exc)
            return None
        except Exception as exc:
            self.logger.error("Unexpected token exchange error: %s", exc)
            return None

    async def fetch_userinfo(
        self,
        access_token: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch user profile from the provider's userinfo endpoint.

        Args:
            access_token: Bearer token for the userinfo request.

        Returns:
            Userinfo dict on success, None on failure.
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with aiohttp.ClientSession(
                timeout=self._http_timeout
            ) as http:
                async with http.get(
                    self._provider.userinfo_url,
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    self.logger.warning(
                        "Userinfo fetch failed: HTTP %s",
                        resp.status,
                    )
                    return None
        except aiohttp.ClientError as exc:
            self.logger.error("Userinfo HTTP error: %s", exc)
            return None
        except Exception as exc:
            self.logger.error("Unexpected userinfo error: %s", exc)
            return None
