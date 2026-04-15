"""Unit tests for BotConfig.policies field (TASK-709).

Verifies that BotConfig accepts an optional list of PolicyRuleConfig objects
and that existing BotConfigs without policies still validate correctly.
"""
import pytest
from parrot.registry.registry import BotConfig
from parrot.auth.models import PolicyRuleConfig


class TestBotConfigPolicies:
    """Tests for the new policies field on BotConfig."""

    def test_botconfig_without_policies(self):
        """BotConfig without policies field validates with policies=None."""
        cfg = BotConfig(name="test", class_name="Bot", module="parrot.bots")
        assert cfg.policies is None

    def test_botconfig_with_policies_as_dicts(self):
        """BotConfig accepts policies as list of dicts (Pydantic auto-coerces)."""
        cfg = BotConfig(
            name="test",
            class_name="Bot",
            module="parrot.bots",
            policies=[{"action": "agent:chat", "effect": "allow", "groups": ["all"]}],
        )
        assert cfg.policies is not None
        assert len(cfg.policies) == 1
        assert cfg.policies[0].action == "agent:chat"
        assert cfg.policies[0].effect == "allow"
        assert cfg.policies[0].groups == ["all"]

    def test_botconfig_with_policies_as_objects(self):
        """BotConfig accepts policies as list of PolicyRuleConfig objects."""
        rule = PolicyRuleConfig(
            action="agent:configure",
            effect="deny",
            roles=["contractors"],
        )
        cfg = BotConfig(
            name="secure_bot",
            class_name="SecureBot",
            module="agents.secure",
            policies=[rule],
        )
        assert cfg.policies is not None
        assert len(cfg.policies) == 1
        assert cfg.policies[0].action == "agent:configure"
        assert cfg.policies[0].effect == "deny"

    def test_botconfig_with_multiple_policies(self):
        """BotConfig accepts multiple policy rules."""
        cfg = BotConfig(
            name="multi",
            class_name="MultiBot",
            module="agents.multi",
            policies=[
                {"action": "agent:chat", "effect": "allow", "groups": ["engineering"]},
                {"action": "agent:configure", "effect": "allow", "roles": ["admin"]},
            ],
        )
        assert len(cfg.policies) == 2
        assert cfg.policies[0].action == "agent:chat"
        assert cfg.policies[1].action == "agent:configure"

    def test_botconfig_policies_default_is_none(self):
        """Default value for policies is None, not an empty list."""
        cfg = BotConfig(name="bot", class_name="Bot", module="parrot.bots")
        assert cfg.policies is None

    def test_existing_botconfig_fields_unchanged(self):
        """Existing BotConfig fields are not affected by adding policies."""
        cfg = BotConfig(
            name="existing",
            class_name="ExistingBot",
            module="agents.existing",
            enabled=True,
            singleton=True,
            priority=5,
        )
        assert cfg.name == "existing"
        assert cfg.singleton is True
        assert cfg.priority == 5
        assert cfg.policies is None

    def test_botconfig_invalid_policy_raises(self):
        """Invalid policy dict (bad effect) raises validation error."""
        with pytest.raises(Exception):
            BotConfig(
                name="bad",
                class_name="Bot",
                module="parrot.bots",
                policies=[{"action": "agent:chat", "effect": "invalid_effect"}],
            )
