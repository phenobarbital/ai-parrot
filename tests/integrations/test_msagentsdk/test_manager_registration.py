"""
Tests for MSAgentSDKConfig dispatch in IntegrationBotConfig and
manager startup/shutdown plumbing.
"""
import pytest


class TestMSAgentSDKConfigDispatch:
    def test_from_dict_msagentsdk(self):
        """IntegrationBotConfig.from_dict() creates MSAgentSDKConfig for kind=msagentsdk."""
        from parrot.integrations.models import IntegrationBotConfig
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {
            "agents": {
                "CopilotBot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "main_agent",
                    "client_id": "app-123",
                    "client_secret": "secret-456",
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "CopilotBot" in config.agents
        assert isinstance(config.agents["CopilotBot"], MSAgentSDKConfig)

    def test_from_dict_msagentsdk_anonymous(self):
        """anonymous_auth flag is preserved through from_dict dispatch."""
        from parrot.integrations.models import IntegrationBotConfig

        data = {
            "agents": {
                "Bot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "agent",
                    "anonymous_auth": True,
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert config.agents["Bot"].anonymous_auth is True

    def test_from_dict_other_kinds_unaffected(self):
        """Adding msagentsdk dispatch does not break existing kind dispatch."""
        from parrot.integrations.models import IntegrationBotConfig
        from parrot.integrations.telegram.models import TelegramAgentConfig

        data = {
            "agents": {
                "TelegramBot": {
                    "kind": "telegram",
                    "chatbot_id": "agent",
                    "bot_token": "TOKEN",
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert isinstance(config.agents["TelegramBot"], TelegramAgentConfig)


class TestMSAgentSDKConfigValidation:
    def test_validate_missing_credentials_when_not_anonymous(self):
        """validate() reports missing client_id/client_secret if not anonymous."""
        from parrot.integrations.models import IntegrationBotConfig
        from unittest.mock import patch

        # Prevent env var fallback from filling in credentials
        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.return_value = None
            data = {
                "agents": {
                    "CopilotBot": {
                        "kind": "msagentsdk",
                        "chatbot_id": "main_agent",
                        "anonymous_auth": False,
                    }
                }
            }
            config = IntegrationBotConfig.from_dict(data)
            errors = config.validate()

        assert any("client_id" in e for e in errors)
        assert any("client_secret" in e for e in errors)

    def test_validate_anonymous_ok(self):
        """validate() passes for anonymous auth without credentials."""
        from parrot.integrations.models import IntegrationBotConfig
        from unittest.mock import patch

        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.return_value = None
            data = {
                "agents": {
                    "CopilotBot": {
                        "kind": "msagentsdk",
                        "chatbot_id": "main_agent",
                        "anonymous_auth": True,
                    }
                }
            }
            config = IntegrationBotConfig.from_dict(data)
            errors = config.validate()

        # No client_id/client_secret errors expected
        assert not any("client_id" in e for e in errors)
        assert not any("client_secret" in e for e in errors)

    def test_validate_missing_chatbot_id(self):
        """validate() flags missing chatbot_id regardless of kind."""
        from parrot.integrations.models import IntegrationBotConfig
        from unittest.mock import patch

        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.return_value = None
            data = {
                "agents": {
                    "CopilotBot": {
                        "kind": "msagentsdk",
                        "chatbot_id": "",
                        "anonymous_auth": True,
                    }
                }
            }
            config = IntegrationBotConfig.from_dict(data)
            errors = config.validate()

        assert any("chatbot_id" in e for e in errors)


class TestMSAgentSDKManagerBotDict:
    def test_msagentsdk_bots_dict_exists(self):
        """IntegrationBotManager has an msagentsdk_bots dict."""
        from parrot.integrations.manager import IntegrationBotManager
        from unittest.mock import MagicMock

        manager = IntegrationBotManager(MagicMock())
        assert hasattr(manager, "msagentsdk_bots")
        assert isinstance(manager.msagentsdk_bots, dict)
        assert len(manager.msagentsdk_bots) == 0

    @pytest.mark.asyncio
    async def test_start_msagentsdk_bot_stores_wrapper(self):
        """_start_msagentsdk_bot stores wrapper in msagentsdk_bots."""
        from parrot.integrations.manager import IntegrationBotManager
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
        from unittest.mock import MagicMock, AsyncMock, patch

        bot_manager = MagicMock()
        bot_manager.get_app.return_value = MagicMock()
        manager = IntegrationBotManager(bot_manager)

        mock_agent = AsyncMock()
        manager._get_agent = AsyncMock(return_value=mock_agent)

        cfg = MSAgentSDKConfig(
            name="TestBot", chatbot_id="agent", anonymous_auth=True
        )

        # Patch the wrapper import inside the method
        mock_wrapper_cls = MagicMock()
        mock_wrapper_instance = MagicMock()
        mock_wrapper_cls.return_value = mock_wrapper_instance

        with patch(
            "parrot.integrations.manager.MSAgentSDKConfig",
            MSAgentSDKConfig,
        ), patch.dict(
            "sys.modules",
            {
                "parrot.integrations.msagentsdk.wrapper": MagicMock(
                    MSAgentSDKWrapper=mock_wrapper_cls
                )
            },
        ):
            await manager._start_msagentsdk_bot("TestBot", cfg)

        assert "TestBot" in manager.msagentsdk_bots
        assert manager.msagentsdk_bots["TestBot"] is mock_wrapper_instance

    @pytest.mark.asyncio
    async def test_start_msagentsdk_bot_aborts_if_no_agent(self):
        """_start_msagentsdk_bot does nothing when agent is not found."""
        from parrot.integrations.manager import IntegrationBotManager
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig
        from unittest.mock import MagicMock, AsyncMock

        bot_manager = MagicMock()
        manager = IntegrationBotManager(bot_manager)
        manager._get_agent = AsyncMock(return_value=None)

        cfg = MSAgentSDKConfig(
            name="TestBot", chatbot_id="missing_agent", anonymous_auth=True
        )
        await manager._start_msagentsdk_bot("TestBot", cfg)
        assert "TestBot" not in manager.msagentsdk_bots


@pytest.mark.asyncio
async def test_shutdown_calls_stop_on_all_wrappers():
    """shutdown() calls stop() on each msagentsdk wrapper."""
    from unittest.mock import AsyncMock, MagicMock
    from parrot.integrations.manager import IntegrationBotManager

    bot_manager = MagicMock()
    manager = IntegrationBotManager(bot_manager)

    mock_wrapper = AsyncMock()
    mock_wrapper.stop = AsyncMock()
    manager.msagentsdk_bots["TestBot"] = mock_wrapper

    await manager.shutdown()
    mock_wrapper.stop.assert_awaited_once()
