"""Integration tests for PBAC Policy Rules (TASK-716).

End-to-end tests verifying the full policy flow:
  1. Bot declares policy_rules → retrieval() enforces
  2. Two bots with different policies → listing returns only allowed
  3. Per-agent YAML → evaluator uses it for filtering
  4. ToolList.get() filters tools based on policy
  5. Bot without policy_rules → access allowed by default (fail-open)

All tests use mocked PDP/evaluator (no need for running navigator-auth).
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web

from parrot.auth.models import PolicyRuleConfig
from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.bots.abstract import AbstractBot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_concrete_bot(name: str = "test_bot", policy_rules=None):
    """Create a minimal AbstractBot subclass."""
    class ConcreteBot(AbstractBot):
        async def chat(self, message, **kwargs):
            return "ok"

        async def stream(self, message, **kwargs):
            yield "ok"

        async def invoke(self, message, **kwargs):
            return "ok"

    ConcreteBot.__name__ = f"ConcreteBot_{name}"
    if policy_rules is not None:
        ConcreteBot.policy_rules = policy_rules
    return ConcreteBot


def _make_mock_evaluator(allow_all: bool = True, allowed_agents: list | None = None):
    """Create a mock PolicyEvaluator with configurable behaviour."""
    evaluator = MagicMock()

    # check_access: allow or deny
    def check_access(ctx, resource_type, name, action):
        result = MagicMock()
        if allow_all:
            result.allowed = True
            result.reason = "allowed"
        else:
            result.allowed = False
            result.reason = "policy denied"
        return result

    evaluator.check_access = MagicMock(side_effect=check_access)

    # filter_resources: return only allowed names
    def filter_resources(ctx, resource_type, names, action):
        result = MagicMock()
        if allow_all:
            result.allowed = list(names)
        else:
            result.allowed = allowed_agents or []
        return result

    evaluator.filter_resources = MagicMock(side_effect=filter_resources)
    evaluator.load_policies = MagicMock()

    return evaluator


def _make_mock_app(evaluator=None):
    """Create a mock aiohttp Application with optional PDP evaluator."""
    app = MagicMock()
    if evaluator is not None:
        pdp = MagicMock()
        pdp._evaluator = evaluator
        app.get = MagicMock(return_value=pdp)
        app.__setitem__ = MagicMock()
        app.__getitem__ = MagicMock(return_value=pdp)
    else:
        app.get = MagicMock(return_value=None)
    return app


def _make_mock_request(app, username="testuser", groups=None):
    """Create a mock request with session."""
    request = MagicMock(spec=web.Request)
    session = MagicMock()
    session.get = MagicMock(return_value={
        "username": username,
        "groups": groups or ["engineering"],
        "roles": [],
        "programs": [],
    })
    request.session = session
    request.app = app
    return request


# ---------------------------------------------------------------------------
# Scenario 1: Bot with policy_rules → retrieval() enforces
# ---------------------------------------------------------------------------

class TestScenario1RetrievalEnforcement:
    """Bot declares policy_rules → retrieval() denies unauthorized user."""

    @pytest.mark.asyncio
    async def test_retrieval_denies_when_evaluator_denies(self):
        """Bot with policy_rules → retrieval() raises HTTPUnauthorized."""
        BotClass = _make_concrete_bot(
            "finance_bot",
            policy_rules=[{"action": "agent:chat", "groups": ["finance"]}]
        )
        # Evaluator that denies (engineering user, not finance)
        evaluator = _make_mock_evaluator(allow_all=False)
        app = _make_mock_app(evaluator)
        request = _make_mock_request(app, groups=["engineering"])

        # Create a minimal bot instance
        bot = MagicMock(spec=BotClass)
        bot.name = "finance_bot"
        bot._semaphore = asyncio.BoundedSemaphore(1)
        bot.logger = MagicMock()
        bot.retrieval = AbstractBot.retrieval.__get__(bot, BotClass)

        with patch('parrot.bots.abstract._PBAC_AVAILABLE', True), \
             patch('parrot.bots.abstract._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.bots.abstract._ResourceType', MagicMock(AGENT='AGENT')):
            with pytest.raises(web.HTTPUnauthorized):
                async with bot.retrieval(request=request) as wrapper:
                    pass

    @pytest.mark.asyncio
    async def test_retrieval_allows_when_evaluator_allows(self):
        """Bot with policy_rules → retrieval() yields wrapper when allowed."""
        BotClass = _make_concrete_bot(
            "public_bot",
            policy_rules=[{"action": "agent:chat", "groups": ["*"]}]
        )
        evaluator = _make_mock_evaluator(allow_all=True)
        app = _make_mock_app(evaluator)
        request = _make_mock_request(app, groups=["engineering"])

        bot = MagicMock(spec=BotClass)
        bot.name = "public_bot"
        bot._semaphore = asyncio.BoundedSemaphore(1)
        bot.logger = MagicMock()
        bot.retrieval = AbstractBot.retrieval.__get__(bot, BotClass)

        with patch('parrot.bots.abstract._PBAC_AVAILABLE', True), \
             patch('parrot.bots.abstract._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.bots.abstract._ResourceType', MagicMock(AGENT='AGENT')):
            async with bot.retrieval(request=request) as wrapper:
                assert wrapper is not None


# ---------------------------------------------------------------------------
# Scenario 2: Two bots → bot listing returns only allowed
# ---------------------------------------------------------------------------

class TestScenario2BotListingFilter:
    """Two bots with different policies → listing returns only allowed."""

    @pytest.mark.asyncio
    async def test_get_all_returns_only_allowed_bots(self):
        """ChatbotHandler._get_all() filters based on policy."""
        from parrot.handlers.bots import ChatbotHandler

        # Evaluator only allows bot_a
        evaluator = _make_mock_evaluator(allow_all=False, allowed_agents=["bot_a"])
        app = _make_mock_app(evaluator)

        handler = MagicMock(spec=ChatbotHandler)
        handler.logger = MagicMock()

        session = MagicMock()
        session.get = MagicMock(return_value={
            "username": "user", "groups": ["guest"],
            "roles": [], "programs": [],
        })
        handler.request = MagicMock()
        handler.request.session = session
        handler.request.app = app

        # Two agents: bot_a and bot_b
        def bot_model_to_dict(agent):
            return {"name": agent.name}

        agent_a = MagicMock()
        agent_a.name = "bot_a"
        agent_b = MagicMock()
        agent_b.name = "bot_b"

        handler._get_db_agents = AsyncMock(return_value=[agent_a, agent_b])
        handler._bot_model_to_dict = MagicMock(side_effect=bot_model_to_dict)
        handler._registry = None
        handler.json_response = MagicMock(return_value={"status": 200})

        handler._get_pbac_evaluator = ChatbotHandler._get_pbac_evaluator.__get__(
            handler, ChatbotHandler
        )
        handler._build_eval_context = ChatbotHandler._build_eval_context.__get__(
            handler, ChatbotHandler
        )
        handler._get_all = ChatbotHandler._get_all.__get__(handler, ChatbotHandler)

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(AGENT='AGENT')):
            await handler._get_all()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        agent_names = [a["name"] for a in result["agents"]]
        assert "bot_a" in agent_names
        assert "bot_b" not in agent_names


# ---------------------------------------------------------------------------
# Scenario 3: AgentRegistry registers policies from class + BotConfig
# ---------------------------------------------------------------------------

class TestScenario3PolicyRegistration:
    """AgentRegistry.register() collects and registers policies with PDP."""

    def _make_registry_with_evaluator(self):
        """Create registry with mock evaluator.

        The TemporaryDirectory is kept alive for the lifetime of the returned
        registry by storing it as an attribute.  Without this, the tmpdir is
        deleted as soon as the ``with`` block exits, leaving the registry
        pointing at a non-existent path and causing flaky FileNotFoundError.
        """
        import tempfile
        from pathlib import Path
        # Keep tmpdir alive — stored on the registry so it is cleaned up when
        # the registry object is garbage-collected after the test.
        tmpdir_ctx = tempfile.TemporaryDirectory()
        tmpdir = tmpdir_ctx.name
        registry = AgentRegistry(agents_dir=Path(tmpdir) / "agents")
        registry._tmpdir_ctx = tmpdir_ctx  # prevent premature cleanup
        evaluator = MagicMock()
        evaluator.load_policies = MagicMock()
        registry._evaluator = evaluator
        return registry, evaluator

    def test_class_policy_rules_registered_on_register(self):
        """Policies from class attribute are loaded into evaluator."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot("finance_bot", policy_rules=[
            {"action": "agent:chat", "groups": ["finance"]}
        ])
        registry.register("finance_bot", BotClass)

        evaluator.load_policies.assert_called_once()
        loaded = evaluator.load_policies.call_args[0][0]
        assert len(loaded) == 1
        assert loaded[0]["resources"] == ["agent:finance_bot"]

    def test_botconfig_policies_registered_on_register(self):
        """Policies from BotConfig.policies are loaded into evaluator."""
        registry, evaluator = self._make_registry_with_evaluator()

        BotClass = _make_concrete_bot("config_bot", policy_rules=[])
        bot_config = BotConfig(
            name="config_bot",
            class_name="ConfigBot",
            module="parrot.bots",
            policies=[{"action": "agent:list", "groups": ["ops"]}],
        )
        registry.register("config_bot", BotClass, bot_config=bot_config)

        evaluator.load_policies.assert_called_once()
        loaded = evaluator.load_policies.call_args[0][0]
        assert loaded[0]["actions"] == ["agent:list"]


