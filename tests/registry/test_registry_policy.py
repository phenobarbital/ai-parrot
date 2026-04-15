"""Unit tests for AgentRegistry policy registration (TASK-710).

Tests cover:
- setup(app) stores app and extracts evaluator
- register() collects and registers policies from factory.policy_rules
- register() collects and registers policies from bot_config.policies
- Invalid rules are logged and skipped
- Works correctly when evaluator is None (setup not called)
"""
import pytest
from unittest.mock import MagicMock, patch

from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.bots.abstract import AbstractBot
from parrot.auth.models import PolicyRuleConfig


def _make_concrete_bot_class(policy_rules=None):
    """Create a minimal concrete AbstractBot subclass for testing."""
    class ConcreteBot(AbstractBot):
        async def chat(self, message, **kwargs):
            return "response"

        async def stream(self, message, **kwargs):
            yield "response"

        async def invoke(self, message, **kwargs):
            return "response"

    if policy_rules is not None:
        ConcreteBot.policy_rules = policy_rules

    return ConcreteBot


def _make_registry():
    """Create an AgentRegistry with a temporary agents dir."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AgentRegistry(agents_dir=Path(tmpdir) / "agents")
        return registry


class TestRegistrySetup:
    """Tests for setup(app) method."""

    def test_setup_stores_app(self):
        """setup(app) stores the Application reference."""
        registry = _make_registry()
        mock_app = MagicMock()
        mock_app.get.return_value = None  # No PDP
        registry.setup(mock_app)
        assert registry._app is mock_app

    def test_setup_extracts_evaluator(self):
        """setup(app) extracts evaluator from app['abac']._evaluator."""
        registry = _make_registry()
        mock_evaluator = MagicMock()
        mock_pdp = MagicMock()
        mock_pdp._evaluator = mock_evaluator
        mock_app = MagicMock()
        mock_app.get.return_value = mock_pdp

        registry.setup(mock_app)

        assert registry._evaluator is mock_evaluator

    def test_setup_no_pdp_evaluator_is_none(self):
        """setup(app) with no PDP sets evaluator to None."""
        registry = _make_registry()
        mock_app = MagicMock()
        mock_app.get.return_value = None  # No PDP

        registry.setup(mock_app)

        assert registry._evaluator is None

    def test_initial_state_no_evaluator(self):
        """AgentRegistry starts with _evaluator=None and _app=None."""
        registry = _make_registry()
        assert registry._app is None
        assert registry._evaluator is None


class TestRegistryPolicyCollection:
    """Tests for _collect_and_register_policies() via register()."""

    def _make_registry_with_evaluator(self):
        """Create registry with a mock evaluator set."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = AgentRegistry(agents_dir=Path(tmpdir) / "agents")
        mock_evaluator = MagicMock()
        mock_evaluator.load_policies = MagicMock()
        registry._evaluator = mock_evaluator
        return registry, mock_evaluator

    def test_register_collects_class_policies(self):
        """register() reads factory.policy_rules and loads into evaluator."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot_class(policy_rules=[
            {"action": "agent:chat", "effect": "allow", "groups": ["engineering"]}
        ])

        registry.register("test_bot", BotClass)

        evaluator.load_policies.assert_called_once()
        loaded = evaluator.load_policies.call_args[0][0]
        assert len(loaded) == 1
        assert loaded[0]["actions"] == ["agent:chat"]
        assert loaded[0]["resources"] == ["agent:test_bot"]

    def test_register_collects_botconfig_policies(self):
        """register() reads bot_config.policies and loads into evaluator."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot_class(policy_rules=[])

        bot_config = BotConfig(
            name="config_bot",
            class_name="ConfigBot",
            module="parrot.bots",
            policies=[{"action": "agent:configure", "groups": ["admins"]}],
        )

        registry.register("config_bot", BotClass, bot_config=bot_config)

        evaluator.load_policies.assert_called_once()
        loaded = evaluator.load_policies.call_args[0][0]
        assert len(loaded) == 1
        assert loaded[0]["actions"] == ["agent:configure"]

    def test_register_no_evaluator_skips(self):
        """register() skips policy loading when evaluator is None."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = AgentRegistry(agents_dir=Path(tmpdir) / "agents")

        # evaluator is None (setup not called)
        BotClass = _make_concrete_bot_class(policy_rules=[
            {"action": "agent:chat", "groups": ["all"]}
        ])
        # Should not raise
        registry.register("no_eval_bot", BotClass)
        assert registry._evaluator is None

    def test_register_invalid_rule_skipped(self):
        """Invalid policy_rules entries are logged as warnings and skipped."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot_class(policy_rules=[
            {"action": "agent:chat"},     # valid
            {"effect": "allow"},           # invalid: missing action
        ])

        # Should not raise — invalid rule is skipped
        registry.register("partial_bot", BotClass)

        # load_policies should be called with only the valid rule
        evaluator.load_policies.assert_called_once()
        loaded = evaluator.load_policies.call_args[0][0]
        assert len(loaded) == 1

    def test_register_no_policies_no_load_call(self):
        """register() does not call load_policies when no policy rules."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot_class(policy_rules=[])

        registry.register("empty_bot", BotClass)

        evaluator.load_policies.assert_not_called()

    def test_register_combines_class_and_config_policies(self):
        """register() combines class attribute + BotConfig policies."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot_class(policy_rules=[
            {"action": "agent:chat", "groups": ["users"]}
        ])
        bot_config = BotConfig(
            name="combined",
            class_name="CombinedBot",
            module="parrot.bots",
            policies=[{"action": "agent:configure", "roles": ["admin"]}],
        )

        registry.register("combined_bot", BotClass, bot_config=bot_config)

        evaluator.load_policies.assert_called_once()
        loaded = evaluator.load_policies.call_args[0][0]
        assert len(loaded) == 2
        actions = {p["actions"][0] for p in loaded}
        assert "agent:chat" in actions
        assert "agent:configure" in actions
