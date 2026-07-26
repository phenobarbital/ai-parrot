"""Unit tests for DevLoopGraphMemory (FEAT-377 TASK-1914).

Covers the opt-in facade's disabled-by-default contract, the
publish/revert round-trip against a real tmp-path SQLite plane,
degrade-never-fail on publish failure, and the grounding filter.
"""

from __future__ import annotations

from typing import Any, List
from unittest.mock import AsyncMock

import pytest

from parrot import conf
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.models import (
    CriterionResult,
    FlowtaskCriterion,
    QAReport,
    WorkBrief,
)


def _brief(**overrides) -> WorkBrief:
    defaults = dict(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="a",
        reporter="b",
    )
    defaults.update(overrides)
    return WorkBrief(**defaults)


def _passing_report(*names: str) -> QAReport:
    return QAReport(
        passed=True,
        criterion_results=[
            CriterionResult(
                name=n, kind="flowtask", exit_code=0, duration_seconds=1.0,
                stdout_tail="", stderr_tail="", passed=True,
            )
            for n in names
        ],
        lint_passed=True,
    )


@pytest.fixture
async def tmp_graph_memory(tmp_path, monkeypatch):
    """SQLitePersistence-backed DevLoopGraphMemory at tmp_path."""
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(tmp_path))
    mem = await DevLoopGraphMemory.from_config()
    assert mem is not None
    return mem


# ---------------------------------------------------------------------------
# Disabled-by-default contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_from_config_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", "")
    assert await DevLoopGraphMemory.from_config() is None


@pytest.mark.asyncio
async def test_from_config_whitespace_only_path_disabled(monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", "   ")
    assert await DevLoopGraphMemory.from_config() is None


@pytest.mark.asyncio
async def test_from_config_enabled_when_path_set(tmp_path, monkeypatch):
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(tmp_path))
    mem = await DevLoopGraphMemory.from_config()
    assert isinstance(mem, DevLoopGraphMemory)


# ---------------------------------------------------------------------------
# publish_run_outcome — commit + revert round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_run_outcome_commit_and_revert(tmp_graph_memory):
    report = _passing_report("customers-sync", "lint")
    receipt = await tmp_graph_memory.publish_run_outcome(
        "run-1", report, "closed", "fixed the customer sync bug"
    )

    assert receipt is not None
    # 1 RUN node + 1 CLAIM node per verified criterion.
    assert "run:run-1" in receipt.node_ids
    assert "claim:run-1:customers-sync" in receipt.node_ids
    assert "claim:run-1:lint" in receipt.node_ids

    edge_kinds_from_run = {
        (src, tgt, kind) for (src, tgt, kind) in receipt.edge_keys
        if src == "run:run-1"
    }
    assert ("run:run-1", "claim:run-1:customers-sync", "produced") in edge_kinds_from_run
    edge_kinds_to_run = {
        (src, tgt, kind) for (src, tgt, kind) in receipt.edge_keys
        if tgt == "run:run-1"
    }
    assert ("claim:run-1:customers-sync", "run:run-1", "about") in edge_kinds_to_run
    assert ("claim:run-1:customers-sync", "run:run-1", "supported_by") in edge_kinds_to_run

    # Revertable.
    revert_result = await tmp_graph_memory._publisher.revert_commit(receipt.commit_id)
    assert revert_result["status"] == "reverted"


@pytest.mark.asyncio
async def test_publish_run_outcome_only_verified_criteria_become_claims(tmp_graph_memory):
    """A failing criterion in the report does NOT get a CLAIM node."""
    report = QAReport(
        passed=False,
        criterion_results=[
            CriterionResult(
                name="passed-one", kind="flowtask", exit_code=0, duration_seconds=1.0,
                stdout_tail="", stderr_tail="", passed=True,
            ),
            CriterionResult(
                name="failed-one", kind="flowtask", exit_code=1, duration_seconds=1.0,
                stdout_tail="", stderr_tail="boom", passed=False,
            ),
        ],
        lint_passed=True,
    )
    receipt = await tmp_graph_memory.publish_run_outcome(
        "run-2", report, "escalated", "partial fix"
    )
    assert receipt is not None
    assert "claim:run-2:passed-one" in receipt.node_ids
    assert "claim:run-2:failed-one" not in receipt.node_ids


@pytest.mark.asyncio
async def test_publish_run_outcome_no_report_still_publishes_run_node(tmp_graph_memory):
    """A run that never reached QA (report=None) still records a RUN node."""
    receipt = await tmp_graph_memory.publish_run_outcome(
        "run-3", None, "escalated", "hard node error"
    )
    assert receipt is not None
    assert receipt.node_ids == ["run:run-3"]


# ---------------------------------------------------------------------------
# Degrade-never-fail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_failure_degrades_to_warning(tmp_graph_memory, caplog):
    class _BoomPublisher:
        async def publish(self, update: Any) -> Any:
            raise RuntimeError("store closed")

    tmp_graph_memory._publisher = _BoomPublisher()
    with caplog.at_level("WARNING"):
        result = await tmp_graph_memory.publish_run_outcome(
            "run-4", _passing_report("x"), "closed", "y"
        )
    assert result is None
    assert any("publish_run_outcome failed" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_build_research_context_failure_degrades_to_none(tmp_graph_memory, caplog):
    class _BoomBuilder:
        async def build(self, task: str, config: Any) -> Any:
            raise RuntimeError("retriever exploded")

    tmp_graph_memory._context_builder = _BoomBuilder()
    with caplog.at_level("WARNING"):
        result = await tmp_graph_memory.build_research_context(_brief())
    assert result is None


@pytest.mark.asyncio
async def test_build_research_context_empty_graph_returns_none(tmp_graph_memory):
    """A freshly-created (empty) graph plane has nothing to contextualize."""
    result = await tmp_graph_memory.build_research_context(_brief())
    assert result is None


# ---------------------------------------------------------------------------
# ground_findings
# ---------------------------------------------------------------------------


class _StubGroundingResult:
    def __init__(self, decision: str) -> None:
        self.decision = decision


@pytest.mark.asyncio
async def test_ground_findings_keeps_grounded_drops_revise(tmp_graph_memory):
    async def _ground_claim(claim: str):
        return _StubGroundingResult("grounded" if "good" in claim else "revise")

    tmp_graph_memory._grounding_evaluator.ground_claim = AsyncMock(side_effect=_ground_claim)

    kept = await tmp_graph_memory.ground_findings(["this is good", "this needs revise"])

    assert kept == ["this is good"]


@pytest.mark.asyncio
async def test_ground_findings_keeps_finding_on_evaluator_error(tmp_graph_memory, caplog):
    """An evaluation error KEEPS the finding (fail toward retaining signal)."""
    tmp_graph_memory._grounding_evaluator.ground_claim = AsyncMock(
        side_effect=RuntimeError("evaluator down")
    )
    with caplog.at_level("WARNING"):
        kept: List[str] = await tmp_graph_memory.ground_findings(["some finding"])
    assert kept == ["some finding"]


@pytest.mark.asyncio
async def test_ground_findings_empty_list_returns_empty(tmp_graph_memory):
    assert await tmp_graph_memory.ground_findings([]) == []
