"""
Unit tests for MSAgentSDKWrapper Authorization header handling.

Covers malformed Authorization header edge cases (S1 from code review).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web
from aiohttp.test_utils import make_mocked_request


def _make_sdk_modules():
    """Build a minimal sys.modules patch dict for the MS Agent SDK."""
    mock_agent_auth_config = MagicMock()
    mock_jwt_validator = MagicMock()

    def make_validator(auth_config):
        inst = MagicMock()
        inst.get_anonymous_claims = MagicMock(return_value=MagicMock())
        inst.validate_token = AsyncMock(return_value=MagicMock())
        return inst

    mock_jwt_validator.side_effect = make_validator

    mock_core = MagicMock()
    mock_core.AgentAuthConfiguration = mock_agent_auth_config
    mock_core.JwtTokenValidator = mock_jwt_validator
    mock_core.AnonymousTokenProvider = MagicMock(return_value=MagicMock())
    mock_core.ClaimsIdentity = MagicMock(return_value=MagicMock())

    mock_aiohttp_hosting = MagicMock()
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.process = AsyncMock(return_value=web.Response(status=200))
    mock_aiohttp_hosting.CloudAdapter = MagicMock(return_value=mock_adapter_instance)

    mock_activity = MagicMock()
    mock_activity.ActivityTypes.message = "message"
    mock_activity.ActivityTypes.conversation_update = "conversationUpdate"
    mock_activity.Activity = MagicMock(return_value=MagicMock())

    mock_patches = MagicMock()
    mock_patches.patch_mcs_connector_empty_response = MagicMock()

    return {
        "microsoft_agents": MagicMock(),
        "microsoft_agents.hosting": MagicMock(),
        "microsoft_agents.hosting.aiohttp": mock_aiohttp_hosting,
        "microsoft_agents.hosting.core": mock_core,
        "microsoft_agents.hosting.core.authorization": MagicMock(),
        "microsoft_agents.activity": mock_activity,
        "microsoft_agents.authentication": MagicMock(),
        "microsoft_agents.authentication.msal": MagicMock(),
    }


def _make_non_anonymous_wrapper(mock_bot, mock_app, api_key=None):
    """Create a non-anonymous MSAgentSDKWrapper for auth tests."""
    from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

    config = MSAgentSDKConfig(
        name="AuthBot",
        chatbot_id="auth_agent",
        anonymous_auth=False,
        client_id="app-id",
        client_secret="app-secret",  # noqa: S106
        tenant_id="tenant-id",
        api_key=api_key,
    )

    sdk_mods = _make_sdk_modules()

    patches_mod = MagicMock()
    patches_mod.patch_mcs_connector_empty_response = MagicMock()

    with patch.dict("sys.modules", {
        **sdk_mods,
        "parrot.integrations.msagentsdk._patches": patches_mod,
    }):
        from parrot.integrations.msagentsdk.wrapper import MSAgentSDKWrapper

        wrapper = MSAgentSDKWrapper(
            agent=mock_bot,
            config=config,
            app=mock_app,
        )

    return wrapper, sdk_mods


class TestMalformedAuthorizationHeader:
    """Malformed Authorization header must return 401, not crash with 500."""

    @pytest.fixture
    def mock_app(self):
        return web.Application()

    @pytest.fixture
    def mock_bot(self):
        bot = MagicMock()
        bot.ask = AsyncMock(return_value=MagicMock(content="reply"))
        return bot

    @pytest.mark.asyncio
    async def test_bearer_without_token_returns_401(self, mock_bot, mock_app):
        """'Authorization: Bearer' (no token) must return 401, not crash."""
        wrapper, sdk_mods = _make_non_anonymous_wrapper(mock_bot, mock_app)

        request = make_mocked_request(
            "POST",
            "/api/messages",
            headers={"Authorization": "Bearer"},
        )

        with patch.dict("sys.modules", {
            **sdk_mods,
            "parrot.integrations.msagentsdk._patches": MagicMock(),
        }):
            response = await wrapper.handle_request(request)

        assert response.status == 401, (
            f"Expected 401 for 'Bearer' without token, got {response.status}"
        )

    @pytest.mark.asyncio
    async def test_empty_authorization_returns_401(self, mock_bot, mock_app):
        """An empty Authorization header value must return 401, not crash."""
        wrapper, sdk_mods = _make_non_anonymous_wrapper(mock_bot, mock_app)

        request = make_mocked_request(
            "POST",
            "/api/messages",
            headers={"Authorization": ""},
        )

        with patch.dict("sys.modules", {
            **sdk_mods,
            "parrot.integrations.msagentsdk._patches": MagicMock(),
        }):
            response = await wrapper.handle_request(request)

        # Empty Authorization string: the header is present but has no scheme
        # or token. The wrapper should reject with 401 (no JWT, no API key).
        assert response.status == 401, (
            f"Expected 401 for empty Authorization, got {response.status}"
        )

    @pytest.mark.asyncio
    async def test_bearer_with_spaces_only_returns_401(self, mock_bot, mock_app):
        """'Authorization: Bearer   ' (only spaces) must return 401."""
        wrapper, sdk_mods = _make_non_anonymous_wrapper(mock_bot, mock_app)

        request = make_mocked_request(
            "POST",
            "/api/messages",
            headers={"Authorization": "Bearer   "},
        )

        with patch.dict("sys.modules", {
            **sdk_mods,
            "parrot.integrations.msagentsdk._patches": MagicMock(),
        }):
            response = await wrapper.handle_request(request)

        assert response.status == 401, (
            f"Expected 401 for 'Bearer   ' (only spaces), got {response.status}"
        )