# ---------------------------------------------------------------------------
# Scenario 4: ToolList.get() filters tools based on policy
# ---------------------------------------------------------------------------

class TestScenario4ToolListFilter:
    """ToolList.get() filters tools based on PBAC policy."""

    @pytest.mark.asyncio
    async def test_toollist_filters_based_on_policy(self):
        """ToolList returns only allowed tools."""
        from parrot.handlers.bots import ToolList

        evaluator = _make_mock_evaluator(allow_all=False, allowed_agents=["tool_public"])
        evaluator.filter_resources = MagicMock(return_value=MagicMock(
            allowed=["tool_public"]
        ))
        app = _make_mock_app(evaluator)

        handler = MagicMock(spec=ToolList)
        session = MagicMock()
        session.get = MagicMock(return_value={
            "username": "restricted_user", "groups": ["guest"],
            "roles": [], "programs": [],
        })
        handler.request = MagicMock()
        handler.request.session = session
        handler.request.app = app
        handler.json_response = MagicMock(return_value={"status": 200})
        handler.error = MagicMock(return_value={"status": 400})
        handler._get_pbac_evaluator = ToolList._get_pbac_evaluator.__get__(
            handler, ToolList
        )
        handler._build_eval_context = ToolList._build_eval_context.__get__(
            handler, ToolList
        )
        handler.get = ToolList.get.__get__(handler, ToolList)

        mock_tools = {"tool_public": "path.public", "tool_admin": "path.admin"}

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(TOOL='TOOL')), \
             patch('parrot.handlers.bots.discover_all', return_value=mock_tools):
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        assert "tool_public" in result["tools"]
        assert "tool_admin" not in result["tools"]


