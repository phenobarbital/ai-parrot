"""Behavioral regressions for agent memory configuration contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.memory.agent_memory.factory import _manager_config, _warn_unsupported_knobs, create_memory_manager
from parrot.memory.agent_memory.mixin import AgentMemoryMixin
from parrot.memory.agent_memory.models import AgentMemoryConfig, MemoryRequestScope
from parrot.memory.agent_memory.toolkit import AgentMemoryToolkit
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.context import ContextAssembler
from parrot.memory.unified.models import MemoryCandidate


@pytest.fixture
def scope() -> MemoryRequestScope:
    """Provide trusted identity for actual context preparation."""
    return MemoryRequestScope(
        tenant_id="tenant", agent_id="agent", user_id="user", turn_id="first", identity_provenance="runtime_derived"
    )


@pytest.mark.parametrize(
    ("field", "section"),
    [
        ("episodic_context_tokens", "episodic"),
        ("user_context_tokens", "user_knowledge"),
        ("brain_context_tokens", "brain"),
        ("skills_context_tokens", "skills"),
    ],
)
def test_each_section_allocation_changes_its_budget(field: str, section: str) -> None:
    """Each allocation controls its share independently of the other enabled lanes."""
    allocations = dict.fromkeys(
        ("episodic_context_tokens", "user_context_tokens", "brain_context_tokens", "skills_context_tokens"), 100
    )
    allocations[field] = 300
    config = _manager_config(
        AgentMemoryConfig(
            enable_episodic_memory=True,
            enable_user_memory=True,
            enable_brain=True,
            include_relevant_skills=True,
            **allocations,
        )
    )
    assert config.normalized_section_weights[section] == pytest.approx(0.5)
    assert sum(config.normalized_section_weights.values()) == pytest.approx(1.0)


def test_all_zero_allocations_deliver_no_content(scope: MemoryRequestScope) -> None:
    """An explicit empty allocation must not resurrect the manager's default weights."""
    config = _manager_config(
        AgentMemoryConfig(
            enable_episodic_memory=True,
            include_relevant_skills=True,
            enable_brain=True,
            enable_user_memory=True,
            episodic_context_tokens=0,
            user_context_tokens=0,
            brain_context_tokens=0,
            skills_context_tokens=0,
        )
    )
    candidates = [
        MemoryCandidate(
            scope=scope, memory_id=kind, content_version="1", source=kind, text="Useful memory", candidate_type=kind
        )
        for kind in ("episodic", "user", "brain", "skill")
    ]
    context = ContextAssembler(config).assemble_candidates(candidates, scope=scope)
    assert config.normalized_section_weights == {}
    assert context.to_prompt_string() == ""
    assert context.tokens_used == 0
    assert context.delivered_refs == ()


@pytest.mark.parametrize("priority", ["high", "normal"])
def test_limits_and_user_priority_reach_the_manager(priority: str) -> None:
    """Keep all existing limit and priority consumers wired during factory changes."""
    config = _manager_config(
        AgentMemoryConfig(
            max_context_tokens=1234,
            max_episodic_warnings=7,
            max_episodic_recall=8,
            max_user_records=9,
            user_context_tokens=321,
            user_memory_priority=priority,
        )
    )
    assert (config.max_context_tokens, config.episodic_max_warnings, config.episodic_max_recall) == (1234, 7, 8)
    assert (config.user_max_records, config.user_context_tokens, config.user_priority) == (9, 321, priority)


