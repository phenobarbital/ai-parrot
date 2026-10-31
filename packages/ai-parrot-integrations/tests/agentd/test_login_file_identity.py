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
from parrot.cli.login import LoginRecord, LoginStore
from parrot.integrations.agentd.config import ServiceIdentityConfig
from parrot.integrations.agentd.server import JsonRpcUnixServer

NAV_ID = "nav-user-42"


def _write_login(path: Path, mode: int = 0o600) -> None:
    record = LoginRecord(
        server_url="https://example.invalid",
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
    monkeypatch.setattr(LoginStore, "for_uid", classmethod(lambda cls, uid: cls(path)))

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
    cfg = ServiceIdentityConfig.from_env()
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
