"""Telegram user authentication against Navigator API."""

from typing import Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp
from navconfig.logging import logging


logger = logging.getLogger("parrot.Telegram.Auth")


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
