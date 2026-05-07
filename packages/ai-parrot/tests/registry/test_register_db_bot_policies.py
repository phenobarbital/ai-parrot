"""Unit tests for AgentRegistry.register_db_bot_policies — FEAT-153 TASK-1051.

Tests cover:
  - Loads N policies into the evaluator for valid non-empty permissions.
  - Returns 0 and no-ops for empty / None permissions.
  - Returns 0 and no-ops when self._evaluator is None.
  - Propagates ValueError for malformed permissions (caller handles catch).
  - DB-path and YAML-path produce byte-equal policy dicts (parity test).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.auth.models import PolicyRuleConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry_with_mock_evaluator() -> AgentRegistry:
    """AgentRegistry with a mocked PolicyEvaluator attached."""
    reg = AgentRegistry()
    reg._evaluator = MagicMock()
    reg._evaluator.load_policies = MagicMock()
    return reg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRegisterDbBotPolicies:
    """Unit tests for AgentRegistry.register_db_bot_policies."""

    def test_loads_into_evaluator(self, registry_with_mock_evaluator: AgentRegistry):
        """Non-empty valid permissions → load_policies called once, returns N."""
        n = registry_with_mock_evaluator.register_db_bot_policies(
            "finance_bot",
            {
                "permissions": [
                    {
                        "action": "agent:resolve",
                        "effect": "allow",
                        "groups": ["finance"],
                    },
                ],
            },
        )
        assert n == 1
        registry_with_mock_evaluator._evaluator.load_policies.assert_called_once()
        # Verify the policy dict has the correct resource
        call_args = registry_with_mock_evaluator._evaluator.load_policies.call_args
        policy_dicts = call_args[0][0]
        assert len(policy_dicts) == 1
        assert "agent:finance_bot" in policy_dicts[0]["resources"]

    def test_empty_dict_no_op(self, registry_with_mock_evaluator: AgentRegistry):
        """Empty permissions ({}) → 0 policies registered, evaluator not called."""
        n = registry_with_mock_evaluator.register_db_bot_policies("bot", {})
        assert n == 0
        registry_with_mock_evaluator._evaluator.load_policies.assert_not_called()

    def test_none_no_op(self, registry_with_mock_evaluator: AgentRegistry):
        """None permissions → 0 policies registered, evaluator not called."""
        n = registry_with_mock_evaluator.register_db_bot_policies("bot", None)
        assert n == 0
        registry_with_mock_evaluator._evaluator.load_policies.assert_not_called()

    def test_empty_permissions_list_no_op(self, registry_with_mock_evaluator: AgentRegistry):
        """permissions=[] (empty) → 0, evaluator not called."""
        n = registry_with_mock_evaluator.register_db_bot_policies(
            "bot", {"permissions": []}
        )
        assert n == 0
        registry_with_mock_evaluator._evaluator.load_policies.assert_not_called()

    def test_no_evaluator_no_op(self):
        """When self._evaluator is None → returns 0 without error."""
        reg = AgentRegistry()
        reg._evaluator = None
        # Provide valid permissions — should still be a no-op
        n = reg.register_db_bot_policies(
            "bot",
            {"permissions": [{"action": "agent:resolve", "effect": "allow"}]},
        )
        assert n == 0

    def test_malformed_permissions_raises(self, registry_with_mock_evaluator: AgentRegistry):
        """Malformed permissions → ValueError raised (caller is responsible for catch)."""
        with pytest.raises(ValueError):
            registry_with_mock_evaluator.register_db_bot_policies(
                "bot",
                {"permissions": "not-a-list"},
            )

    def test_multiple_rules_loaded(self, registry_with_mock_evaluator: AgentRegistry):
        """Multiple rules → all loaded in single load_policies call."""
        n = registry_with_mock_evaluator.register_db_bot_policies(
            "finance_bot",
            {
                "permissions": [
                    {"action": "agent:resolve", "effect": "allow",
                     "groups": ["engineering", "ops"], "priority": 10},
                    {"action": "agent:resolve", "effect": "deny",
                     "roles": ["contractors"], "priority": 100},
                ],
            },
        )
        assert n == 2
        call_args = registry_with_mock_evaluator._evaluator.load_policies.call_args
        policy_dicts = call_args[0][0]
        assert len(policy_dicts) == 2

    def test_db_path_parity_with_yaml_path(self):
        """DB-loaded and YAML-loaded same rule produce identical policy dicts.

        This is the parity acceptance criterion from spec §4:
        the same PolicyRuleConfig registered via DB path and via YAML path
        must produce byte-equal policy dicts.
        """
        rule_data = {
            "action": "agent:resolve",
            "effect": "allow",
            "groups": ["finance"],
            "priority": 10,
        }
        bot_name = "finance_bot"

        # --- DB path ---
        reg_db = AgentRegistry()
        reg_db._evaluator = MagicMock()
        reg_db._evaluator.load_policies = MagicMock()
        reg_db.register_db_bot_policies(bot_name, {"permissions": [rule_data]})
        db_dicts = reg_db._evaluator.load_policies.call_args[0][0]

        # --- YAML path: _collect_and_register_policies ---
        reg_yaml = AgentRegistry()
        reg_yaml._evaluator = MagicMock()
        reg_yaml._evaluator.load_policies = MagicMock()

        # Build a BotConfig with the same rule
        rule = PolicyRuleConfig(**rule_data)
        bot_config = BotConfig(
            name=bot_name,
            class_name="parrot.bots.agent.BasicAgent",
            module="parrot.bots.agent",
            policies=[rule],
        )

        # Call the YAML-path method directly (using a dummy factory class)
        class _FakeFactory:
            policy_rules = []

        reg_yaml._collect_and_register_policies(bot_name, _FakeFactory, bot_config)
        yaml_dicts = reg_yaml._evaluator.load_policies.call_args[0][0]

        # The policy dicts must be byte-equal
        assert db_dicts == yaml_dicts, (
            f"DB path produced: {db_dicts}\n"
            f"YAML path produced: {yaml_dicts}"
        )
