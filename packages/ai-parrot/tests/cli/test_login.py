"""parrot login / logout and LoginStore (FEAT-774 M1)."""

import asyncio
import os
import time
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest
from click.testing import CliRunner

from parrot.auth.oauth2 import device_code
from parrot.cli import cli
from parrot.cli import login as login_module
from parrot.cli.login import LoginExpired, LoginFileError, LoginRecord, LoginStore, login, logout, refresh_login


class _FakeResponse:
    """Minimal aiohttp response context manager for the in-memory fake AS."""

    def __init__(self, status: int, payload: Optional[Dict[str, Any]] = None) -> None:
        self.status = status
        self.payload = payload or {}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def json(self) -> Dict[str, Any]:
        """Return the configured JSON body."""
        return self.payload

    async def read(self) -> bytes:
        """Consume the configured body."""
        return b""


class _FakeAuthorizationServer:
    """In-memory authorization server exercised through the aiohttp session API."""

    def __init__(self) -> None:
        self.base_url = "https://auth.example.test"
        self.include_device_endpoint = True
        self.reject_client = False
        self.polls = 0
        self.refreshes = 0
        self.revocations = 0
        self.fail_revocation = False

    def session_factory(self, **_kwargs) -> "_FakeSession":
        """Return a new session bound to this fake server."""
        return _FakeSession(self)

    def get(self, url: str, headers: Optional[Dict[str, str]] = None) -> _FakeResponse:
        """Handle discovery and userinfo requests."""
        if url.endswith("/.well-known/oauth-authorization-server"):
            metadata = {
                "token_endpoint": f"{self.base_url}/token",
                "userinfo_endpoint": f"{self.base_url}/userinfo",
                "revocation_endpoint": f"{self.base_url}/revoke",
            }
            if self.include_device_endpoint:
                metadata["device_authorization_endpoint"] = f"{self.base_url}/device"
            return _FakeResponse(200, metadata)
        if url == f"{self.base_url}/userinfo":
            assert headers == {"Authorization": "Bearer access-secret"}
            return _FakeResponse(200, {"sub": "1042", "email": "jlara@example.com"})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, data: Dict[str, str]) -> _FakeResponse:
        """Handle device, token, refresh, and revocation requests."""
        if url == f"{self.base_url}/device":
            assert data["client_id"] == "parrot-cli"
            assert data["scope"] == "openid profile email"
            assert data["code_challenge"]
            assert data["code_challenge_method"] == "S256"
            if self.reject_client:
                return _FakeResponse(400, {"error": "invalid_client"})
            return _FakeResponse(
                200,
                {
                    "device_code": "device-secret",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": f"{self.base_url}/verify",
                    "expires_in": 120,
                    "interval": 1,
                },
            )
        if url == f"{self.base_url}/token" and data["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code":
            assert data["client_id"] == "parrot-cli"
            assert data["device_code"] == "device-secret"
            assert data["code_verifier"]
            self.polls += 1
            if self.polls <= 2:
                return _FakeResponse(400, {"error": "authorization_pending"})
            if self.polls == 3:
                return _FakeResponse(400, {"error": "slow_down"})
            return _FakeResponse(
                200,
                {
                    "access_token": "access-secret",
                    "refresh_token": "refresh-secret",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "scope": "openid profile email",
                },
            )
        if url == f"{self.base_url}/token" and data["grant_type"] == "refresh_token":
            assert data == {"grant_type": "refresh_token", "refresh_token": "rt", "client_id": "parrot-cli"}
            self.refreshes += 1
            if self.refreshes == 1:
                return _FakeResponse(
                    200, {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 7200}
                )
            return _FakeResponse(400, {"error": "invalid_grant"})
        if url == f"{self.base_url}/revoke":
            assert data == {"token": "rt", "client_id": "parrot-cli"}
            self.revocations += 1
            return _FakeResponse(500 if self.fail_revocation else 200)
        raise AssertionError(f"unexpected POST {url}")


class _FakeSession:
    """Minimal aiohttp ClientSession bound to an in-memory fake AS."""

    def __init__(self, server: _FakeAuthorizationServer) -> None:
        self.server = server

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    def get(self, url: str, headers: Optional[Dict[str, str]] = None) -> _FakeResponse:
        """Dispatch a GET to the fake server."""
        return self.server.get(url, headers)

    def post(self, url: str, data: Dict[str, str]) -> _FakeResponse:
        """Dispatch a POST to the fake server."""
        return self.server.post(url, data)


def _poll_without_wait(sleep):
    """Wrap the real polling engine with a no-delay asyncio facade."""

    async def poll(*args, **kwargs):
        original_asyncio = device_code.asyncio
        device_code.asyncio = SimpleNamespace(sleep=sleep)
        try:
            return await device_code.poll_device_token(*args, **kwargs)
        finally:
            device_code.asyncio = original_asyncio

    return poll


@pytest.fixture
def login_record() -> LoginRecord:
    """Return a complete login record with non-expired tokens."""
    return LoginRecord(
        server_url="http://parrot.test",
        access_token="at",
        refresh_token="rt",
        expires_at=time.time() + 3600,
        user_id="1042",
        email="jlara@example.com",
        tenant_id="troc",
        roles=["agents:use"],
        cache_key="k" * 43,
        issued_at=time.time(),
    )


def test_login_store_roundtrip_0600_and_lock(tmp_path, login_record):
    """LoginStore writes 0600 and rejects symlinks, loose modes, and wrong owners."""
    store = LoginStore(tmp_path / "nested" / "login.json")
    assert store.load_optional() is None

    store.save(login_record)

    assert store.path.stat().st_mode & 0o777 == 0o600
    assert store.lock_path.exists()
    assert store.lock_path.stat().st_mode & 0o777 == 0o600
    assert store.load_optional(expected_uid=os.getuid()) == login_record

    symlink_store = LoginStore(tmp_path / "linked-login.json")
    symlink_store.path.symlink_to(store.path)
    with pytest.raises(LoginFileError, match="opened safely"):
        symlink_store.load_optional()

    store.path.chmod(0o644)
    with pytest.raises(LoginFileError, match="group or other"):
        store.load_optional()
    store.path.chmod(0o600)

    with pytest.raises(LoginFileError, match="owned by uid"):
        store.load_optional(expected_uid=os.getuid() + 1)


def test_login_device_grant_happy_path(monkeypatch, tmp_path):
    """The login command completes PKCE device polling and saves the Navigator identity."""
    server = _FakeAuthorizationServer()

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(login_module.aiohttp, "ClientSession", server.session_factory)
    monkeypatch.setattr(login_module, "poll_device_token", _poll_without_wait(no_wait))
    result = CliRunner().invoke(
        login,
        ["--server", server.base_url, "--no-browser"],
        env={"PARROT_LOGIN_FILE": str(tmp_path / "login.json")},
    )

    assert result.exit_code == 0, result.output
    assert server.polls == 4
    assert "ABCD-EFGH" in result.output
    saved = LoginStore(tmp_path / "login.json").load_optional()
    assert saved is not None
    assert saved.user_id == "1042"
    assert saved.email == "jlara@example.com"
    assert saved.cache_key != "k" * 43
    assert saved.roles == []
    assert saved.tenant_id is None


def test_login_fails_loudly_without_device_endpoint(monkeypatch, tmp_path):
    """Missing device support and unregistered clients fail with command status 2."""
    server = _FakeAuthorizationServer()
    monkeypatch.setattr(login_module.aiohttp, "ClientSession", server.session_factory)
    server.include_device_endpoint = False
    missing_result = CliRunner().invoke(
        login,
        ["--server", server.base_url, "--no-browser"],
        env={"PARROT_LOGIN_FILE": str(tmp_path / "login.json")},
    )
    assert missing_result.exit_code == 2
    assert "device_authorization_endpoint" in missing_result.output

    server.include_device_endpoint = True
    server.reject_client = True
    client_result = CliRunner().invoke(
        login,
        ["--server", server.base_url, "--no-browser"],
        env={"PARROT_LOGIN_FILE": str(tmp_path / "login.json")},
    )
    assert client_result.exit_code == 2
    assert "parrot-cli public client" in client_result.output
    assert not (tmp_path / "login.json").exists()


async def test_refresh_login_rotation_and_invalid_grant(login_record):
    """Refresh accepts token rotation and maps invalid_grant to LoginExpired."""
    server = _FakeAuthorizationServer()
    record = login_record.model_copy(update={"server_url": server.base_url})
    session = _FakeSession(server)
    refreshed = await refresh_login(record, session)
    assert refreshed.access_token == "new-at"
    assert refreshed.refresh_token == "new-rt"
    assert refreshed.expires_at > time.time() + 7100
    with pytest.raises(LoginExpired, match="run `parrot login` again"):
        await refresh_login(record, session)


def test_logout_revokes_and_wipes(monkeypatch, tmp_path, login_record):
    """Logout attempts revocation and always removes the login and cache files."""
    server = _FakeAuthorizationServer()
    monkeypatch.setattr(login_module.aiohttp, "ClientSession", server.session_factory)

    def run() -> object:
        store = LoginStore(tmp_path / "login.json")
        store.save(login_record.model_copy(update={"server_url": server.base_url}))
        store.cache_path.write_text("encrypted-cache", encoding="utf-8")
        result = CliRunner().invoke(logout, env={"PARROT_LOGIN_FILE": str(store.path)})
        assert not store.path.exists()
        assert not store.cache_path.exists()
        return result

    first_result = run()
    assert first_result.exit_code == 0, first_result.output
    assert server.revocations == 1

    server.fail_revocation = True
    second_result = run()
    assert second_result.exit_code == 0, second_result.output
    assert server.revocations == 2


def test_cli_help_lists_connection_commands():
    """The top-level help exposes all six FEAT-774 lazy commands."""
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0, result.output
    for command in ("login", "logout", "whoami", "connect", "connections", "disconnect"):
        assert command in result.output
