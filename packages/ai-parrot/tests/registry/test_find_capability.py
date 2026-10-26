"""Tests for AgentRegistry Roost advertisements and capability lookup."""

from __future__ import annotations

from pathlib import Path
from typing import Type

import pytest

from parrot.bots.abstract import AbstractBot
from parrot.registry import AgentRegistry, BotConfig
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig


@pytest.fixture
def registry(tmp_path: Path) -> AgentRegistry:
    """Build an isolated agent registry."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


@pytest.fixture
def dummy_bot_cls() -> Type[AbstractBot]:
    """Return a minimal concrete bot class for registration tests."""

    class DummyBot(AbstractBot):
        """Minimal bot used only for registration."""

    return DummyBot


def _hr_cfg() -> RoostAgentConfig:
    """Build the deterministic HR capability advert used by the tests."""
    return RoostAgentConfig(
        capabilities=["hr.people.salary"],
        categories=["hr.people"],
        keywords=["salary"],
        category_hashes={"hr.people": "abc123"},
        backing="deterministic",
    )


def test_roost_not_swallowed_into_startup_config(
    registry: AgentRegistry,
    dummy_bot_cls: Type[AbstractBot],
) -> None:
    """The named roost argument belongs on metadata, not startup kwargs."""
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())

    metadata = registry.get_metadata("hr")

    assert metadata is not None
    assert metadata.roost is not None
    assert "roost" not in metadata.startup_config


def test_decorator_accepts_roost_without_swallowing(registry: AgentRegistry) -> None:
    """The decorator path forwards its named roost advert to registration."""

    @registry.register_bot_decorator(name="hr", roost=_hr_cfg())
    class DecoratedBot(AbstractBot):
        """Minimal decorated bot."""

    metadata = registry.get_metadata("hr")

    assert metadata is not None
    assert metadata.factory is DecoratedBot
    assert metadata.roost == _hr_cfg()
    assert metadata.bot_config.roost == _hr_cfg()
    assert "roost" not in metadata.startup_config


def test_bot_config_roost_is_used_as_fallback(
    registry: AgentRegistry,
    dummy_bot_cls: Type[AbstractBot],
) -> None:
    """A declarative BotConfig advert is retained when no explicit advert is passed."""
    bot_config = BotConfig(name="hr", class_name="DummyBot", module=__name__, roost=_hr_cfg())

    registry.register("hr", dummy_bot_cls, bot_config=bot_config)

    metadata = registry.get_metadata("hr")
    assert metadata is not None
    assert metadata.roost == _hr_cfg()


def test_find_capability_ranked(
    registry: AgentRegistry,
    dummy_bot_cls: Type[AbstractBot],
) -> None:
    """Exact keyword lookup returns the mirrored advert and category hash."""
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())

    (match,) = registry.find_capability("salary")

    assert match.agent_name == "hr"
    assert match.category_hash == "abc123"


def test_find_capability_ranks_before_applying_limit(
    registry: AgentRegistry,
    dummy_bot_cls: Type[AbstractBot],
) -> None:
    """Cost ranking considers every exact match before truncating results."""
    registry.register("a-expensive", dummy_bot_cls, roost=_hr_cfg().model_copy(update={"cost": 5.0}))
    registry.register("z-cheap", dummy_bot_cls, roost=_hr_cfg().model_copy(update={"cost": 1.0}))

    (match,) = registry.find_capability("salary", limit=1)

    assert match.agent_name == "z-cheap"


def test_grant_filter_fail_closed(
    registry: AgentRegistry,
    dummy_bot_cls: Type[AbstractBot],
) -> None:
    """Caller lookup denies missing grants and accepts matching glob scopes."""
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())
    registry.register("a", dummy_bot_cls, roost=RoostAgentConfig())
    registry.register("b", dummy_bot_cls, roost=RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"])))

    assert registry.find_capability("salary", caller="a") == []
    assert registry.find_capability("salary", caller="missing") == []
    assert len(registry.find_capability("salary", caller="b")) == 1


def test_replace_refreshes_capability_index(
    registry: AgentRegistry,
    dummy_bot_cls: Type[AbstractBot],
) -> None:
    """Replacing an advert removes its stale capability entries."""
    registry.register("hr", dummy_bot_cls, roost=_hr_cfg())
    registry.register(
        "hr",
        dummy_bot_cls,
        replace=True,
        roost=RoostAgentConfig(capabilities=["hr.people.benefits"], keywords=["benefits"]),
    )

    assert registry.find_capability("salary") == []
    (match,) = registry.find_capability("benefits")
    assert match.cap_id == "hr.people.benefits"
