"""
Unit tests for MSAgentSDKWrapper.

All tests mock the ``microsoft_agents.*`` SDK so the suite runs without the
optional dependency installed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web


@pytest.fixture
def mock_app():
    """Bare aiohttp application for route registration tests."""
    return web.Application()


@pytest.fixture
def mock_config():
    """Anonymous-auth config for wrapper tests."""
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

    return MSAgentSDKConfig(
        name="TestBot",
        chatbot_id="test_agent",
        anonymous_auth=True,
    )


@pytest.fixture
def mock_config_with_spaces():
    """Config with spaces in the name to verify safe_id normalisation."""
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

    return MSAgentSDKConfig(
        name="My Copilot Bot",
        chatbot_id="agent",
        anonymous_auth=True,
    )


def _make_wrapper(mock_bot, mock_config, mock_app):
    """Helper that patches CloudAdapter and returns a wrapper."""
    mock_adapter_cls = MagicMock()
    mock_adapter_instance = MagicMock()
    mock_adapter_cls.return_value = mock_adapter_instance

    with patch.dict(
        "sys.modules",
        {
            "microsoft_agents": MagicMock(),
            "microsoft_agents.hosting": MagicMock(),
            "microsoft_agents.hosting.aiohttp": MagicMock(
                CloudAdapter=mock_adapter_cls
            ),
            # Anonymous mode now builds an _AnonymousConnectionManager, which
            # imports AnonymousTokenProvider / AgentAuthConfiguration from core.
            "microsoft_agents.hosting.core": MagicMock(),
        },
    ):
        from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

        wrapper = MSAgentSDKWrapper(mock_bot, mock_config, mock_app)
    return wrapper, mock_adapter_instance


class TestMSAgentSDKWrapperRouteRegistration:
    def test_route_registered(self, mock_app, mock_config):
        """Wrapper registers the per-bot route on the aiohttp app."""
        mock_bot = AsyncMock()
        wrapper, _ = _make_wrapper(mock_bot, mock_config, mock_app)
        routes = [r.resource.canonical for r in mock_app.router.routes()]
        assert "/api/msagentsdk/testbot/messages" in routes

    def test_route_safe_id_with_spaces(self, mock_app, mock_config_with_spaces):
        """Spaces in the name are replaced with underscores in the route."""
        mock_bot = AsyncMock()
        wrapper, _ = _make_wrapper(mock_bot, mock_config_with_spaces, mock_app)
        routes = [r.resource.canonical for r in mock_app.router.routes()]
        assert "/api/msagentsdk/my_copilot_bot/messages" in routes

    def test_route_attribute_set(self, mock_app, mock_config):
        """Wrapper stores the route on self.route."""
        mock_bot = AsyncMock()
        wrapper, _ = _make_wrapper(mock_bot, mock_config, mock_app)
        assert wrapper.route == "/api/msagentsdk/testbot/messages"


class TestMSAgentSDKWrapperHandleRequest:
    @pytest.mark.asyncio
    async def test_handle_request_delegates_to_adapter(self, mock_app, mock_config):
        """handle_request() calls adapter.process(request, m365_agent)."""
        mock_bot = AsyncMock()
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = AsyncMock()
        mock_adapter_instance.process = AsyncMock(
            return_value=web.Response(text="ok")
        )
        mock_adapter_cls.return_value = mock_adapter_instance

        with patch.dict(
            "sys.modules",
            {
                "microsoft_agents": MagicMock(),
                "microsoft_agents.hosting": MagicMock(),
                "microsoft_agents.hosting.aiohttp": MagicMock(
                    CloudAdapter=mock_adapter_cls
                ),
                "microsoft_agents.hosting.core": MagicMock(),
            },
        ):
            from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

            wrapper = MSAgentSDKWrapper(mock_bot, mock_config, mock_app)
            # Anonymous request: no Authorization header, no configured client_id.
            wrapper._auth_config.CLIENT_ID = None
            fake_request = MagicMock()
            fake_request.headers.get.return_value = None
            result = await wrapper.handle_request(fake_request)

        mock_adapter_instance.process.assert_called_once_with(
            fake_request, wrapper.m365_agent
        )
        assert isinstance(result, web.Response)

    @pytest.mark.asyncio
    async def test_anonymous_ignores_bearer_token(self, mock_app, mock_config):
        """In anonymous mode a present Authorization header is NOT validated.

        Regression: Web Chat sends a bearer token even to anonymous bots; the
        wrapper must attach anonymous claims instead of failing audience checks.
        """
        mock_bot = AsyncMock()
        mock_adapter_cls = MagicMock()
        mock_adapter_instance = AsyncMock()
        mock_adapter_instance.process = AsyncMock(
            return_value=web.Response(text="ok")
        )
        mock_adapter_cls.return_value = mock_adapter_instance

        with patch.dict(
            "sys.modules",
            {
                "microsoft_agents": MagicMock(),
                "microsoft_agents.hosting": MagicMock(),
                "microsoft_agents.hosting.aiohttp": MagicMock(
                    CloudAdapter=mock_adapter_cls
                ),
                "microsoft_agents.hosting.core": MagicMock(),
            },
        ):
            from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

            wrapper = MSAgentSDKWrapper(mock_bot, mock_config, mock_app)
            fake_request = MagicMock()
            # A bearer token IS present, but anonymous mode must ignore it.
            fake_request.headers.get.return_value = "Bearer some.jwt.token"
            result = await wrapper.handle_request(fake_request)

        wrapper._token_validator.validate_token.assert_not_called()
        wrapper._token_validator.get_anonymous_claims.assert_called_once()
        mock_adapter_instance.process.assert_awaited_once_with(
            fake_request, wrapper.m365_agent
        )
        assert isinstance(result, web.Response)


class TestMSAgentSDKWrapperAzureAuth:
    """Outbound auth config built for Azure AD (non-anonymous) modes."""

    def _build(self, config):
        """Build a wrapper in non-anonymous mode, capturing AgentAuthConfiguration."""
        captured = {}

        def _agent_auth_configuration(**kwargs):
            captured.update(kwargs)
            return MagicMock(CLIENT_ID=kwargs.get("client_id"))

        core_mock = MagicMock(AgentAuthConfiguration=_agent_auth_configuration)

        with patch.dict(
            "sys.modules",
            {
                "microsoft_agents": MagicMock(),
                "microsoft_agents.hosting": MagicMock(),
                "microsoft_agents.hosting.aiohttp": MagicMock(
                    CloudAdapter=MagicMock()
                ),
                "microsoft_agents.hosting.core": core_mock,
                "microsoft_agents.authentication": MagicMock(),
                "microsoft_agents.authentication.msal": MagicMock(
                    MsalConnectionManager=MagicMock()
                ),
            },
        ):
            from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

            MSAgentSDKWrapper(AsyncMock(), config, web.Application())
        return captured

    def test_multitenant_uses_botframework_authority(self):
        """A multi-tenant app pins the botframework.com outbound authority."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig(
            name="MTBot",
            chatbot_id="agent",
            client_id="cid",
            client_secret="secret",
            tenant_id="tid",
            app_type="MultiTenant",
        )
        captured = self._build(cfg)
        # tenant_id kept (for inbound issuer validation), authority overridden.
        assert captured["tenant_id"] == "tid"
        assert captured["authority"] == (
            "https://login.microsoftonline.com/botframework.com"
        )

    def test_singletenant_keeps_tenant_authority(self):
        """A single-tenant app does not override the authority (derived from tenant)."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig(
            name="STBot",
            chatbot_id="agent",
            client_id="cid",
            client_secret="secret",
            tenant_id="tid",
            app_type="SingleTenant",
        )
        captured = self._build(cfg)
        assert captured["tenant_id"] == "tid"
        assert captured["authority"] is None

    def test_explicit_authority_wins(self):
        """An explicit authority override is honoured even for multi-tenant."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig(
            name="OverrideBot",
            chatbot_id="agent",
            client_id="cid",
            client_secret="secret",
            tenant_id="tid",
            app_type="MultiTenant",
            authority="https://login.microsoftonline.us/botframework.com",
        )
        captured = self._build(cfg)
        assert captured["authority"] == (
            "https://login.microsoftonline.us/botframework.com"
        )


class TestMSAgentSDKWrapperStop:
    @pytest.mark.asyncio
    async def test_stop_does_not_raise(self, mock_app, mock_config):
        """stop() completes without errors (graceful no-op)."""
        mock_bot = AsyncMock()
        wrapper, _ = _make_wrapper(mock_bot, mock_config, mock_app)
        await wrapper.stop()  # Should not raise


class TestMSAgentSDKWrapperAuthExclusion:
    def test_auth_middleware_exclusion(self, mock_app, mock_config):
        """Route is excluded from the auth middleware when auth is present."""
        mock_bot = AsyncMock()
        mock_auth = MagicMock()
        mock_auth.add_exclude_list = MagicMock()
        mock_app["auth"] = mock_auth

        _make_wrapper(mock_bot, mock_config, mock_app)
        mock_auth.add_exclude_list.assert_called_once_with(
            "/api/msagentsdk/testbot/messages"
        )

    def test_no_auth_middleware_no_error(self, mock_app, mock_config):
        """No error when auth middleware is not present on the app."""
        mock_bot = AsyncMock()
        # Don't add 'auth' to app — should not raise
        wrapper, _ = _make_wrapper(mock_bot, mock_config, mock_app)
        assert wrapper is not None
