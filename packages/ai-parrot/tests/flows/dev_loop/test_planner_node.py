"""Unit tests for parrot.flows.dev_loop.nodes.planner (TASK-1921)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    FeatureBrief,
    PlannerOutput,
)
from parrot.flows.dev_loop.nodes.planner import PlannerNode

_SDD_PLANNER_PROMPT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "parrot"
    / "flows"
    / "dev_loop"
    / "_subagent_data"
    / "sdd-planner.md"
)


def _write_index(tmp_path: Path, slug: str, tasks: list[dict]) -> Path:
    index_dir = tmp_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    path = index_dir / f"{slug}.json"
    path.write_text(json.dumps({"feature": slug, "tasks": tasks}))
    return path


def _brief(tmp_path: Path, **overrides) -> FeatureBrief:
    doc = tmp_path / "x.proposal.md"
    doc.write_text("# proposal")
    kwargs = {
        "document_path": str(doc),
        "document_kind": "proposal",
    }
    kwargs.update(overrides)
    return FeatureBrief(**kwargs)


def _planner_output(tmp_path: Path, slug: str, **overrides) -> PlannerOutput:
    worktree = tmp_path
    kwargs = {
        "spec_path": f"sdd/specs/{slug}.spec.md",
        "task_index_path": str(worktree / "sdd" / "tasks" / "index" / f"{slug}.json"),
        "feat_id": "FEAT-999",
        "branch_name": f"feat-999-{slug}",
        "worktree_path": str(worktree),
    }
    kwargs.update(overrides)
    return PlannerOutput(**kwargs)


def _node(dispatcher, *, development_pool_max: int = 4) -> PlannerNode:
    return PlannerNode(dispatcher=dispatcher, development_pool_max=development_pool_max)


async def test_planner_happy_path_proposal(tmp_path, monkeypatch):
    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))
    slug = "my-feature"
    planner_out = _planner_output(tmp_path, slug)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=planner_out)

    node = _node(dispatcher)
    shared = {"feature_brief": _brief(tmp_path), "run_id": "r1"}

    result = await node.execute(shared)

    assert isinstance(result, PlannerOutput)
    assert result.feat_id == "FEAT-999"
    assert shared["planner_output"] is result
    dispatcher.dispatch.assert_awaited_once()
    _, kwargs = dispatcher.dispatch.call_args
    assert kwargs["profile"].subagent == "sdd-planner"


async def test_planner_spec_passthrough_skips_sdd_spec():
    """The static prompt must instruct the subagent to skip /sdd-spec
    when document_kind is already 'spec'."""
    text = _SDD_PLANNER_PROMPT.read_text()
    assert "document_kind" in text
    assert "/sdd-spec" in text
    assert "skip" in text.lower()


async def test_planner_no_jira_calls(tmp_path, monkeypatch):
    """PlannerNode structurally cannot call a Jira toolkit — it never
    accepts one as a dependency."""
    sig = inspect.signature(PlannerNode.__init__)
    assert "jira_toolkit" not in sig.parameters

    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))
    slug = "my-feature"
    planner_out = _planner_output(tmp_path, slug)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=planner_out)
    node = _node(dispatcher)
    assert not hasattr(node, "_jira")

    shared = {"feature_brief": _brief(tmp_path), "run_id": "r1"}
    await node.execute(shared)
    # Nothing on the node exposes a Jira-capable attribute.
    assert not any("jira" in attr.lower() for attr in vars(node) if attr != "node_id")


def test_pool_sizing_brief_override(tmp_path):
    dispatcher = MagicMock()
    node = _node(dispatcher)
    brief = _brief(
        tmp_path,
        dev_agents=[DevAgentSpec(agent="codex", model="gpt-5.5", count=2)],
    )
    planner_out = _planner_output(tmp_path, "irrelevant")

    import asyncio

    pool = asyncio.run(node._resolve_pool(brief, planner_out))
    assert isinstance(pool, DevAgentPoolConfig)
    assert len(pool.agents) == 1
    assert pool.agents[0].agent == "codex"
    assert pool.agents[0].count == 2


def test_pool_sizing_wave_width_capped(tmp_path):
    slug = "wide-feature"
    _write_index(
        tmp_path,
        slug,
        [
            {"id": "TASK-1", "status": "pending", "depends_on": []},
            {"id": "TASK-2", "status": "pending", "depends_on": []},
            {"id": "TASK-3", "status": "pending", "depends_on": []},
        ],
    )
    dispatcher = MagicMock()
    node = _node(dispatcher, development_pool_max=2)
    brief = _brief(tmp_path)
    planner_out = _planner_output(tmp_path, slug)

    import asyncio

    pool = asyncio.run(node._resolve_pool(brief, planner_out))
    assert len(pool.agents) == 1
    assert pool.agents[0].agent == "claude-code"
    assert pool.agents[0].count == 2  # wave width 3, capped at 2


def test_pool_sizing_single_task(tmp_path):
    slug = "single-task-feature"
    _write_index(
        tmp_path,
        slug,
        [{"id": "TASK-1", "status": "pending", "depends_on": []}],
    )
    dispatcher = MagicMock()
    node = _node(dispatcher, development_pool_max=4)
    brief = _brief(tmp_path)
    planner_out = _planner_output(tmp_path, slug)

    import asyncio

    pool = asyncio.run(node._resolve_pool(brief, planner_out))
    assert len(pool.agents) == 1
    assert pool.agents[0].count == 1


async def test_cycle_fails_before_dev_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))
    slug = "cyclic-feature"
    _write_index(
        tmp_path,
        slug,
        [
            {"id": "TASK-1", "status": "pending", "depends_on": ["TASK-2"]},
            {"id": "TASK-2", "status": "pending", "depends_on": ["TASK-1"]},
        ],
    )
    planner_out = _planner_output(tmp_path, slug)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=planner_out)
    node = _node(dispatcher)
    shared = {"feature_brief": _brief(tmp_path), "run_id": "r1"}

    with pytest.raises(ValueError, match="Cycle"):
        await node.execute(shared)


async def test_graph_memory_absent_degrades(tmp_path, monkeypatch):
    """DevLoopGraphMemory does not exist (FEAT-377/B not merged) — the
    node must still work, dispatching with an empty graph_context."""
    monkeypatch.setattr(conf, "WORKTREE_BASE_PATH", str(tmp_path))
    slug = "my-feature"
    planner_out = _planner_output(tmp_path, slug)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=planner_out)
    node = _node(dispatcher)
    shared = {"feature_brief": _brief(tmp_path), "run_id": "r1"}

    result = await node.execute(shared)

    assert isinstance(result, PlannerOutput)
    _, kwargs = dispatcher.dispatch.call_args
    assert kwargs["brief"].graph_context == ""
