"""Generic RFC 8628 device-authorization client engine (FEAT-774 M8)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import aiohttp
from pydantic import BaseModel

logger = logging.getLogger(__name__)

DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
WELL_KNOWN_AS_PATH = "/.well-known/oauth-authorization-server"
SLOW_DOWN_INCREMENT_S = 5
_PENDING = {"authorization_pending", "slow_down"}


class DeviceAuthorization(BaseModel):
    """RFC 8628 §3.2 device authorization response."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: Optional[str] = None
    expires_in: int
    interval: int = 5


class DeviceCodeError(RuntimeError):
    """Terminal device-code authorization outcome."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def make_pkce_pair() -> Tuple[str, str]:
    """Return ``(code_verifier, S256 code_challenge)``."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _response_json(response: Any) -> Dict[str, Any]:
    """Return a JSON object response or raise a value error."""
    body = await response.json()
    if not isinstance(body, dict):
        raise ValueError("response JSON must be an object")
    return body


async def discover_authorization_server(session: aiohttp.ClientSession, issuer: str) -> Dict[str, Any]:
    """GET authorization-server metadata for ``issuer``.

    Args:
        session: Open HTTP client session.
        issuer: Authorization-server issuer URL.

    Returns:
        The authorization-server metadata document.

    Raises:
        DeviceCodeError: The metadata endpoint cannot supply a JSON object.
    """
    url = issuer.rstrip("/") + WELL_KNOWN_AS_PATH
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise DeviceCodeError(
                    "discovery_failed", f"authorization server discovery failed at {url}: HTTP {response.status}"
                )
            return await _response_json(response)
    except DeviceCodeError:
        raise
    except (aiohttp.ClientError, TypeError, ValueError) as exc:
        raise DeviceCodeError("discovery_failed", f"authorization server discovery failed at {url}: {exc}") from exc


async def request_device_authorization(
    session: aiohttp.ClientSession,
    url: str,
    *,
    client_id: str,
    scopes: Sequence[str],
    code_challenge: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> DeviceAuthorization:
    """POST a device authorization request (RFC 8628 §3.1)."""
    data: Dict[str, str] = {"client_id": client_id}
    if scopes:
        data["scope"] = " ".join(scopes)
    if code_challenge:
        data.update(code_challenge=code_challenge, code_challenge_method="S256")
    if client_secret:
        data["client_secret"] = client_secret
    try:
        async with session.post(url, data=data) as response:
            body = await _response_json(response)
    except (aiohttp.ClientError, TypeError, ValueError) as exc:
        raise DeviceCodeError("http_error", f"device authorization request failed at {url}: {exc}") from exc

    error = body.get("error")
    if isinstance(error, str):
        raise DeviceCodeError(error, str(body.get("error_description", error)))
    if response.status != 200:
        raise DeviceCodeError(
            f"http_{response.status}", f"device authorization request failed at {url}: HTTP {response.status}"
        )
    try:
        return DeviceAuthorization.model_validate(body)
    except ValueError as exc:
        raise DeviceCodeError("invalid_response", f"device authorization request failed at {url}: {exc}") from exc


async def request_device_token(
    session: aiohttp.ClientSession,
    token_url: str,
    *,
    client_id: str,
    device_code: str,
    code_verifier: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Run one token poll and classify its RFC 8628 outcome."""
    data = {"grant_type": DEVICE_CODE_GRANT, "device_code": device_code, "client_id": client_id}
    if code_verifier:
        data["code_verifier"] = code_verifier
    if client_secret:
        data["client_secret"] = client_secret
    try:
        async with session.post(token_url, data=data) as response:
            body = await _response_json(response)
    except (aiohttp.ClientError, TypeError, ValueError) as exc:
        raise DeviceCodeError("http_error", f"device token request failed at {token_url}: {exc}") from exc

    error = body.get("error")
    if isinstance(error, str):
        if error in _PENDING:
            return error, body
        raise DeviceCodeError(error, str(body.get("error_description", error)))
    if response.status == 200 and body.get("access_token"):
        return "approved", body
    raise DeviceCodeError(
        f"http_{response.status}", f"device token request failed at {token_url}: HTTP {response.status}"
    )


async def poll_device_token(
    session: aiohttp.ClientSession,
    token_url: str,
    *,
    client_id: str,
    authorization: DeviceAuthorization,
    code_verifier: Optional[str] = None,
    timeout_s: Optional[int] = None,
    on_wait: Optional[Callable[[int], None]] = None,
    client_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Poll until approved, increasing the wait after ``slow_down``."""
    interval = max(1, authorization.interval)
    budget = authorization.expires_in if timeout_s is None else min(authorization.expires_in, timeout_s)
    deadline = time.monotonic() + budget
    while True:
        if time.monotonic() >= deadline:
            raise DeviceCodeError("timeout", "device authorization timed out")
        outcome, payload = await request_device_token(
            session,
            token_url,
            client_id=client_id,
            device_code=authorization.device_code,
            code_verifier=code_verifier,
            client_secret=client_secret,
        )
        if outcome == "approved":
            return payload
        if outcome == "slow_down":
            interval += SLOW_DOWN_INCREMENT_S
        if on_wait is not None:
            on_wait(interval)
        await asyncio.sleep(interval)
