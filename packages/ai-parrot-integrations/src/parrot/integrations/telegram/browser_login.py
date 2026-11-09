"""Browser-mode Telegram login (FEAT-854).

State registry correlating a CSRF ``state`` with a Telegram chat, the browser
identity-verification contract, and the browser result pages. The aiohttp
completion handler is appended by TASK-5424.

Never import ``auth.py`` or ``wrapper.py`` here: ``auth.py`` imports
``BROWSER_COMPLETE_PATH`` from this module.
"""

from __future__ import annotations

import html as html_mod
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, MutableMapping, Optional, Protocol, runtime_checkable

from navconfig.logging import logging
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

BROWSER_LOGIN_APP_KEY = "telegram_browser_login"
BROWSER_VERIFIERS_APP_KEY = "telegram_browser_identity_verifiers"
TELEGRAM_WRAPPERS_APP_KEY = "telegram_wrappers"
BROWSER_STATE_PREFIX = "browser."
BROWSER_COMPLETE_PATH = "/api/auth/telegram/browser-complete"
PAGE_AUTH_METHODS = frozenset({"basic", "azure", "google"})
_REGISTRY_TTL_SECONDS = 600  # same policy as auth.py:1058 (_STATE_TTL_SECONDS)
_STATE_RE = re.compile(r"browser\.[A-Za-z0-9_-]{43}")


def new_browser_state() -> str:
    """Return a fresh browser-mode CSRF state (``browser.`` + 32 random bytes)."""
    return BROWSER_STATE_PREFIX + secrets.token_urlsafe(32)


def is_browser_state(state: Optional[str]) -> bool:
    """Return True when ``state`` is in the browser namespace (routing only, not proof)."""
    return isinstance(state, str) and state.startswith(BROWSER_STATE_PREFIX)


@dataclass
class BrowserLoginEntry:
    """One pending browser-mode login, keyed by CSRF state."""

    state: str
    telegram_id: int
    chat_id: int
    bot_id: str
    bot_username: Optional[str]
    created_at: float  # time.monotonic()


