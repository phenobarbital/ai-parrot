"""Unit tests for the dev-agent pool config & output models (FEAT-323 TASK-1857)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.models import (
    DevAgentPoolConfig,
    DevAgentSpec,
    DevelopmentOutput,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    TaskScopedBrief,
    WorkBrief,
    WorkerSummary,
)


class TestDevAgentSpec:
    def test_defaults(self):
        s = DevAgentSpec(agent="claude-code")
        assert s.model == "" and s.count == 1

    def test_count_ge_1(self):
        with pytest.raises(ValidationError):
            DevAgentSpec(agent="codex", count=0)

    def test_invalid_backend_rejected(self):
        with pytest.raises(ValidationError):
            DevAgentSpec(agent="not-a-backend")


class TestPoolConfig:
    def test_isolation_default_shared(self):
        c = DevAgentPoolConfig(agents=[DevAgentSpec(agent="zai")])
        assert c.isolation_mode == "shared"

    def test_agents_min_length(self):
        with pytest.raises(ValidationError):
            DevAgentPoolConfig(agents=[])

    def test_isolated_mode_explicit(self):
        c = DevAgentPoolConfig(
            agents=[DevAgentSpec(agent="claude-code")], isolation_mode="isolated"
        )
        assert c.isolation_mode == "isolated"


class TestWorkerSummary:
    def test_defaults(self):
        ws = WorkerSummary(worker_id="development.w1", agent="codex", model="gpt-5.5")
        assert ws.tasks_completed == []
        assert ws.tasks_failed == []
        assert ws.summary == ""


class TestTaskScopedBrief:
    def test_wraps_research_output(self):
        research = ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-323",
            branch_name="feat-323-x",
            worktree_path="/tmp/wt",
        )
        brief = TaskScopedBrief(research=research, task_id="TASK-1857")
        assert brief.task_id == "TASK-1857"
        assert brief.research.feat_id == "FEAT-323"


class TestBackCompat:
    def test_workbrief_without_pool_fields(self):
        """Payloads existentes (sin dev_agents) validan igual que hoy."""
        brief = WorkBrief(
            summary="x" * 20,
            affected_component="etl/customers/sync.yaml",
            log_sources=[LogSource(kind="cloudwatch", locator="/etl/x")],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ],
            escalation_assignee="557058:abc",
            reporter="557058:def",
        )
        assert brief.dev_agents is None
        assert brief.dev_isolation is None

    def test_workbrief_with_pool_fields(self):
        brief = WorkBrief(
            summary="x" * 20,
            affected_component="etl/customers/sync.yaml",
            log_sources=[],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ],
            escalation_assignee="557058:abc",
            reporter="557058:def",
            dev_agents=[DevAgentSpec(agent="codex"), DevAgentSpec(agent="claude-code")],
            dev_isolation="isolated",
        )
        assert len(brief.dev_agents) == 2
        assert brief.dev_isolation == "isolated"

    def test_development_output_old_payload(self):
        out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="x")
        assert out.incomplete_tasks == [] and out.worker_summaries == []

    def test_development_output_with_pool_fields(self):
        out = DevelopmentOutput(
            files_changed=["a.py"],
            commit_shas=["abc123"],
            summary="done",
            incomplete_tasks=["TASK-002"],
            worker_summaries=[
                WorkerSummary(
                    worker_id="development.w1",
                    agent="codex",
                    model="gpt-5.5",
                    tasks_completed=["TASK-001"],
                )
            ],
        )
        assert out.incomplete_tasks == ["TASK-002"]
        assert out.worker_summaries[0].worker_id == "development.w1"
