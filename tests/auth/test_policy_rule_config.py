"""Unit tests for PolicyRuleConfig model (TASK-707).

Tests cover valid creation, default values, to_resource_policy() conversion,
and validation rejection of invalid inputs.
"""
import pytest
from pydantic import ValidationError
from parrot.auth.models import PolicyRuleConfig
from parrot.auth import PolicyRuleConfig as PolicyRuleConfigFromInit  # noqa: F401


class TestPolicyRuleConfigCreation:
    """Tests for model creation and defaults."""

    def test_valid_creation_minimal(self):
        """Minimal valid creation with only action."""
        rule = PolicyRuleConfig(action="agent:chat")
        assert rule.action == "agent:chat"
        assert rule.effect == "allow"
        assert rule.priority == 10
        assert rule.groups is None
        assert rule.roles is None
        assert rule.description is None
        assert rule.conditions is None

    def test_valid_creation_with_groups(self):
        """Valid creation with groups."""
        rule = PolicyRuleConfig(action="agent:chat", groups=["engineering"])
        assert rule.effect == "allow"
        assert rule.priority == 10
        assert rule.groups == ["engineering"]

    def test_deny_effect(self):
        """Deny effect is accepted."""
        rule = PolicyRuleConfig(action="agent:chat", effect="deny", groups=["contractors"])
        assert rule.effect == "deny"

    def test_custom_priority(self):
        """Custom priority is accepted."""
        rule = PolicyRuleConfig(action="agent:chat", priority=25)
        assert rule.priority == 25

    def test_full_fields(self):
        """All fields can be set."""
        rule = PolicyRuleConfig(
            action="agent:configure",
            effect="allow",
            groups=["admins"],
            roles=["superadmin"],
            priority=15,
            description="Allow admins to configure",
            conditions={"time": "business_hours"},
        )
        assert rule.action == "agent:configure"
        assert rule.roles == ["superadmin"]
        assert rule.description == "Allow admins to configure"
        assert rule.conditions == {"time": "business_hours"}


class TestPolicyRuleConfigValidation:
    """Tests for validation rejection."""

    def test_invalid_effect_rejected(self):
        """Invalid effect value is rejected."""
        with pytest.raises((ValidationError, Exception)):
            PolicyRuleConfig(action="agent:chat", effect="maybe")

    def test_empty_action_rejected(self):
        """Empty action string is rejected."""
        with pytest.raises((ValidationError, Exception)):
            PolicyRuleConfig(action="")

    def test_whitespace_action_rejected(self):
        """Whitespace-only action is rejected."""
        with pytest.raises((ValidationError, Exception)):
            PolicyRuleConfig(action="   ")

    def test_missing_action_rejected(self):
        """Missing action field is rejected."""
        with pytest.raises((ValidationError, Exception)):
            PolicyRuleConfig()  # type: ignore[call-arg]


class TestPolicyRuleConfigToResourcePolicy:
    """Tests for to_resource_policy() conversion."""

    def test_to_resource_policy_basic(self):
        """Basic conversion produces correct dict."""
        rule = PolicyRuleConfig(action="agent:chat", effect="allow", groups=["finance"])
        policy = rule.to_resource_policy("finance_bot")
        assert policy["resources"] == ["agent:finance_bot"]
        assert policy["actions"] == ["agent:chat"]
        assert policy["effect"] == "allow"
        assert policy["subjects"]["groups"] == ["finance"]
        assert policy["priority"] == 10

    def test_to_resource_policy_with_roles(self):
        """Roles are included in subjects."""
        rule = PolicyRuleConfig(action="agent:configure", roles=["admin"])
        policy = rule.to_resource_policy("my_bot")
        assert policy["subjects"]["roles"] == ["admin"]
        assert "groups" not in policy["subjects"]

    def test_to_resource_policy_with_groups_and_roles(self):
        """Both groups and roles are included in subjects."""
        rule = PolicyRuleConfig(
            action="agent:chat",
            groups=["engineering"],
            roles=["developer"]
        )
        policy = rule.to_resource_policy("dev_bot")
        assert policy["subjects"]["groups"] == ["engineering"]
        assert policy["subjects"]["roles"] == ["developer"]

    def test_to_resource_policy_deny(self):
        """Deny effect is preserved in policy dict."""
        rule = PolicyRuleConfig(action="agent:chat", effect="deny", groups=["external"])
        policy = rule.to_resource_policy("secure_bot")
        assert policy["effect"] == "deny"

    def test_to_resource_policy_custom_priority(self):
        """Custom priority is preserved."""
        rule = PolicyRuleConfig(action="agent:chat", priority=25)
        policy = rule.to_resource_policy("bot")
        assert policy["priority"] == 25

    def test_to_resource_policy_name_format(self):
        """Policy name follows expected format."""
        rule = PolicyRuleConfig(action="agent:chat")
        policy = rule.to_resource_policy("test_bot")
        assert "test_bot" in policy["name"]
        assert "agent:chat" in policy["name"]

    def test_to_resource_policy_empty_subjects(self):
        """Empty subjects dict when no groups or roles specified."""
        rule = PolicyRuleConfig(action="agent:list")
        policy = rule.to_resource_policy("public_bot")
        assert policy["subjects"] == {}

    def test_to_resource_policy_with_conditions(self):
        """Conditions are passed through to policy dict."""
        rule = PolicyRuleConfig(
            action="agent:chat",
            conditions={"time": "business_hours"}
        )
        policy = rule.to_resource_policy("timed_bot")
        assert policy["conditions"] == {"time": "business_hours"}

    def test_to_resource_policy_with_description(self):
        """Description is included in policy dict when set."""
        rule = PolicyRuleConfig(
            action="agent:chat",
            description="Allow engineering team chat access",
        )
        policy = rule.to_resource_policy("eng_bot")
        assert policy["description"] == "Allow engineering team chat access"

    def test_to_resource_policy_no_description(self):
        """No description key when description is None."""
        rule = PolicyRuleConfig(action="agent:chat")
        policy = rule.to_resource_policy("bot")
        assert "description" not in policy


class TestPolicyRuleConfigImportPaths:
    """Tests that module exports work correctly."""

    def test_import_from_models(self):
        """PolicyRuleConfig is importable from parrot.auth.models."""
        from parrot.auth.models import PolicyRuleConfig as PRC
        assert PRC is PolicyRuleConfig

    def test_import_from_parrot_auth(self):
        """PolicyRuleConfig is importable from parrot.auth."""
        from parrot.auth import PolicyRuleConfig as PRC
        assert PRC is PolicyRuleConfig
