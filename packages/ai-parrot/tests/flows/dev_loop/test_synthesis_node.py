"""Unit tests for parrot.flows.dev_loop.nodes.synthesis (TASK-1922)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.dispatchers import DispatchExecutionError
from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput, SynthesisReport
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


def _development_out(**overrides) -> DevelopmentOutput:
    kwargs = {
        "files_changed": ["a.py", "b.py"],
        "commit_shas": ["abc123"],
        "summary": "implemented tasks",
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
        "development_output": _development_out(worker_summaries=[]),
        "run_id": "r1",
    }

    await node.execute(shared)

    assert shared["synthesis_report"] == report
