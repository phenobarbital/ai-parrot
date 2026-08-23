"""Unit tests for agentd caller identity (TASK-2286 — FEAT-434 Claude Agent
Tool Bridge).

Tests: `SO_PEERCRED` resolves the OS user of a real UDS peer, unresolvable
credentials / non-UDS transports fall back to the configured service
identity, `ServiceIdentityConfig` env provisioning + defaults, the service
identity's `window_seconds` staying pinned to `0`, and that
`PermissionContext.user_id` is never the literal `"anonymous"`.
"""

from __future__ import annotations

import asyncio
import os
import pwd
from unittest.mock import MagicMock, patch

import pytest
from parrot.auth.confirmation import ConfirmationConfig
from parrot.auth.permission import PermissionContext
from parrot.integrations.agentd.config import ServiceIdentityConfig
from parrot.integrations.agentd.server import JsonRpcUnixServer
from pydantic import ValidationError


async def _ping_handler(session, params):
    return {"pong": True}


@pytest.fixture
async def server(tmp_path):
    socket_path = tmp_path / "agentd.sock"
    srv = JsonRpcUnixServer(socket_path, dispatch={"ping": _ping_handler})
    await srv.start()
    yield srv
    await srv.close()


# ── SO_PEERCRED resolution (real UDS connections) ───────────────────────────


class TestPeerCredentials:
    async def test_peercred_resolves_os_user(self, server):
        _reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path)
        )
        try:
            # Give the accept-loop callback a tick to run.
            await asyncio.sleep(0.05)
            assert len(server._sessions) == 1
            session = next(iter(server._sessions.values()))
            assert session.identity_source == "peercred"
            expected_user = pwd.getpwuid(os.getuid()).pw_name
            assert session.permission_context.user_id == expected_user
        finally:
            writer.close()

    async def test_unresolvable_uid_falls_back_to_service_identity(self, server):
        fake_writer = MagicMock()
        fake_socket = MagicMock()
        fake_socket.getsockopt.return_value = b"\x00" * 12  # decodes to pid=uid=gid=0
        fake_writer.get_extra_info.return_value = fake_socket

        with patch("parrot.integrations.agentd.server.pwd.getpwuid", side_effect=KeyError):
            ctx, source = await server._resolve_identity(fake_writer)

        assert source == "service_identity"
        assert ctx.user_id == server.service_identity.user_id

    async def test_non_uds_transport_falls_back(self, server):
        fake_writer = MagicMock()
        fake_writer.get_extra_info.return_value = None  # no socket available

        ctx, source = await server._resolve_identity(fake_writer)

        assert source == "service_identity"
        assert ctx.user_id == server.service_identity.user_id


# ── ServiceIdentityConfig ────────────────────────────────────────────────────


class TestServiceIdentity:
    def test_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("AGENTD_SERVICE_IDENTITY_DISPLAY_NAME", "custom agent")
        monkeypatch.setenv("AGENTD_SERVICE_IDENTITY_USER_ID", "svc-42")
        monkeypatch.setenv("AGENTD_SERVICE_IDENTITY_TENANT_ID", "acme")
        monkeypatch.setenv("AGENTD_SERVICE_IDENTITY_ROLES", "tool.execute, ops")

        cfg = ServiceIdentityConfig.from_env()

        assert cfg.display_name == "custom agent"
        assert cfg.user_id == "svc-42"
        assert cfg.tenant_id == "acme"
        assert cfg.roles == frozenset({"tool.execute", "ops"})

    def test_defaults_when_env_unset(self, monkeypatch):
        for var in (
            "AGENTD_SERVICE_IDENTITY_DISPLAY_NAME",
            "AGENTD_SERVICE_IDENTITY_USER_ID",
            "AGENTD_SERVICE_IDENTITY_TENANT_ID",
            "AGENTD_SERVICE_IDENTITY_ROLES",
        ):
            monkeypatch.delenv(var, raising=False)

        cfg = ServiceIdentityConfig.from_env()

        assert cfg.display_name == "parrot agent server"
        assert cfg.user_id == "1001"
        assert cfg.tenant_id == "default"
        assert cfg.roles == frozenset()

    def test_window_seconds_pinned_to_zero(self):
        assert ServiceIdentityConfig().window_seconds == 0

    def test_window_seconds_zero_even_when_deployment_raises_it(self):
        # A deployment-wide ConfirmationConfig default has no bearing on the
        # service identity's own (fixed) window — the two are decoupled by
        # construction.
        deployment_config = ConfirmationConfig(window_seconds=999)
        assert deployment_config.window_seconds == 999
        assert ServiceIdentityConfig().window_seconds == 0

    def test_window_seconds_not_settable_via_constructor(self):
        with pytest.raises(ValidationError):
            ServiceIdentityConfig(window_seconds=999)

    def test_to_permission_context_carries_window_seconds(self):
        ctx = ServiceIdentityConfig().to_permission_context()
        assert ctx.extra["window_seconds"] == 0


# ── PermissionContext propagation ────────────────────────────────────────────


class TestPermissionContextPropagation:
    async def test_permission_context_reaches_session(self, server):
        _reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path)
        )
        try:
            await asyncio.sleep(0.05)
            session = next(iter(server._sessions.values()))
            assert isinstance(session.permission_context, PermissionContext)
        finally:
            writer.close()

    async def test_owner_is_never_anonymous(self, server):
        _reader, writer = await asyncio.open_unix_connection(
            path=str(server.socket_path)
        )
        try:
            await asyncio.sleep(0.05)
            session = next(iter(server._sessions.values()))
            assert session.permission_context.user_id != "anonymous"
        finally:
            writer.close()

        # Service-identity fallback path must also never be "anonymous".
        fake_writer = MagicMock()
        fake_writer.get_extra_info.return_value = None
        ctx, _source = await server._resolve_identity(fake_writer)
        assert ctx.user_id != "anonymous"
