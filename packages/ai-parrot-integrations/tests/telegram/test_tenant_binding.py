"""FEAT-707 — Telegram tenant binding (TASK-4500)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.integrations.telegram.models import TelegramAgentConfig


class _Logger:
    """Minimal logger used by unbound wrapper-method tests."""

    def debug(self, *args, **kwargs) -> None:
        """Accept debug messages."""

    def info(self, *args, **kwargs) -> None:
        """Accept info messages."""

    def error(self, *args, **kwargs) -> None:
        """Accept error messages."""


def _wrapper(config: TelegramAgentConfig, agent=None):
    """Build a wrapper shell without initializing its aiogram resources."""
    wrapper_class = _wrapper_class()
    wrapper = object.__new__(wrapper_class)
    wrapper.config = config
    wrapper.agent = agent or SimpleNamespace()
    wrapper.logger = _Logger()
    wrapper._bot_id = "42"
    wrapper._agent_lock = asyncio.Lock()
    return wrapper


def _wrapper_class():
    """Import the wrapper only when its optional runtime stack is available."""
    pytest.importorskip("aiogram")
    module = pytest.importorskip("parrot.integrations.telegram.wrapper")
    return module.TelegramAgentWrapper


def _session():
    """Create the smallest valid Telegram session for wrapper calls."""
    pytest.importorskip("aiogram")
    from parrot.integrations.telegram.auth import TelegramUserSession

    return TelegramUserSession(telegram_id=99, telegram_username="alice")


def test_telegram_config_tenant_from_yaml_and_default_none():
    """YAML tenant configuration is preserved and remains optional."""
    configured = TelegramAgentConfig.from_dict("finance", {"tenant": "acme"})
    defaulted = TelegramAgentConfig.from_dict("finance", {})

    assert configured.tenant == "acme"
    assert defaulted.tenant is None


def test_permission_context_and_user_context_bind_tenant():
    """Permission and user contexts receive the configured static tenant."""
    wrapper_class = _wrapper_class()

    session = _session()
    configured = TelegramAgentConfig(name="finance", chatbot_id="finance", tenant="acme")
    context = wrapper_class._build_permission_context(session, tenant_id=configured.tenant)
    default_context = wrapper_class._build_permission_context(session)
    user_context = _wrapper(configured)._build_user_context(session)

    assert context.session.tenant_id == "acme"
    assert default_context.session.tenant_id == "default"
    assert user_context.metadata["tenant"] == "acme"


@pytest.mark.asyncio
@pytest.mark.parametrize("singleton", [True, False])
async def test_invoke_passes_tenant_for_singleton_and_per_user_agents(singleton: bool):
    """Both invocation branches pass the static tenant without mutating the agent."""
    agent = SimpleNamespace(
        ask=AsyncMock(return_value="ok"),
        tool_manager=SimpleNamespace(),
        enable_tools=False,
        sync_tools=lambda: None,
    )
    config = TelegramAgentConfig(
        name="finance", chatbot_id="finance", tenant="acme", singleton_agent=singleton, agent_timeout=1
    )
    wrapper = _wrapper(config, agent)
    session = _session()

    async def resolve_agent(*args, **kwargs):
        return agent, SimpleNamespace(tool_count=lambda: 0) if singleton else None

    wrapper._resolve_agent_for_request = resolve_agent

    await wrapper._invoke_agent(session, "revenue", memory=SimpleNamespace())

    assert agent.ask.await_args.kwargs["tenant"] == "acme"
    assert not hasattr(agent, "tenant_id")


@pytest.mark.asyncio
async def test_skill_command_uses_contextvar_and_passes_tenant():
    """A file skill is request-local and never assigned to the shared agent."""
    _wrapper_class()
    from parrot.skills.tenancy import current_active_skill, set_active_skill

    skill = SimpleNamespace(name="revenue", body="instructions")
    agent = SimpleNamespace(ask=AsyncMock(return_value="ok"))
    wrapper = _wrapper(TelegramAgentConfig(name="finance", chatbot_id="finance", tenant="acme"), agent)
    message = SimpleNamespace(chat=SimpleNamespace(id=4), text="/skill revenue", answer=AsyncMock())
    wrapper._is_authorized = lambda chat_id: True
    wrapper._check_authentication = AsyncMock(return_value=True)
    wrapper._list_agent_skills = lambda: [{"name": "revenue"}]
    wrapper._resolve_skill_definition = AsyncMock(return_value=skill)
    wrapper._typing_indicator = AsyncMock()
    wrapper._parse_response = lambda response: response
    wrapper._send_parsed_response = AsyncMock()

    try:
        await wrapper.handle_skill(message)
        assert current_active_skill() is skill
        assert agent.ask.await_args.kwargs["tenant"] == "acme"
        assert "_active_skill" not in agent.__dict__
    finally:
        set_active_skill(None)


@pytest.mark.asyncio
async def test_skill_listing_and_resolution_use_tenant_view_with_legacy_fallback():
    """Tenant views are preferred, while legacy agents continue using their registry."""
    skill = SimpleNamespace(name="revenue", description="Tenant revenue", triggers=["/revenue"])
    view = SimpleNamespace(list_skills=lambda: [skill], get_by_name=lambda name: skill, get=lambda trigger: None)
    tenant_agent = SimpleNamespace(current_skill_view=lambda tenant: view, _skill_registry=None)
    wrapper = _wrapper(TelegramAgentConfig(name="finance", chatbot_id="finance", tenant="acme"), tenant_agent)

    assert wrapper._list_agent_skills() == [
        {"name": "revenue", "description": "Tenant revenue", "triggers": ["/revenue"], "source": "file"}
    ]
    assert await wrapper._resolve_skill_definition("revenue") is skill

    legacy_skill = SimpleNamespace(name="global", description="Global", triggers=[])
    legacy_registry = SimpleNamespace(list_skills=lambda: [legacy_skill])
    legacy_agent = SimpleNamespace(_skill_file_registry=legacy_registry, _skill_registry=None)
    legacy_wrapper = _wrapper(TelegramAgentConfig(name="finance", chatbot_id="finance"), legacy_agent)

    assert legacy_wrapper._list_agent_skills()[0]["name"] == "global"


@pytest.mark.asyncio
async def test_invalid_tenant_view_returns_empty_results_without_agent_mutation():
    """Invalid tenant views fail closed and do not write a tenant to the agent."""
    agent = SimpleNamespace(
        current_skill_view=lambda tenant: (_ for _ in ()).throw(ValueError("invalid tenant")),
        _skill_registry=None,
    )
    wrapper = _wrapper(TelegramAgentConfig(name="finance", chatbot_id="finance", tenant="../bad"), agent)

    assert wrapper._list_agent_skills() == []
    assert await wrapper._resolve_skill_definition("revenue") is None
    assert "tenant_id" not in agent.__dict__
    assert "_tenant_id" not in agent.__dict__
