"""RFC 8628 engine state machine (FEAT-774 M8, AC-10)."""
import asyncio
import base64
import hashlib
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2 import device_code
from parrot.auth.oauth2.device_code import (
    DeviceAuthorization,
    DeviceCodeError,
    make_pkce_pair,
    poll_device_token,
    request_device_token,
)


def _authz(**kw) -> DeviceAuthorization:
    base = dict(device_code="dc", user_code="ABCD-EFGH", verification_uri="https://as/device", expires_in=600, interval=5)
    return DeviceAuthorization(**{**base, **kw})


async def test_device_code_engine_state_machine(monkeypatch):
    """Pending, slow-down, then approval respects the adjusted interval."""
    poll = AsyncMock(
        side_effect=[
            ("authorization_pending", {"error": "authorization_pending"}),
            ("slow_down", {"error": "slow_down"}),
            ("approved", {"access_token": "token"}),
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(device_code, "request_device_token", poll)
    monkeypatch.setattr(asyncio, "sleep", sleep)

    result = await poll_device_token(object(), "https://as/token", client_id="client", authorization=_authz())

    assert result == {"access_token": "token"}
    assert [call.args[0] for call in sleep.await_args_list] == [5, 10]


class _Response:
    """Minimal aiohttp response context manager for token-poll tests."""

    def __init__(self, status, payload) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def json(self):
        return self._payload


class _Session:
    """Minimal aiohttp session that returns a fixed response."""

    def __init__(self, response) -> None:
        self.response = response

    def post(self, *args, **kwargs):
        return self.response


@pytest.mark.parametrize("error", ["expired_token", "access_denied"])
async def test_terminal_errors_raise(error):
    """Terminal token-endpoint outcomes expose the RFC error code."""
    session = _Session(_Response(400, {"error": error}))

    with pytest.raises(DeviceCodeError, match=error) as raised:
        await request_device_token(session, "https://as/token", client_id="client", device_code="dc")

    assert raised.value.code == error


async def test_timeout_and_cancellation(monkeypatch):
    """Timeout is normalized, while cancellation reaches the caller unchanged."""
    with pytest.raises(DeviceCodeError) as raised:
        await poll_device_token(object(), "https://as/token", client_id="client", authorization=_authz(), timeout_s=0)
    assert raised.value.code == "timeout"

    waiting = asyncio.Event()
    release = asyncio.Event()

    async def pending(*args, **kwargs):
        return "authorization_pending", {"error": "authorization_pending"}

    async def sleep_forever(interval):
        waiting.set()
        await release.wait()

    monkeypatch.setattr(device_code, "request_device_token", pending)
    monkeypatch.setattr(asyncio, "sleep", sleep_forever)
    task = asyncio.create_task(poll_device_token(object(), "https://as/token", client_id="client", authorization=_authz()))
    await waiting.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


def test_pkce_pair_is_s256():
    """The PKCE challenge is the unpadded URL-safe SHA-256 digest."""
    verifier, challenge = make_pkce_pair()

    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    assert challenge == expected
