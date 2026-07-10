"""
Integration tests for IntegrationBotManager._start_msagent_bot() (TASK-1710).

``MSAgentSDKWrapper`` requires the optional ``microsoft-agents-*`` SDK, so
its import is mocked via ``sys.modules`` (same pattern as
``tests/integrations/test_msagentsdk/test_manager_registration.py``), while
``A2AServer``/``A2ASecurityMiddleware`` (core/``ai-parrot-server``) are
exercised directly since they are cheap and already installed in this repo.
"""
import builtins

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web

from parrot.integrations.manager import IntegrationBotManager
from parrot.integrations.msagentsdk.models import MSAgentIntegrationConfig


class _DummyAgent:
    def __init__(self, name: str = "MSBot"):
        self.name = name
        self.description = "A test agent"
        self.role = None
        self.goal = None
        self.tools = []


@pytest.fixture
def manager_with_app():
    app = web.Application()
    bot_manager = MagicMock()
    bot_manager.get_app.return_value = app
    manager = IntegrationBotManager(bot_manager)
    return manager, app


@pytest.fixture
def mock_wrapper():
    mock_wrapper_cls = MagicMock()
    mock_wrapper_instance = MagicMock()
    mock_wrapper_cls.return_value = mock_wrapper_instance
    return mock_wrapper_cls, mock_wrapper_instance


class TestMSAgentBotBasic:
    @pytest.mark.asyncio
    async def test_start_msagent_bot_creates_wrapper(self, manager_with_app, mock_wrapper):
        manager, app = manager_with_app
        mock_wrapper_cls, mock_wrapper_instance = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(
            name="MSBot", chatbot_id="agent", anonymous_auth=True
        )
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        assert "MSBot" in manager.msagent_bots
        assert manager.msagent_bots["MSBot"] is mock_wrapper_instance

    @pytest.mark.asyncio
    async def test_wrapper_receives_converted_sdk_config(self, manager_with_app, mock_wrapper):
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(
            name="MSBot",
            chatbot_id="agent",
            microsoft_app_id="app-id",
            microsoft_app_password="secret",
        )
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        _, kwargs = mock_wrapper_cls.call_args
        sdk_config = kwargs["config"]
        assert sdk_config.client_id == "app-id"
        assert sdk_config.client_secret == "secret"

    @pytest.mark.asyncio
    async def test_aborts_when_agent_not_found(self, manager_with_app):
        manager, app = manager_with_app
        manager._get_agent = AsyncMock(return_value=None)

        cfg = MSAgentIntegrationConfig(name="Missing", chatbot_id="missing_agent")
        await manager._start_msagent_bot("Missing", cfg)

        assert "Missing" not in manager.msagent_bots


class TestMSAgentBotCredentialBroker:
    @pytest.mark.asyncio
    async def test_broker_wired_when_enabled(self, manager_with_app, mock_wrapper):
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(
            name="MSBot",
            chatbot_id="agent",
            enable_credential_broker=True,
            credentials=[{"provider": "fireflies", "auth": "static_key", "options": {}}],
        )
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        _, kwargs = mock_wrapper_cls.call_args
        assert kwargs["broker"] is not None

    @pytest.mark.asyncio
    async def test_no_broker_when_disabled(self, manager_with_app, mock_wrapper):
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(name="MSBot", chatbot_id="agent")
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        _, kwargs = mock_wrapper_cls.call_args
        assert kwargs["broker"] is None

    @pytest.mark.asyncio
    async def test_invalid_credential_entry_skipped_not_fatal(
        self, manager_with_app, mock_wrapper
    ):
        """A malformed credential dict is skipped, not fatal — the broker is
        still built from the remaining valid entries (strict=False contract).
        """
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(
            name="MSBot",
            chatbot_id="agent",
            enable_credential_broker=True,
            credentials=[
                {"provider": "broken"},  # missing required 'auth' → skipped
                {"provider": "fireflies", "auth": "static_key", "options": {}},
            ],
        )
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        # Bot still started and a broker was built despite the bad entry.
        assert "MSBot" in manager.msagent_bots
        _, kwargs = mock_wrapper_cls.call_args
        assert kwargs["broker"] is not None


