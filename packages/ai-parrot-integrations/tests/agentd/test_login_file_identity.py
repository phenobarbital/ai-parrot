"""agentd login-file principal (FEAT-774 M9, AC-11)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from parrot.auth.oauth2.models import WhoAmI
from parrot.auth.oauth2.remote_client import ServerConnectionsClient
from parrot.cli.login import LoginFileError, LoginRecord, LoginStore
from parrot.integrations.agentd.config import ServiceIdentityConfig
from parrot.integrations.agentd.server import JsonRpcUnixServer

NAV_ID = "nav-user-42"
TRUSTED_URL = "https://example.invalid"
_REAL_ME = ServerConnectionsClient.me


def _trusted_identity() -> ServiceIdentityConfig:
    return ServiceIdentityConfig(login_file_server_url=TRUSTED_URL)


def _write_login(path: Path, mode: int = 0o600, server_url: str = TRUSTED_URL) -> None:
    record = LoginRecord(
        server_url=server_url,
        access_token="tok",
        expires_at=time.time() + 3600,
        user_id=NAV_ID,
        cache_key="k",
        issued_at=time.time(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.model_dump(mode="json")))
    os.chmod(path, mode)


@pytest.fixture
def login_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "home" / ".parrot" / "login.json"
    monkeypatch.setattr("parrot.integrations.agentd.server._peer_login_file_exists", lambda uid: True)
    monkeypatch.setattr(
        LoginStore,
        "for_uid",
        classmethod(lambda cls, uid, read_only=False: cls(path, expected_uid=uid, read_only=read_only)),
    )

    async def fake_me(self) -> WhoAmI:
        return WhoAmI(user_id=NAV_ID, tenant_id="acme", roles=["r1"], scopes=["s1"])

    monkeypatch.setattr(ServerConnectionsClient, "me", fake_me)
    return path


def _fake_writer() -> MagicMock:
    # A real socketpair gives genuine SO_PEERCRED values (this process's uid).
    import socket

    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    writer = MagicMock()
    writer.get_extra_info.return_value = a
    writer._peer = b
    return writer


@pytest.fixture
async def server(tmp_path):
    srv = JsonRpcUnixServer(tmp_path / "agentd.sock", dispatch={})
    srv.service_identity = _trusted_identity()
    yield srv


async def test_agentd_login_file_principal(server, login_path):
    _write_login(login_path)
    ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "login_file"
    assert ctx.user_id == NAV_ID
    assert ctx.session.tenant_id == "acme"


async def test_agentd_login_file_rejected_falls_back(server, login_path, tmp_path):
    # 0644 -> rejected
    _write_login(login_path, mode=0o644)
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"

    # symlink -> rejected
    login_path.unlink()
    real = tmp_path / "real.json"
    _write_login(real)
    login_path.symlink_to(real)
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"

    # wrong owner -> rejected (expected_uid differs from the file owner)
    login_path.unlink()
    _write_login(login_path)
    real_fstat = os.fstat

    def other_owner(fd):
        st = real_fstat(fd)
        return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid + 1, *tuple(st)[5:]))

    import parrot.cli.login as login_mod

    login_mod.os.fstat = other_owner
    try:
        _ctx, source = await server._resolve_identity(_fake_writer())
    finally:
        login_mod.os.fstat = real_fstat
    assert source == "peercred"


async def test_agentd_login_server_failure_falls_back(server, login_path, monkeypatch):
    _write_login(login_path)

    async def boom(self):
        raise RuntimeError("down")

    monkeypatch.setattr(ServerConnectionsClient, "me", boom)
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"


async def test_agentd_login_lookup_disabled(server, login_path, monkeypatch):
    _write_login(login_path)
    monkeypatch.setenv("AGENTD_LOGIN_FILE_LOOKUP", "0")
    monkeypatch.setenv("AGENTD_LOGIN_FILE_SERVER_URL", TRUSTED_URL)
    cfg = ServiceIdentityConfig.from_env()
    assert cfg.login_file_server_url == TRUSTED_URL
    assert cfg.login_file_enabled is False
    assert cfg.login_file_lookup is False
    server.service_identity = cfg
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"
    monkeypatch.delenv("AGENTD_LOGIN_FILE_LOOKUP")
    assert ServiceIdentityConfig.from_env().login_file_lookup is True


async def test_e2e_agentd_login_file(tmp_path, login_path):
    _write_login(login_path)

    async def info(session, params):
        return {"user_id": session.permission_context.user_id, "identity_source": session.identity_source}

    srv = JsonRpcUnixServer(tmp_path / "e2e.sock", dispatch={"agent.info": info})
    srv.service_identity = _trusted_identity()
    await srv.start()
    try:
        reader, writer = await asyncio.open_unix_connection(path=str(srv.socket_path))
        try:
            await asyncio.sleep(0.1)
            session = next(iter(srv._sessions.values()))
            assert session.identity_source == "login_file"
            assert session.permission_context.user_id == NAV_ID
        finally:
            writer.close()
    finally:
        await srv.close()


# --- Review fixes: trusted-server pin + read-only agentd store ------------------------------


def test_login_file_disabled_without_trusted_server(monkeypatch):
    monkeypatch.delenv("AGENTD_LOGIN_FILE_LOOKUP", raising=False)
    monkeypatch.delenv("AGENTD_LOGIN_FILE_SERVER_URL", raising=False)
    cfg = ServiceIdentityConfig.from_env()
    assert cfg.login_file_lookup is True
    assert cfg.login_file_server_url is None
    assert cfg.login_file_enabled is False


async def test_no_trusted_server_keeps_peercred(server, login_path, monkeypatch):
    _write_login(login_path)
    server.service_identity = ServiceIdentityConfig()
    calls = []

    async def spy_me(self) -> WhoAmI:
        calls.append(1)
        return WhoAmI(user_id=NAV_ID, tenant_id="acme")

    monkeypatch.setattr(ServerConnectionsClient, "me", spy_me)
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"
    assert calls == []


async def test_login_file_naming_untrusted_server_is_ignored(server, login_path, monkeypatch):
    _write_login(login_path, server_url="https://attacker.example")
    calls = []

    async def spy_me(self) -> WhoAmI:
        calls.append(1)
        return WhoAmI(user_id="forged-admin", tenant_id="acme", roles=["admin"])

    monkeypatch.setattr(ServerConnectionsClient, "me", spy_me)
    ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"
    assert ctx.user_id != "forged-admin"
    assert calls == []


async def test_trusted_server_comparison_is_normalized(server, login_path):
    _write_login(login_path, server_url="HTTPS://Example.Invalid/")
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "login_file"


class _FakeResponse:
    def __init__(self, status: int, body):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self) -> bytes:
        return json.dumps(self._body).encode() if self._body is not None else b""

    async def json(self):
        return self._body


class _FakeSession:
    def __init__(self, status: int, body=None):
        self.status = status
        self.body = body
        self.urls: list[str] = []
        self.closed = False

    def request(self, method, url, headers=None, json=None):
        self.urls.append(url)
        return _FakeResponse(self.status, self.body)


async def test_pinned_server_url_overrides_login_record(login_path):
    _write_login(login_path, server_url="https://attacker.example")
    session = _FakeSession(200, {"user_id": NAV_ID, "tenant_id": "acme"})
    client = ServerConnectionsClient(LoginStore(login_path, read_only=True), session=session, server_url=TRUSTED_URL)
    who = await _REAL_ME(client)
    assert who.user_id == NAV_ID
    assert session.urls and all(url.startswith(TRUSTED_URL + "/") for url in session.urls)


async def test_read_only_store_never_refreshes_on_401(login_path, monkeypatch):
    from parrot.cli.login import LoginExpired

    _write_login(login_path)
    refreshed = []

    async def fake_refresh(record, session):
        refreshed.append(1)
        return record

    monkeypatch.setattr("parrot.auth.oauth2.remote_client.refresh_login", fake_refresh)
    session = _FakeSession(401)
    client = ServerConnectionsClient(LoginStore(login_path, read_only=True), session=session, server_url=TRUSTED_URL)
    before = sorted(p.name for p in login_path.parent.iterdir())
    with pytest.raises(LoginExpired):
        await _REAL_ME(client)
    assert refreshed == []
    assert sorted(p.name for p in login_path.parent.iterdir()) == before


async def test_agentd_401_falls_back_without_touching_peer_dir(server, login_path, monkeypatch):
    _write_login(login_path)
    refreshed = []

    async def fake_refresh(record, session):
        refreshed.append(1)
        return record

    async def unauthorized(self, session, record, method, path, request_json):
        return 401, None

    monkeypatch.setattr(ServerConnectionsClient, "me", _REAL_ME)
    monkeypatch.setattr(ServerConnectionsClient, "_send", unauthorized)
    monkeypatch.setattr("parrot.auth.oauth2.remote_client.refresh_login", fake_refresh)
    before = sorted(p.name for p in login_path.parent.iterdir())
    _ctx, source = await server._resolve_identity(_fake_writer())
    assert source == "peercred"
    assert refreshed == []
    assert sorted(p.name for p in login_path.parent.iterdir()) == before


def test_read_only_store_refuses_writes(login_path):
    _write_login(login_path)
    store = LoginStore(login_path, read_only=True)
    record = store.load_optional()
    with pytest.raises(LoginFileError):
        store.save(record)
    with pytest.raises(LoginFileError):
        store.delete()
    assert not store.lock_path.exists()


def test_lock_file_symlink_is_refused(login_path, tmp_path):
    _write_login(login_path)
    target = tmp_path / "victim.txt"
    target.write_text("untouched")
    store = LoginStore(login_path)
    store.lock_path.symlink_to(target)
    record = store.load_optional()
    with pytest.raises(LoginFileError):
        store.save(record)
    assert target.read_text() == "untouched"


def test_store_expected_uid_applies_to_every_load(login_path):
    _write_login(login_path)
    store = LoginStore(login_path, expected_uid=os.getuid() + 1)
    with pytest.raises(LoginFileError):
        store.load_optional()
