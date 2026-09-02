"""Unit tests for parrot.flows.dev_loop.nodes.synthesis (TASK-1922)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.dispatchers import DispatchExecutionError
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    ResearchOutput,
    SynthesisReport,
    WorkerSummary,
)
from parrot.flows.dev_loop.nodes.synthesis import SynthesisNode


def _research_out(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path=str(tmp_path),
        log_excerpts=[],
    )


def _worker(worker_id: str) -> WorkerSummary:
    return WorkerSummary(worker_id=worker_id, agent="claude-code", model="sonnet")


def _development_out(**overrides) -> DevelopmentOutput:
    """A merged multi-worker development output.

    Defaults to the shape SynthesisNode exists for — two workers whose
    sub-worktrees were actually merged — so every legacy case here keeps
    exercising the dispatch path. The skip path (single worker, or no
    merge at all) has its own tests below.
    """
    kwargs = {
        "files_changed": ["a.py", "b.py"],
        "commit_shas": ["abc123"],
        "summary": "implemented tasks",
        "worker_summaries": [_worker("development.w1"), _worker("development.w2")],
        "merge_performed": True,
    }
    kwargs.update(overrides)
    return DevelopmentOutput(**kwargs)


def _node(dispatcher) -> SynthesisNode:
    return SynthesisNode(dispatcher=dispatcher)


async def test_synthesis_happy_path(tmp_path):
    report = SynthesisReport(consistent=True, adjustments=["fixed import"], summary="all good")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=report)
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(),
        "run_id": "r1",
    }

    result = await node.execute(shared)

    assert result is report
    assert shared["synthesis_report"] is report
    dispatcher.dispatch.assert_awaited_once()
    _, kwargs = dispatcher.dispatch.call_args
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["profile"].subagent is None
    assert kwargs["profile"].system_prompt_override


async def test_synthesis_inconsistent_raises(tmp_path):
    report = SynthesisReport(consistent=False, adjustments=[], summary="pytest still failing")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=report)
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(),
        "run_id": "r1",
    }

    with pytest.raises(RuntimeError, match="inconsistent"):
        await node.execute(shared)

    # Report is still published even though the node raises, so downstream
    # failure handling has the diagnostic detail.
    assert shared["synthesis_report"] is report


async def test_synthesis_dispatch_failure_raises(tmp_path):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=DispatchExecutionError("boom"))
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(),
        "run_id": "r1",
    }

    with pytest.raises(DispatchExecutionError):
        await node.execute(shared)

    assert "synthesis_report" not in shared


async def test_report_published_to_shared_state(tmp_path):
    report = SynthesisReport(consistent=True, adjustments=[], summary="clean")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=report)
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(),
        "run_id": "r1",
    }

    await node.execute(shared)

    assert shared["synthesis_report"] == report


# ──────────────────────────────────────────────────────────────────────
# Skip guard — no merge happened, so there is nothing to reconcile
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "overrides",
    [
        # Single-agent dispatch: one worker summary, no sub-worktrees.
        {"worker_summaries": [_worker("development.single")], "merge_performed": False},
        # Legacy/agent-emitted payload: no worker summaries at all.
        {"worker_summaries": [], "merge_performed": False},
        # Pool collapsed to one seat, isolated mode — a merge ran, but a
        # single worker has no one to be inconsistent with.
        {"worker_summaries": [_worker("development.w1")], "merge_performed": True},
        # Several workers but shared isolation: nothing was ever merged.
        {
            "worker_summaries": [_worker("development.w1"), _worker("development.w2")],
            "merge_performed": False,
        },
    ],
    ids=["single-agent", "no-workers", "collapsed-pool", "shared-isolation"],
)
async def test_synthesis_skipped_without_a_merge(tmp_path, overrides):
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(**overrides),
        "run_id": "r1",
    }

    result = await node.execute(shared)

    dispatcher.dispatch.assert_not_awaited()
    assert result.consistent is True
    assert result.adjustments == []
    assert "skipped" in result.summary.lower()
    assert shared["synthesis_report"] is result


async def test_skip_warns_when_qa_is_also_bypassed(tmp_path, caplog):
    """Skipping synthesis under skip_qa leaves the run with no tests at all."""
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(merge_performed=False),
        "run_id": "r1",
        "skip_qa": True,
    }

    with caplog.at_level("WARNING"):
        await node.execute(shared)

    assert any("no test suite" in r.message for r in caplog.records)


async def test_merged_pool_still_dispatches_with_truthful_brief(tmp_path):
    report = SynthesisReport(consistent=True, adjustments=[], summary="clean")
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=report)
    node = _node(dispatcher)
    shared = {
        "research_output": _research_out(tmp_path),
        "development_output": _development_out(),
        "run_id": "r1",
    }

    await node.execute(shared)

    _, kwargs = dispatcher.dispatch.call_args
    brief = kwargs["brief"]
    # The prompt asserts "multiple workers ... already merged"; the brief
    # must not contradict it.
    assert brief.worker_count == 2
    assert brief.merge_performed is True
    # Cost guard (D) — the reconciliation dispatch is turn-capped.
    assert kwargs["profile"].max_turns == 30