@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_factory_injects_skills_only_when_enabled(
    tmp_path: Path, scope: MemoryRequestScope, persistent: bool, enabled: bool
) -> None:
    """Both factory paths can deliver real skill context while respecting the capability flag."""
    registry = SimpleNamespace(get_relevant_skills=AsyncMock(return_value="Use the schema inspection tool"))
    manager = await create_memory_manager(
        AgentMemoryConfig(
            include_relevant_skills=enabled,
            enable_user_memory=persistent,
            storage_path=str(tmp_path / "memory.db") if persistent else None,
        ),
        namespace=MemoryNamespace(tenant_id=scope.tenant_id, agent_id=scope.agent_id),
        skill_registry=registry,
    )
    try:
        context = await manager.prepare_context("schema", scope=scope)
        assert context.relevant_skills == ("Use the schema inspection tool" if enabled else "")
        assert manager.skills is (registry if enabled else None)
        assert registry.get_relevant_skills.await_count == int(enabled)
    finally:
        await manager.cleanup()


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("available", [False, True])
@pytest.mark.asyncio
async def test_first_prepare_binds_available_host_skills(
    scope: MemoryRequestScope, enabled: bool, available: bool
) -> None:
    """First-turn preparation can recall skills without a preceding completion event."""
    registry = SimpleNamespace(get_relevant_skills=AsyncMock(return_value="Inspect the schema first"))
    manager = await create_memory_manager(
        AgentMemoryConfig(include_relevant_skills=enabled),
        namespace=MemoryNamespace(tenant_id=scope.tenant_id, agent_id=scope.agent_id),
    )
    host = AgentMemoryMixin()
    host._memory_manager = manager
    if available:
        host._skill_registry = registry
    try:
        context = await host.prepare_memory("schema", scope=scope)
        assert context.relevant_skills == ("Inspect the schema first" if enabled and available else "")
        assert registry.get_relevant_skills.await_count == int(enabled and available)
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
async def test_first_prepare_preserves_an_explicit_registry(scope: MemoryRequestScope) -> None:
    """Host binding must not replace an explicitly configured manager registry."""
    explicit = SimpleNamespace(get_relevant_skills=AsyncMock(return_value="Explicit skill"))
    host_registry = SimpleNamespace(get_relevant_skills=AsyncMock(return_value="Host skill"))
    manager = await create_memory_manager(
        AgentMemoryConfig(include_relevant_skills=True),
        namespace=MemoryNamespace(tenant_id=scope.tenant_id, agent_id=scope.agent_id),
        skill_registry=explicit,
    )
    host = AgentMemoryMixin()
    host._memory_manager = manager
    host._skill_registry = host_registry
    try:
        assert (await host.prepare_memory("query", scope=scope)).relevant_skills == "Explicit skill"
        host_registry.get_relevant_skills.assert_not_awaited()
    finally:
        await manager.cleanup()


@pytest.mark.parametrize(
    ("field", "value"), [("enable_reflection", False), ("suppress_trivial_tools", False), ("flush_on_startup", True)]
)
def test_each_unsupported_setting_warns_and_is_documented(
    field: str, value: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Accepted compatibility settings are explicitly documented and non-default values warn."""
    with caplog.at_level("WARNING", logger="parrot.memory.agent_memory.factory"):
        _warn_unsupported_knobs(AgentMemoryConfig(**{field: value}))
    assert field in caplog.text and "no effect" in caplog.text
    assert "unsupported" in AgentMemoryConfig.model_fields[field].description.lower()


def test_compatibility_defaults_do_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    """Default configurations remain accepted without repetitive compatibility warnings."""
    _warn_unsupported_knobs(AgentMemoryConfig())
    assert not caplog.records


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_dynamics_controls_the_explicit_review_gate(enabled: bool) -> None:
    """Dynamics enables operator review validation, not a new manager/store behavior switch."""
    toolkit = AgentMemoryToolkit(
        config={"memory_dynamics": enabled}, namespace={"tenant_id": "tenant", "agent_id": "agent"}
    )
    toolkit._opened_manager = AsyncMock(return_value=SimpleNamespace(episodic=SimpleNamespace(review=AsyncMock())))
    with pytest.raises(ValueError) as error:
        await toolkit.memory_review(["episode"], {}, "exposure")
    if enabled:
        assert "memory dynamics is not enabled" not in str(error.value)
        assert "ReviewSignal" in str(error.value)
    else:
        assert str(error.value) == "memory dynamics is not enabled"