# ---------------------------------------------------------------------------
# Scenario 5: Bot without policy_rules → access allowed by default
# ---------------------------------------------------------------------------

class TestScenario5NoPolicyRulesFailOpen:
    """Bot without policy_rules → access allowed by default (fail-open)."""

    @pytest.mark.asyncio
    async def test_bot_without_policy_rules_allows_access_no_pdp(self):
        """Bot with no policy_rules and no PDP allows access (fail-open)."""
        BotClass = _make_concrete_bot("open_bot")
        # Empty policy_rules (default)
        assert BotClass.policy_rules == []

        app = _make_mock_app(evaluator=None)
        request = _make_mock_request(app)

        bot = MagicMock(spec=BotClass)
        bot.name = "open_bot"
        bot._semaphore = asyncio.BoundedSemaphore(1)
        bot.logger = MagicMock()
        bot.retrieval = AbstractBot.retrieval.__get__(bot, BotClass)

        # No PDP → should allow (fail-open)
        async with bot.retrieval(request=request) as wrapper:
            assert wrapper is not None

    def test_policy_rule_config_to_resource_policy(self):
        """PolicyRuleConfig.to_resource_policy() produces correct dict."""
        rule = PolicyRuleConfig(
            action="agent:chat",
            effect="allow",
            groups=["finance"],
            priority=10,
        )
        policy = rule.to_resource_policy("finance_bot")
        assert policy["resources"] == ["agent:finance_bot"]
        assert policy["actions"] == ["agent:chat"]
        assert policy["effect"] == "allow"
        assert policy["subjects"]["groups"] == ["finance"]
        assert policy["priority"] == 10
