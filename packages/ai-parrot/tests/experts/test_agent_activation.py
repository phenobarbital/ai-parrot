"""Tests for ExpertAgent and activate_expert (FEAT-778 M3). No network, no LLM calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from parrot.experts.activation import activate_expert
from parrot.experts.agent import ExpertAgent
from parrot.experts.loader import parse_expert_bundle
from parrot.experts.models import KnowledgeContext, KnowledgeLayer, KnowledgeMode
from parrot.models.basic import ModelConfig
from parrot.observability.context import current_agent_name, current_run_id, current_seat
from parrot.tools.toolkit import AbstractToolkit


class _Toolkit(AbstractToolkit):
    """Toolkit with an allowed and a disallowed tool."""

    async def lookup_fact(self, topic: str) -> str:
        """Look up a fact about a topic."""
        return topic

    async def spawn_sub_agent(self, task: str) -> str:
        """Spawn a sub agent (must be filtered out)."""
        return task


class _FakeResolver:
    """Resolver returning a fixed context."""

    async def resolve(self, expert: Any, stage: Any, workspace: Any, *, model: Any, budget_tokens: Any = None):
        """Return one inline knowledge layer and one rules layer."""
        return KnowledgeContext(
            expert=expert.manifest.name,
            budget_tokens=1000,
            layers=[
                KnowledgeLayer(
                    layer="rules", source="r", mode=KnowledgeMode.INLINE, revision="1", content="ALWAYS cite sources"
                ),
                KnowledgeLayer(
                    layer="tier1_expert",
                    source="k",
                    mode=KnowledgeMode.INLINE,
                    revision="1",
                    content="Use primary sources.",
                ),
            ],
        )


def _make(expert_bundle: Path, allowed: list[str] | None = None) -> ExpertAgent:
    bundle = parse_expert_bundle(expert_bundle / "experts" / "sample-expert")
    return ExpertAgent(
        bundle,
        resolver=_FakeResolver(),  # type: ignore[arg-type]
        model_config=ModelConfig(provider="openai", model="gpt-4o-mini"),
        toolkits=[_Toolkit()],
        allowed_tools=["lookup_fact"] if allowed is None else allowed,
    )


def test_expert_agent_uses_bundle_identity_dir(expert_bundle: Path) -> None:
    agent = _make(expert_bundle)
    assert Path(agent.identity_dir) == expert_bundle / "experts" / "sample-expert" / "identity"
    assert agent.name == "sample-expert"


def test_allowlist_filters_tools(expert_bundle: Path) -> None:
    agent = _make(expert_bundle)
    names = set(agent.tool_manager.list_tools())
    assert "lookup_fact" in names
    assert "spawn_sub_agent" not in names


@pytest.mark.asyncio
async def test_configure_installs_expert_layers(expert_bundle: Path) -> None:
    agent = _make(expert_bundle)
    await agent.configure()
    assert agent.knowledge_context is not None
    builder = agent._prompt_builder
    assert builder.get("expert_rules") is not None or builder.get("expert_knowledge") is not None
    assert agent.knowledge_context.inline_text("rules") == "ALWAYS cite sources"
    assert agent._prompt_builder is not None


@pytest.mark.asyncio
async def test_activate_expert_attribution(expert_bundle: Path) -> None:
    agent = _make(expert_bundle)
    assert current_agent_name.get() is None
    async with activate_expert(agent, run_id="run-1", stage="design") as active:
        assert active is agent
        assert current_agent_name.get() == "sample-expert"
        assert current_seat.get() == "design.sample-expert"
        assert current_run_id.get() == "run-1"
        async with activate_expert(agent, run_id="run-2", stage="qa"):
            assert current_seat.get() == "qa.sample-expert"
        assert current_seat.get() == "design.sample-expert"
        assert current_run_id.get() == "run-1"
    assert current_agent_name.get() is None
    assert current_seat.get() is None
    assert current_run_id.get() is None


@pytest.mark.asyncio
async def test_concurrent_activations_isolated(expert_bundle: Path) -> None:
    first, second = _make(expert_bundle), _make(expert_bundle)

    async def _run(agent: ExpertAgent, stage: str) -> tuple[str | None, str | None]:
        async with activate_expert(agent, run_id=stage, stage=stage):
            await asyncio.sleep(0.01)
            return current_agent_name.get(), current_seat.get()

    r1, r2 = await asyncio.gather(_run(first, "a"), _run(second, "b"))
    assert r1 == ("sample-expert", "a.sample-expert")
    assert r2 == ("sample-expert", "b.sample-expert")
    assert first._prompt_builder is not second._prompt_builder


def test_persona_md_never_read(expert_bundle: Path) -> None:
    root = expert_bundle / "experts" / "sample-expert"
    (root / "persona.md").write_text("PERSONA_SENTINEL_XYZ\n", encoding="utf-8")
    agent = _make(expert_bundle)
    assert "PERSONA_SENTINEL_XYZ" not in repr(agent._prompt_builder.__dict__)


@pytest.mark.asyncio
async def test_configured_expert_excludes_spawn_tool(expert_bundle: Path) -> None:
    agent = _make(expert_bundle)
    await agent.configure()
    names = set(agent.tool_manager.list_tools())
    assert "spawn_sub_agent" not in names
    assert "lookup_fact" in names


@pytest.mark.asyncio
async def test_configure_removes_injected_spawn_tool(expert_bundle: Path) -> None:
    agent = _make(expert_bundle)
    spawn = next(tool for tool in _Toolkit().get_tools() if tool.name == "spawn_sub_agent")
    agent.tool_manager.add_tool(spawn)
    before = set(agent.tool_manager.list_tools())
    assert "spawn_sub_agent" in before
    await agent.configure()
    after = set(agent.tool_manager.list_tools())
    assert "spawn_sub_agent" not in after
    assert before - {"spawn_sub_agent"} <= after
    assert "read_omitted_content" in after
