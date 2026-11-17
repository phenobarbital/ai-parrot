"""Tests for per-tier expert LLM defaults, credentials, and usage tags (FEAT-796)."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
from navconfig import config

from parrot import conf
from parrot.bots.agent import Agent
from parrot.experts.agent import ExpertAgent
from parrot.experts.models import ExpertTier
from parrot.experts.policy import DEFAULT_TIER_POLICY, model_config_for
from parrot.models.basic import ModelConfig
from parrot.observability.context import current_component

_BUILTIN_POLICY = {
    ExpertTier.JUDGMENT: {"provider": "google", "model": "gemini-4-argon", "temperature": 0.2},
    ExpertTier.BALANCED: {"provider": "google", "model": "gemini-3.8-flash", "temperature": 0.1},
    ExpertTier.TEMPLATED: {"provider": "google", "model": "gemini-3.8-flash", "temperature": 0.0},
}


def _set_llm_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    """Make component resolution read from ``values`` without touching the process environment."""
    monkeypatch.setattr(config, "get", lambda name, *args, **kwargs: values.get(name, kwargs.get("fallback")))
    monkeypatch.setattr(conf, "DEFAULT_LLM", None)


def _bundle(tier: ExpertTier) -> SimpleNamespace:
    """Return the minimal bundle shape consumed by ``ExpertAgent.__init__``."""
    return SimpleNamespace(
        manifest=SimpleNamespace(name=f"{tier.value}-expert", tier=tier),
        identity_dir=None,
    )


def test_tier_policy_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """An EXPERT_BALANCED_LLM override changes only the BALANCED tier."""
    _set_llm_env(monkeypatch, {"EXPERT_BALANCED_LLM": "openai:gpt-tier"})

    balanced = model_config_for(ExpertTier.BALANCED)
    judgment = model_config_for(ExpertTier.JUDGMENT)

    assert (balanced.provider, balanced.model, balanced.temperature) == ("openai", "gpt-tier", 0.1)
    assert (judgment.provider, judgment.model, judgment.temperature) == ("google", "gemini-4-argon", 0.2)


def test_default_tier_policy_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset component settings preserve every builtin and the exported policy mapping."""
    expected = deepcopy(_BUILTIN_POLICY)
    _set_llm_env(monkeypatch, {})

    assert DEFAULT_TIER_POLICY == expected
    for tier, values in expected.items():
        configured = model_config_for(tier)
        assert (configured.provider, configured.model, configured.temperature) == (
            values["provider"],
            values["model"],
            values["temperature"],
        )
    assert DEFAULT_TIER_POLICY == expected


def test_registry_style_override_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller overrides retain precedence over the per-tier environment default."""
    _set_llm_env(monkeypatch, {"EXPERT_BALANCED_LLM": "openai:gpt-tier"})

    configured = model_config_for(
        ExpertTier.BALANCED,
        overrides={"provider": "anthropic", "model": "claude-override"},
    )

    assert (configured.provider, configured.model) == ("anthropic", "claude-override")


def test_expert_agent_api_key_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a tier-qualified key reaches that tier's client kwargs; the shared key is ignored."""
    _set_llm_env(
        monkeypatch,
        {
            "EXPERT_BALANCED_GOOGLE_API_KEY": "balanced-key",
            "EXPERT_GOOGLE_API_KEY": "shared-key-must-be-ignored",
        },
    )
    captured: list[dict[str, Any]] = []

    def fake_agent_init(self: Agent, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(Agent, "__init__", fake_agent_init)
    model_config = ModelConfig(provider="google", model="gemini-3.8-flash")

    ExpertAgent(
        _bundle(ExpertTier.BALANCED),
        resolver=SimpleNamespace(),
        model_config=model_config,
        toolkits=[],
        allowed_tools=[],
    )
    ExpertAgent(
        _bundle(ExpertTier.JUDGMENT),
        resolver=SimpleNamespace(),
        model_config=model_config,
        toolkits=[],
        allowed_tools=[],
    )

    assert captured[0]["llm_kwargs"]["api_key"] == "balanced-key"
    assert "api_key" not in captured[1]
    assert "api_key" not in captured[1].get("llm_kwargs", {})


def test_explicit_expert_api_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit caller credential is not replaced by the tier default."""
    _set_llm_env(monkeypatch, {"EXPERT_BALANCED_GOOGLE_API_KEY": "balanced-key"})
    captured: dict[str, Any] = {}

    def fake_agent_init(self: Agent, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(Agent, "__init__", fake_agent_init)
    ExpertAgent(
        _bundle(ExpertTier.BALANCED),
        resolver=SimpleNamespace(),
        model_config=ModelConfig(provider="google", model="gemini-3.8-flash"),
        toolkits=[],
        allowed_tools=[],
        api_key="caller-key",
    )

    assert captured["llm_kwargs"]["api_key"] == "caller-key"


@pytest.mark.asyncio
async def test_expert_ask_tagged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier component is active during ``Agent.ask`` and restored afterward."""
    seen: list[str | None] = []

    async def fake_ask(self: Agent, *args: Any, **kwargs: Any) -> str:
        seen.append(current_component.get())
        return "answer"

    monkeypatch.setattr(Agent, "ask", fake_ask)
    expert = object.__new__(ExpertAgent)
    expert._usage_component = "EXPERT_TEMPLATED"

    assert current_component.get() is None
    assert await expert.ask("question") == "answer"
    assert seen == ["EXPERT_TEMPLATED"]
    assert current_component.get() is None


@pytest.mark.asyncio
async def test_expert_invoke_tagged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tier component is active during ``Agent.invoke`` and restored afterward."""
    seen: list[str | None] = []

    async def fake_invoke(self: Agent, *args: Any, **kwargs: Any) -> str:
        seen.append(current_component.get())
        return "answer"

    monkeypatch.setattr(Agent, "invoke", fake_invoke)
    expert = object.__new__(ExpertAgent)
    expert._usage_component = "EXPERT_JUDGMENT"

    assert await expert.invoke("question") == "answer"
    assert seen == ["EXPERT_JUDGMENT"]
    assert current_component.get() is None
