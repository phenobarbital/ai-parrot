"""Unit tests for post_auth_actions config parsing (FEAT-108 / TASK-756)."""
import pytest

from parrot.integrations.telegram.models import (
    PostAuthAction,
    TelegramAgentConfig,
    TelegramBotsConfig,
)


class TestPostAuthAction:
    """Tests for the PostAuthAction dataclass."""

    def test_defaults(self):
        action = PostAuthAction(provider="jira")
        assert action.provider == "jira"
        assert action.required is False

    def test_required_true(self):
        action = PostAuthAction(provider="jira", required=True)
        assert action.required is True

    def test_required_false_explicit(self):
        action = PostAuthAction(provider="github", required=False)
        assert action.provider == "github"
        assert action.required is False


class TestTelegramAgentConfigPostAuth:
    """Tests for TelegramAgentConfig.from_dict() post_auth_actions parsing."""

    def test_from_dict_with_post_auth_actions(self):
        data = {
            "chatbot_id": "test",
            "auth_method": "basic",
            "post_auth_actions": [
                {"provider": "jira", "required": True},
                {"provider": "confluence"},
            ],
        }
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert len(config.post_auth_actions) == 2
        assert config.post_auth_actions[0].provider == "jira"
        assert config.post_auth_actions[0].required is True
        assert config.post_auth_actions[1].provider == "confluence"
        assert config.post_auth_actions[1].required is False

    def test_from_dict_without_post_auth_actions(self):
        data = {"chatbot_id": "test"}
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert config.post_auth_actions == []

    def test_from_dict_empty_post_auth_actions(self):
        data = {"chatbot_id": "test", "post_auth_actions": []}
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert config.post_auth_actions == []

    def test_from_dict_single_post_auth_action(self):
        data = {
            "chatbot_id": "test",
            "post_auth_actions": [
                {"provider": "jira", "required": True},
            ],
        }
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert len(config.post_auth_actions) == 1
        assert config.post_auth_actions[0].provider == "jira"
        assert config.post_auth_actions[0].required is True

    def test_from_dict_accepts_existing_postauthaction_instances(self):
        """When entries are already PostAuthAction instances, they pass through."""
        entry = PostAuthAction(provider="jira", required=True)
        data = {
            "chatbot_id": "test",
            "post_auth_actions": [entry],
        }
        config = TelegramAgentConfig.from_dict("test_bot", data)
        assert len(config.post_auth_actions) == 1
        assert config.post_auth_actions[0] is entry

    def test_post_auth_actions_default_empty_list_on_direct_construction(self):
        """Directly-constructed config defaults post_auth_actions to []."""
        config = TelegramAgentConfig(name="t", chatbot_id="t")
        assert config.post_auth_actions == []

    def test_post_auth_actions_independent_defaults(self):
        """Each instance gets its own default list (no mutable default bug)."""
        c1 = TelegramAgentConfig(name="a", chatbot_id="a")
        c2 = TelegramAgentConfig(name="b", chatbot_id="b")
        c1.post_auth_actions.append(PostAuthAction(provider="jira"))
        assert c2.post_auth_actions == []


class TestTelegramBotsConfigValidation:
    """Tests for TelegramBotsConfig.validate() soft-warning behavior."""

    def test_validate_known_provider_no_warning(self, caplog):
        """'jira' is a known provider; no warning emitted."""
        bots = TelegramBotsConfig.from_dict({
            "agents": {
                "MyBot": {
                    "chatbot_id": "my_bot",
                    "bot_token": "abc",
                    "post_auth_actions": [
                        {"provider": "jira", "required": True},
                    ],
                }
            }
        })
        import logging as _logging
        with caplog.at_level(_logging.WARNING,
                             logger="parrot.integrations.telegram.models"):
            errors = bots.validate()
        assert errors == []
        # No warning about unknown provider
        assert not any(
            "unknown" in rec.message.lower() and "provider" in rec.message.lower()
            for rec in caplog.records
        )

    def test_validate_unknown_provider_warns(self, caplog):
        """Unknown providers trigger a soft warning (not an error)."""
        bots = TelegramBotsConfig.from_dict({
            "agents": {
                "MyBot": {
                    "chatbot_id": "my_bot",
                    "bot_token": "abc",
                    "post_auth_actions": [
                        {"provider": "mystery_provider", "required": False},
                    ],
                }
            }
        })
        import logging as _logging
        with caplog.at_level(_logging.WARNING,
                             logger="parrot.integrations.telegram.models"):
            errors = bots.validate()
        # Soft warning — not an error.
        assert errors == []
        assert any(
            "mystery_provider" in rec.message for rec in caplog.records
        )