class TestMSAgentBotA2ACompanion:
    @pytest.mark.asyncio
    async def test_companion_a2a_started_and_registered(self, manager_with_app, mock_wrapper):
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(name="MSBot", chatbot_id="agent", tags=["companion"])
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        assert "MSBot" in manager.a2a_bots
        assert "MSBot" in app["a2a_discovery_registry"]

    @pytest.mark.asyncio
    async def test_companion_security_wired_when_jwt_secret_set(
        self, manager_with_app, mock_wrapper
    ):
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(
            name="MSBot", chatbot_id="agent", jwt_secret="s3cret"
        )
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        assert len(app.middlewares) == 1

    @pytest.mark.asyncio
    async def test_companion_security_wired_when_only_api_key_set(
        self, manager_with_app, mock_wrapper
    ):
        """api_key alone must still secure the companion A2A surface.

        Regression: gating companion security on jwt_secret only left an
        api_key-only companion surface unauthenticated.
        """
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        cfg = MSAgentIntegrationConfig(
            name="MSBot", chatbot_id="agent", api_key="sekret-key"
        )
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        assert len(app.middlewares) == 1

    @pytest.mark.asyncio
    async def test_companion_skipped_gracefully_without_ai_parrot_server(
        self, manager_with_app, mock_wrapper, monkeypatch
    ):
        manager, app = manager_with_app
        mock_wrapper_cls, mock_wrapper_instance = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "parrot.a2a.server":
                raise ImportError("simulated missing ai-parrot-server")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        cfg = MSAgentIntegrationConfig(name="MSBot", chatbot_id="agent")
        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot", cfg)

        # The MS Agent SDK wrapper still starts even though the companion
        # A2A surface could not be mounted.
        assert manager.msagent_bots["MSBot"] is mock_wrapper_instance
        assert "MSBot" not in manager.a2a_bots


class TestMSAgentBotO365:
    @pytest.mark.asyncio
    async def test_o365_wired_under_frozen_on_startup(self, manager_with_app, mock_wrapper):
        """Reproduces the production timing: _start_msagent_bot() runs from
        inside the shared app's own on_startup dispatch, where
        app.on_startup is already frozen — O365OAuthManager.setup()'s
        app.on_startup.append() would raise if called directly.
        """
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        class _FakeRedis:
            async def ping(self):
                return True

        app["redis"] = _FakeRedis()

        cfg = MSAgentIntegrationConfig(
            name="MSBot",
            chatbot_id="agent",
            o365_client_id="cid",
            o365_client_secret="csecret",
            redirect_uri="http://localhost/callback",
        )

        result = {}

        async def on_startup_handler(app):
            with patch.dict(
                "sys.modules",
                {
                    "parrot.integrations.msagentsdk.wrapper": MagicMock(
                        MSAgentSDKWrapper=mock_wrapper_cls
                    )
                },
            ):
                try:
                    await manager._start_msagent_bot("MSBot", cfg)
                except Exception as exc:  # noqa: BLE001
                    result["error"] = exc

        app.on_startup.append(on_startup_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            assert "error" not in result
            assert "oauth2_manager_o365" in app
        finally:
            await runner.cleanup()

    @pytest.mark.asyncio
    async def test_second_o365_bot_reuses_manager_without_clobbering(
        self, manager_with_app, mock_wrapper
    ):
        """A second MSAgent bot must reuse the shared O365 manager rather than
        registering its own — which would clobber the first bot's app slot and
        duplicate the OAuth callback route.
        """
        manager, app = manager_with_app
        mock_wrapper_cls, _ = mock_wrapper
        manager._get_agent = AsyncMock(return_value=_DummyAgent())

        def make_cfg(name):
            return MSAgentIntegrationConfig(
                name=name,
                chatbot_id="agent",
                o365_client_id="cid",
                o365_client_secret="csecret",
                redirect_uri="http://localhost/callback",
            )

        with patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagent_bot("MSBot1", make_cfg("MSBot1"))
            first_manager = app["oauth2_manager_o365"]
            await manager._start_msagent_bot("MSBot2", make_cfg("MSBot2"))

        # Same manager instance reused; slot never clobbered.
        assert app["oauth2_manager_o365"] is first_manager
        # Both bots started; single OAuth callback route (not duplicated).
        assert {"MSBot1", "MSBot2"} <= set(manager.msagent_bots)
        callback_resources = {
            route.resource
            for route in app.router.routes()
            if route.resource is not None
            and route.resource.canonical == "/api/auth/oauth2/o365/callback"
        }
        assert len(callback_resources) == 1
