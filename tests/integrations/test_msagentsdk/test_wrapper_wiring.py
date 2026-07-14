"""
Unit tests for MSAgentSDKWrapper OAuth resolver wiring.

Covers FEAT-261 Module 8 (Wrapper Auth Wiring).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWrapperAuthWiring:
    """Tests for BFTokenServiceResolver wiring in MSAgentSDKWrapper."""

    def test_wrapper_no_resolver_when_empty(self):
        """Wrapper skips resolver when oauth_connections is empty."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        cfg = MSAgentSDKConfig(
            name="Bot",
            chatbot_id="bot",
            anonymous_auth=True,
        )
        assert cfg.oauth_connections == {}

        # When wrapper creates ParrotM365Agent with empty connections,
        # resolver and audit_ledger should be None
        mock_bot = AsyncMock()

        import sys
        from unittest.mock import patch, MagicMock as MM

        # Mock the SDK so wrapper.__init__ can proceed without SDK installed
        mock_activity = MM()
        mock_hosting_core = MM()
        mock_hosting_core.AgentAuthConfiguration = MM(return_value=MM())
        mock_hosting_core.AnonymousTokenProvider = MM(return_value=MM())
        mock_hosting_core.JwtTokenValidator = MM(return_value=MM(
            get_anonymous_claims=MM(return_value=MM())
        ))
        mock_adapter = MM()
        mock_aiohttp_adapter = MM(return_value=mock_adapter)
        mock_hosting_aiohttp = MM()
        mock_hosting_aiohttp.CloudAdapter = mock_aiohttp_adapter

        with patch.dict(sys.modules, {
            "microsoft_agents.activity": mock_activity,
            "microsoft_agents.hosting.core": mock_hosting_core,
            "microsoft_agents.hosting.aiohttp": mock_hosting_aiohttp,
        }):
            from parrot.integrations.msagentsdk import wrapper as wrapper_mod
            import importlib
            # An earlier test's patch.dict(sys.modules) can leave the package
            # attribute ``parrot.integrations.msagentsdk.wrapper`` pointing at a
            # module object that is no longer registered in ``sys.modules``.
            # ``importlib.reload`` rejects that desync ("module ... not in
            # sys.modules"), so re-register the object before reloading.
            sys.modules[wrapper_mod.__name__] = wrapper_mod
            importlib.reload(wrapper_mod)
            from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

            mock_app = MM()
            mock_app.router = MM()
            mock_app.router.add_post = MM()
            mock_app.get = MM(return_value=None)

            # Mock the _patches module to avoid side effects
            with patch("parrot.integrations.msagentsdk.wrapper._AnonymousConnectionManager") as mock_cm:
                mock_cm.return_value = MM()
                w = MSAgentSDKWrapper(agent=mock_bot, config=cfg, app=mock_app)

        assert w.m365_agent._resolver is None
        assert w.m365_agent._audit_ledger is None

    def test_agent_resolver_is_none_without_oauth(self):
        """ParrotM365Agent._resolver is None when no resolver passed."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent

        mock_bot = AsyncMock()
        agent = ParrotM365Agent(parrot_agent=mock_bot)
        assert agent._resolver is None
        assert agent._audit_ledger is None

    def test_agent_resolver_wired_when_provided(self):
        """ParrotM365Agent stores resolver and audit_ledger when passed."""
        from parrot.integrations.msagentsdk.agent import ParrotM365Agent
        from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver
        from parrot.security.audit_ledger import AuditLedger

        mock_bot = AsyncMock()
        ledger = AuditLedger()
        resolver = BFTokenServiceResolver(
            oauth_connections={"o365": "graph_sso"},
            obo_scopes={},
            audit_ledger=ledger,
        )
        agent = ParrotM365Agent(
            parrot_agent=mock_bot,
            resolver=resolver,
            audit_ledger=ledger,
        )
        assert agent._resolver is resolver
        assert agent._audit_ledger is ledger
