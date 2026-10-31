"""aiohttp client for /api/v1/connections* (FEAT-774 M4). CLI-side only; never imports server code."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import BaseModel

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2.models import NotConnected, PulledToken, WhoAmI
from parrot.cli.login import LoginExpired, LoginRecord, LoginStore, refresh_login

__all__ = ["ConnectAttempt", "NotConnected", "NotLoggedIn", "PulledToken", "ServerConnectionsClient", "WhoAmI"]
logger = logging.getLogger(__name__)
_BASE = "/api/v1/connections"


class NotLoggedIn(RuntimeError):
    """No login record; run `parrot login`."""


class ConnectAttempt(BaseModel):
    """CLI-side correlation of one connect (S10); never stored server-side."""

    provider: str
    state: str
    auth_url: str
    started_at: float
    expires_in: int = 600


class ServerConnectionsClient:
    """Call the remote connections API using the current CLI login bearer."""

    def __init__(self, store: LoginStore, *, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.store = store
        self._session = session
        self._owns_session = session is None
        self._refresh_lock = asyncio.Lock()
        self.logger = logger

    async def __aenter__(self) -> "ServerConnectionsClient":
        """Return this client for use in an async context manager."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Close resources owned by this client."""
        await self.close()

    async def close(self) -> None:
        """Close the lazily created session, leaving injected sessions open."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _record(self) -> LoginRecord:
        """Load the current login record without blocking the event loop."""
        record = await asyncio.to_thread(self.store.load_optional)
        if record is None:
            raise NotLoggedIn("not logged in — run `parrot login`")
        return record

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the injected session or lazily create the owned session."""
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def _send(
        self,
        session: aiohttp.ClientSession,
        record: LoginRecord,
        method: str,
        path: str,
        request_json: Optional[Dict[str, Any]],
    ) -> tuple[int, Any]:
        """Send one request and parse its JSON response without logging secrets."""
        url = f"{record.server_url.rstrip('/')}{path}"
        headers = {"Authorization": f"Bearer {record.access_token}"}
        async with session.request(method, url, headers=headers, json=request_json) as response:
            if response.status == 401:
                return response.status, None
            if not 200 <= response.status < 300 and response.status != 409:
                return response.status, None
            raw_body = await response.read()
            body = await response.json() if raw_body else None
            return response.status, body

    async def _request(self, method: str, path: str, *, json: Optional[Dict[str, Any]] = None) -> tuple[int, Any]:
        """Return ``(status, body)`` and refresh the login once on HTTP 401."""
        record = await self._record()
        session = await self._get_session()
        status, body = await self._send(session, record, method, path, json)
        if status != 401:
            return status, body

        async with self._refresh_lock:
            current_record = await self._record()
            if current_record.access_token == record.access_token:
                current_record = await refresh_login(current_record, session)
                await asyncio.to_thread(self.store.save, current_record)

        status, body = await self._send(session, current_record, method, path, json)
        if status == 401:
            raise LoginExpired("refreshed login was rejected; run `parrot login` again")
        return status, body

    @staticmethod
    def _require_status(method: str, path: str, status: int) -> None:
        """Raise a body-free error for a non-successful API response."""
        if not 200 <= status < 300:
            raise RuntimeError(f"{method} {path}: HTTP {status}")

    async def me(self) -> WhoAmI:
        """Return the Navigator principal represented by the CLI bearer."""
        path = f"{_BASE}/me"
        status, body = await self._request("GET", path)
        self._require_status("GET", path, status)
        return WhoAmI.model_validate(body)

    async def list(self) -> List[Dict[str, Any]]:
        """List the current principal's connection descriptors."""
        status, body = await self._request("GET", _BASE)
        self._require_status("GET", _BASE, status)
        return list(body)

    async def status(self, provider: str) -> Dict[str, Any]:
        """Return the connection descriptor for a provider."""
        path = f"{_BASE}/{provider}"
        status, body = await self._request("GET", path)
        self._require_status("GET", path, status)
        return dict(body)

    async def start_connect(
        self,
        provider: str,
        *,
        channel: str = "cli",
        scopes: Optional[List[str]] = None,
    ) -> ConnectAttempt:
        """Start a provider connection and retain the local start timestamp."""
        started_at = time.time()
        path = f"{_BASE}/{provider}/start"
        status, body = await self._request("POST", path, json={"channel": channel, "scopes": scopes})
        self._require_status("POST", path, status)
        return ConnectAttempt(
            provider=provider,
            state=body["state"],
            auth_url=body["auth_url"],
            started_at=started_at,
            expires_in=body.get("expires_in", 600),
        )

    async def complete(self, provider: str, *, code: str, state: str) -> Dict[str, Any]:
        """Complete a browser authorization callback pasted into the CLI."""
        path = f"{_BASE}/{provider}/complete"
        status, body = await self._request("POST", path, json={"code": code, "state": state})
        self._require_status("POST", path, status)
        return dict(body)

    async def pull_token(self, provider: str) -> PulledToken:
        """Pull a provider access token, mapping an absent connection to NotConnected."""
        path = f"{_BASE}/{provider}/token"
        status, body = await self._request("POST", path)
        if status == 409:
            raise NotConnected(AuthRequiredPayload.model_validate(body))
        self._require_status("POST", path, status)
        return PulledToken.model_validate(body)

    async def disconnect(self, provider: str) -> None:
        """Disconnect the provider for the current principal."""
        path = f"{_BASE}/{provider}"
        status, _ = await self._request("DELETE", path)
        self._require_status("DELETE", path, status)

    async def device_start(self, provider: str) -> Dict[str, Any]:
        """Start the provider's server-mediated device authorization flow."""
        path = f"{_BASE}/{provider}/device/start"
        status, body = await self._request("POST", path)
        self._require_status("POST", path, status)
        return dict(body)

    async def device_poll(self, provider: str, handle: str) -> Dict[str, Any]:
        """Poll one server-mediated device authorization attempt."""
        path = f"{_BASE}/{provider}/device/poll"
        status, body = await self._request("POST", path, json={"handle": handle})
        self._require_status("POST", path, status)
        return dict(body)
