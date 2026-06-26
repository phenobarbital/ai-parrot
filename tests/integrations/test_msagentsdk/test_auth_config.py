"""
Unit tests for MSAgentSDKConfig oauth_connections and obo_scopes fields.

Covers FEAT-261 Module 1 (Config Extension).
"""
import json
from unittest.mock import patch


class TestOAuthConfigFields:
    """Tests for the oauth_connections and obo_scopes fields."""

    def test_config_oauth_connections(self):
        """oauth_connections and obo_scopes are stored correctly."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig(
            name="TestBot",
            chatbot_id="test_agent",
            anonymous_auth=True,
            oauth_connections={"o365": "graph_sso", "jira": "jira_oauth"},
            obo_scopes={"o365": ["https://graph.microsoft.com/.default"]},
        )
        assert cfg.oauth_connections == {"o365": "graph_sso", "jira": "jira_oauth"}
        assert cfg.obo_scopes == {"o365": ["https://graph.microsoft.com/.default"]}

    def test_config_oauth_connections_empty(self):
        """Empty oauth_connections is valid and backward compatible."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        cfg = MSAgentSDKConfig(
            name="Bot",
            chatbot_id="bot",
            anonymous_auth=True,
        )
        assert cfg.oauth_connections == {}
        assert cfg.obo_scopes == {}

    def test_config_from_dict_with_oauth(self):
        """from_dict() correctly parses oauth_connections and obo_scopes."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {
            "chatbot_id": "agent",
            "anonymous_auth": True,
            "oauth_connections": {"o365": "graph_sso"},
            "obo_scopes": {"o365": ["https://graph.microsoft.com/.default"]},
        }
        cfg = MSAgentSDKConfig.from_dict("TestBot", data)
        assert cfg.oauth_connections == {"o365": "graph_sso"}
        assert cfg.obo_scopes == {"o365": ["https://graph.microsoft.com/.default"]}

    def test_config_from_dict_no_oauth_defaults_empty(self):
        """from_dict() defaults oauth_connections and obo_scopes to empty."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        data = {"chatbot_id": "agent", "anonymous_auth": True}
        cfg = MSAgentSDKConfig.from_dict("TestBot", data)
        assert cfg.oauth_connections == {}
        assert cfg.obo_scopes == {}

    def test_env_fallback_oauth_connections(self):
        """__post_init__ reads OAUTH_CONNECTIONS env var (JSON)."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        connections = {"o365": "graph_sso"}
        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.side_effect = lambda key: (
                json.dumps(connections)
                if key == "TESTBOT_OAUTH_CONNECTIONS"
                else None
            )
            cfg = MSAgentSDKConfig(name="TestBot", chatbot_id="agent")
        assert cfg.oauth_connections == connections

    def test_env_fallback_obo_scopes(self):
        """__post_init__ reads OBO_SCOPES env var (JSON)."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        scopes = {"o365": ["https://graph.microsoft.com/.default"]}
        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.side_effect = lambda key: (
                json.dumps(scopes) if key == "TESTBOT_OBO_SCOPES" else None
            )
            cfg = MSAgentSDKConfig(name="TestBot", chatbot_id="agent")
        assert cfg.obo_scopes == scopes

    def test_explicit_oauth_not_overridden_by_env(self):
        """Explicit oauth_connections takes precedence over env var."""
        from parrot.integrations.msagentsdk.models import MSAgentSDKConfig

        explicit = {"jira": "jira_oauth"}
        with patch("parrot.integrations.msagentsdk.models.config") as mock_cfg:
            mock_cfg.get.return_value = json.dumps({"o365": "graph_sso"})
            cfg = MSAgentSDKConfig(
                name="TestBot",
                chatbot_id="agent",
                oauth_connections=explicit,
            )
        assert cfg.oauth_connections == explicit
