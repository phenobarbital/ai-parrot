"""Tests for explicit resources on policy rule configuration."""

from parrot.auth.agent_guard import parse_bot_permissions
from parrot.auth.models import PolicyRuleConfig

PINNED = {
    "name": "code_rule_finance_bot_agent:chat",
    "effect": "allow",
    "resources": ["agent:finance_bot"],
    "actions": ["agent:chat"],
    "subjects": {"groups": ["finance"]},
    "priority": 10,
}


def test_policy_rule_without_resource_is_unchanged() -> None:
    """Rules without a resource retain the pre-change policy shape."""
    rule = PolicyRuleConfig(action="agent:chat", groups=["finance"])

    assert rule.to_resource_policy("finance_bot") == PINNED


def test_policy_rule_resource_override() -> None:
    """An explicit resource replaces the default agent resource."""
    rule = PolicyRuleConfig(action="tool:execute", resource="tool:spawn_sub_agent")

    policy = rule.to_resource_policy("finance_bot")

    assert policy["resources"] == ["tool:spawn_sub_agent"]
    assert policy["name"] == "code_rule_finance_bot_tool:execute_tool:spawn_sub_agent"


def test_policy_rule_resource_names_do_not_collide() -> None:
    """Rules for different explicit resources receive distinct names."""
    first = PolicyRuleConfig(action="tool:execute", resource="tool:spawn_sub_agent")
    second = PolicyRuleConfig(action="tool:execute", resource="tool:search")

    first_name = first.to_resource_policy("finance_bot")["name"]
    second_name = second.to_resource_policy("finance_bot")["name"]

    assert first_name != second_name


def test_parse_bot_permissions_accepts_resource() -> None:
    """The public parser accepts and preserves an explicit resource."""
    rules = parse_bot_permissions([{"action": "tool:execute", "effect": "deny", "resource": "tool:spawn_sub_agent"}])

    assert len(rules) == 1
    assert rules[0].resource == "tool:spawn_sub_agent"
