"""``BotManager._wire_agent_mount`` tests (FEAT-477 TASK-2610 post-review fix).

Code review of FEAT-477 found `BotManager.setup(agent_mount_config=...)`
had zero test coverage and no way to actually secure the mount it builds
(no `auth_template`/`pbac_resolver`/`audit_sink` parameters existed at
all). These tests cover the fix: the four `agent_mount_*` keyword
parameters on `setup()` reach `AgentMCPMount`'s constructor unchanged, and
`agent_mount_config=None` (the default) wires nothing at all (G11).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from aiohttp import web
from parrot.manager.manager import BotManager
from parrot.mcp.config import AgentMCPMountConfig, MCPServerConfig


def _manager() -> BotManager:
    """A `BotManager` with no heavy `__init__` side effects (pattern:
    test_reload_agent.py) — `_wire_agent_mount` only needs `self.app` and
    `self` (passed as the mount's `bot_manager`).
    """
    bm = BotManager.__new__(BotManager)
    bm.app = web.Application()
    bm.logger = MagicMock()
    return bm


class TestWireAgentMount:
    def test_none_config_wires_nothing(self, monkeypatch):
        """G11 — the default (`agent_mount_config=None`) must not construct
        an `AgentMCPMount` at all.
        """
        spy = MagicMock()
        monkeypatch.setattr("parrot.manager.manager.AgentMCPMount", spy)
        manager = _manager()

        manager._wire_agent_mount(None)

        spy.assert_not_called()

    def test_config_alone_wires_with_no_security_params(self, monkeypatch):
        """Passing only a config (no auth_template/pbac_resolver/audit_sink)
        still constructs the mount — with those three `None`, matching
        `AgentMCPMount`'s own fail-closed defaults (unauthenticated
        requests get rejected by principal resolution, and `pbac_resolver
        =None` denies every call — never a silent open passthrough).
        """
        mount_instance = MagicMock()
        spy = MagicMock(return_value=mount_instance)
        monkeypatch.setattr("parrot.manager.manager.AgentMCPMount", spy)
        manager = _manager()
        cfg = AgentMCPMountConfig(agents=["finance"], resource_server_url="https://h/x")

        manager._wire_agent_mount(cfg)

        spy.assert_called_once_with(manager, cfg, pbac_resolver=None, audit_sink=None, auth_template=None)
        mount_instance.setup.assert_called_once_with(manager.app)

    def test_all_security_params_reach_agent_mcp_mount(self, monkeypatch):
        """The fix under test: `auth_template`/`pbac_resolver`/`audit_sink`
        passed to `setup()`/`_wire_agent_mount` must reach `AgentMCPMount`'s
        constructor unchanged — this is what makes the mount actually
        authenticate and enforce PBAC instead of being permanently
        unreachable (AuthMethod.NONE) or permanently denying (no resolver).
        """
        mount_instance = MagicMock()
        spy = MagicMock(return_value=mount_instance)
        monkeypatch.setattr("parrot.manager.manager.AgentMCPMount", spy)
        manager = _manager()
        cfg = AgentMCPMountConfig(agents=["finance"], resource_server_url="https://h/x")
        auth_template = MCPServerConfig(name="tmpl")

        async def resolver(pctx, resource, required_permissions):
            return True

        def audit_sink(entry):
            return None

        manager._wire_agent_mount(cfg, auth_template=auth_template, pbac_resolver=resolver, audit_sink=audit_sink)

        spy.assert_called_once_with(
            manager,
            cfg,
            pbac_resolver=resolver,
            audit_sink=audit_sink,
            auth_template=auth_template,
        )
        mount_instance.setup.assert_called_once_with(manager.app)

    def test_setup_kwargs_reach_wire_agent_mount(self, monkeypatch):
        """`BotManager.setup()`'s own `agent_mount_*` keyword-only params
        must be threaded through to `_wire_agent_mount` unchanged. Spies on
        `_wire_agent_mount` but calls the **real** `setup()` — the actual
        method under test, not a re-implementation of it.
        """
        captured = {}
        real_wire = BotManager._wire_agent_mount

        def spying_wire(self, config, *, auth_template=None, pbac_resolver=None, audit_sink=None):
            captured.update(
                config=config,
                auth_template=auth_template,
                pbac_resolver=pbac_resolver,
                audit_sink=audit_sink,
            )
            return real_wire(
                self,
                config,
                auth_template=auth_template,
                pbac_resolver=pbac_resolver,
                audit_sink=audit_sink,
            )

        monkeypatch.setattr(BotManager, "_wire_agent_mount", spying_wire)
        monkeypatch.setattr("parrot.manager.manager.AgentMCPMount", MagicMock())

        manager = BotManager(enable_registry_bots=False, enable_crews=False)
        cfg = AgentMCPMountConfig(agents=["finance"], resource_server_url="https://h/x")
        auth_template = MCPServerConfig(name="tmpl")
        resolver = object()
        audit_sink = object()

        manager.setup(
            web.Application(),
            agent_mount_config=cfg,
            agent_mount_auth_template=auth_template,
            agent_mount_pbac_resolver=resolver,
            agent_mount_audit_sink=audit_sink,
        )

        assert captured == {
            "config": cfg,
            "auth_template": auth_template,
            "pbac_resolver": resolver,
            "audit_sink": audit_sink,
        }

    async def test_end_to_end_agent_mount_via_real_setup(self):
        """No mocks on `AgentMCPMount` itself: `BotManager.setup()` with a
        real `agent_mount_config` + `auth_template` produces a genuinely
        working, authenticated `/mcp/agents/{name}` route on the real app.
        """
        from aiohttp.test_utils import TestClient, TestServer
        from parrot.mcp.config import AuthMethod
        from parrot.mcp.oauth_server import APIKeyStore

        class _FakeToolManager:
            def list_tools(self):
                return []

            def get_tool(self, name):
                return None

        class _FinanceAgent:
            name = "finance"

            def __init__(self):
                self.tool_manager = _FakeToolManager()

        manager = BotManager(enable_registry_bots=False, enable_crews=False)
        manager._bots = {"finance": _FinanceAgent()}
        api_key_store = APIKeyStore()
        record = api_key_store.issue_key(user_id="dev-user")

        app = web.Application()
        manager.setup(
            app,
            agent_mount_config=AgentMCPMountConfig(
                agents=["finance"],
                resource_server_url="https://h/mcp/agents/finance",
                default_tenant_id="acme",
            ),
            agent_mount_auth_template=MCPServerConfig(auth_method=AuthMethod.API_KEY, api_key_store=api_key_store),
            agent_mount_pbac_resolver=lambda pctx, resource, required_permissions: True,
        )

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            no_auth = await client.post(
                "/mcp/agents/finance", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            )
            assert no_auth.status == 401

            authed = await client.post(
                "/mcp/agents/finance",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                headers={"X-API-Key": record.key},
            )
            assert authed.status == 200
        finally:
            await client.close()
