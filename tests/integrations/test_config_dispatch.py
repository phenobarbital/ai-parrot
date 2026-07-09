"""
Tests for IntegrationBotConfig.from_dict() dispatch across all supported
``kind`` values, including the new ``a2a`` and ``msagent`` kinds (TASK-1708).
"""
from parrot.integrations.models import IntegrationBotConfig
from parrot.integrations.telegram.models import TelegramAgentConfig
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.whatsapp.models import WhatsAppAgentConfig
from parrot.integrations.slack.models import SlackAgentConfig
from parrot.integrations.msagentsdk.models import MSAgentSDKConfig, MSAgentIntegrationConfig
from parrot.integrations.a2a.models import A2AAgentConfig


class TestConfigDispatchNewKinds:
    def test_a2a_kind_parsed(self):
        data = {"agents": {"TestA2A": {"kind": "a2a", "chatbot_id": "test"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "TestA2A" in config.agents
        assert isinstance(config.agents["TestA2A"], A2AAgentConfig)
        assert config.agents["TestA2A"].kind == "a2a"

    def test_msagent_kind_parsed(self):
        data = {"agents": {"TestMS": {"kind": "msagent", "chatbot_id": "test"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "TestMS" in config.agents
        assert isinstance(config.agents["TestMS"], MSAgentIntegrationConfig)
        assert config.agents["TestMS"].kind == "msagent"


class TestConfigDispatchExistingKinds:
    def test_telegram_kind_unaffected(self):
        data = {
            "agents": {
                "Bot": {"kind": "telegram", "chatbot_id": "x", "bot_token": "t"}
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "Bot" in config.agents
        assert isinstance(config.agents["Bot"], TelegramAgentConfig)

    def test_msteams_kind_unaffected(self):
        data = {
            "agents": {
                "Bot": {
                    "kind": "msteams",
                    "chatbot_id": "x",
                    "client_id": "id",
                    "client_secret": "secret",
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "Bot" in config.agents
        assert isinstance(config.agents["Bot"], MSTeamsAgentConfig)

    def test_whatsapp_kind_unaffected(self):
        data = {
            "agents": {
                "Bot": {
                    "kind": "whatsapp",
                    "chatbot_id": "x",
                    "phone_id": "p",
                    "token": "t",
                    "verify_token": "v",
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "Bot" in config.agents
        assert isinstance(config.agents["Bot"], WhatsAppAgentConfig)

    def test_slack_kind_unaffected(self):
        data = {
            "agents": {
                "Bot": {"kind": "slack", "chatbot_id": "x", "bot_token": "t"}
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "Bot" in config.agents
        assert isinstance(config.agents["Bot"], SlackAgentConfig)

    def test_msagentsdk_kind_unaffected(self):
        data = {
            "agents": {
                "Bot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "x",
                    "anonymous_auth": True,
                }
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert "Bot" in config.agents
        assert isinstance(config.agents["Bot"], MSAgentSDKConfig)


class TestConfigDispatchUnknownKind:
    def test_unknown_kind_skipped(self):
        data = {"agents": {"X": {"kind": "unknown", "chatbot_id": "x"}}}
        config = IntegrationBotConfig.from_dict(data)
        assert "X" not in config.agents

    def test_empty_agent_data_skipped(self):
        data = {"agents": {"X": None}}
        config = IntegrationBotConfig.from_dict(data)
        assert "X" not in config.agents

    def test_empty_config_returns_no_agents(self):
        config = IntegrationBotConfig.from_dict({})
        assert config.agents == {}

    def test_none_config_returns_no_agents(self):
        config = IntegrationBotConfig.from_dict(None)
        assert config.agents == {}


class TestConfigDispatchMixedKinds:
    def test_all_seven_kinds_coexist(self):
        """A YAML with all supported kinds parses each into the right type."""
        data = {
            "agents": {
                "TelegramBot": {
                    "kind": "telegram",
                    "chatbot_id": "a",
                    "bot_token": "t",
                },
                "TeamsBot": {
                    "kind": "msteams",
                    "chatbot_id": "b",
                    "client_id": "id",
                    "client_secret": "secret",
                },
                "WhatsAppBot": {
                    "kind": "whatsapp",
                    "chatbot_id": "c",
                    "phone_id": "p",
                    "token": "t",
                    "verify_token": "v",
                },
                "SlackBot": {"kind": "slack", "chatbot_id": "d", "bot_token": "t"},
                "SDKBot": {
                    "kind": "msagentsdk",
                    "chatbot_id": "e",
                    "anonymous_auth": True,
                },
                "A2ABot": {"kind": "a2a", "chatbot_id": "f"},
                "MSAgentBot": {"kind": "msagent", "chatbot_id": "g"},
            }
        }
        config = IntegrationBotConfig.from_dict(data)
        assert len(config.agents) == 7
        assert isinstance(config.agents["TelegramBot"], TelegramAgentConfig)
        assert isinstance(config.agents["TeamsBot"], MSTeamsAgentConfig)
        assert isinstance(config.agents["WhatsAppBot"], WhatsAppAgentConfig)
        assert isinstance(config.agents["SlackBot"], SlackAgentConfig)
        assert isinstance(config.agents["SDKBot"], MSAgentSDKConfig)
        assert isinstance(config.agents["A2ABot"], A2AAgentConfig)
        assert isinstance(config.agents["MSAgentBot"], MSAgentIntegrationConfig)