class BrowserLoginRegistry:
    """In-process, TTL-bound state -> chat correlation for browser-mode logins."""

    def __init__(self, ttl_seconds: float = _REGISTRY_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: Dict[str, BrowserLoginEntry] = {}

    def _expired(self, entry: BrowserLoginEntry, now: float) -> bool:
        return (now - entry.created_at) > self._ttl

    def _sweep(self) -> None:
        now = time.monotonic()
        for state in [state for state, entry in self._entries.items() if self._expired(entry, now)]:
            del self._entries[state]

    def register(self, entry: BrowserLoginEntry) -> None:
        """Store a pending login; sweeps expired entries first."""
        if _STATE_RE.fullmatch(entry.state) is None:
            raise ValueError("Browser login state must use the browser namespace and contain 32 random bytes")
        self._sweep()
        self._entries[entry.state] = entry

    def consume(self, state: str) -> Optional[BrowserLoginEntry]:
        """Pop and return the entry (single-use); None if unknown or expired. Never awaits."""
        entry = self._entries.pop(state, None)
        if entry is None or self._expired(entry, time.monotonic()):
            return None
        return entry

    def peek(self, state: str) -> Optional[BrowserLoginEntry]:
        """Non-destructive lookup; never use a miss to select legacy routing."""
        entry = self._entries.get(state)
        if entry is None or self._expired(entry, time.monotonic()):
            return None
        return entry

    def __len__(self) -> int:
        return len(self._entries)


def get_or_create_browser_login_registry(app: MutableMapping[str, Any]) -> BrowserLoginRegistry:
    """Return the app-scoped registry, creating it under BROWSER_LOGIN_APP_KEY."""
    registry = app.get(BROWSER_LOGIN_APP_KEY)
    if registry is None:
        registry = BrowserLoginRegistry()
        app[BROWSER_LOGIN_APP_KEY] = registry
    return registry


class VerifiedBrowserIdentity(BaseModel):
    """Identity proven by a server-side verifier (never by browser JSON)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: str
    display_name: Optional[str] = None
    email: Optional[str] = None


class BrowserVerificationError(Exception):
    """The credential or identity was rejected (maps to HTTP 401)."""


class BrowserVerifierUnavailableError(Exception):
    """The verifier or its backend could not answer (maps to HTTP 503)."""


@runtime_checkable
class BrowserIdentityVerifier(Protocol):
    """Server-owned verifier bound to one issuer, audience/application and tenant."""

    async def verify(
        self,
        token: str,
        *,
        auth_method: str,
        bot_id: str,
        tenant_id: Optional[str],
    ) -> VerifiedBrowserIdentity:
        """Return the verified identity or raise one of the two typed errors."""
        ...


def register_browser_identity_verifier(
    app: MutableMapping[str, Any],
    *,
    bot_id: str,
    auth_method: str,
    verifier: BrowserIdentityVerifier,
) -> None:
    """Register ``verifier`` under app[BROWSER_VERIFIERS_APP_KEY][bot_id][auth_method]."""
    if auth_method not in PAGE_AUTH_METHODS:
        raise ValueError(f"Unsupported browser authentication method: {auth_method}")
    verifiers = app.setdefault(BROWSER_VERIFIERS_APP_KEY, {})
    verifiers.setdefault(bot_id, {})[auth_method] = verifier


def get_browser_identity_verifier(
    app: Optional[MutableMapping[str, Any]],
    *,
    bot_id: str,
    auth_method: str,
) -> Optional[BrowserIdentityVerifier]:
    """Return the registered verifier, or None when app/bot/method has none."""
    if app is None:
        return None
    verifiers = app.get(BROWSER_VERIFIERS_APP_KEY)
    if not verifiers:
        return None
    bot_verifiers = verifiers.get(bot_id)
    if not bot_verifiers:
        return None
    return bot_verifiers.get(auth_method)


_TG_USERNAME_RE = re.compile(r"[A-Za-z0-9_]{5,32}")


def telegram_deep_link(bot_username: Optional[str]) -> Optional[str]:
    """Return ``https://t.me/<bot_username>`` for a valid username, else None."""
    if bot_username and _TG_USERNAME_RE.fullmatch(bot_username):
        return f"https://t.me/{bot_username}"
    return None


def _render_page(*, title: str, heading: str, body: str) -> str:
    """Render the shared self-contained browser result page shell."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      margin: 0;
      background: #f4f6f8;
      color: #1f2933;
    }}
    main {{
      max-width: 32rem;
      margin: 1rem;
      padding: 2rem;
      border-radius: 0.75rem;
      background: #ffffff;
      box-shadow: 0 0.25rem 1rem rgba(0, 0, 0, 0.1);
      text-align: center;
    }}
    a {{ color: #1677b8; font-weight: 600; }}
  </style>
</head>
<body>
  <main>
    <h1>{heading}</h1>
    {body}
  </main>
</body>
</html>
"""


def render_browser_success(bot_username: Optional[str], display_name: str) -> str:
    """HTML success page with a t.me deep link back to the chat."""
    safe_display_name = html_mod.escape(display_name)
    deep_link = telegram_deep_link(bot_username)
    if deep_link is None:
        return_link = "<p>You can now return to Telegram.</p>"
    else:
        return_link = f'<p><a href="{deep_link}">Return to Telegram</a></p>'
    body = f"<p>Welcome, {safe_display_name}. Authentication is complete.</p>{return_link}"
    return _render_page(title="Authentication Complete", heading="Authentication complete", body=body)


def render_browser_error(message: str) -> str:
    """HTML error page (no auth data echoed back)."""
    safe_message = html_mod.escape(message)
    body = f"<p>{safe_message}</p><p>Return to Telegram and send <code>/login</code> again.</p>"
    return _render_page(title="Authentication Error", heading="Authentication failed", body=body)
