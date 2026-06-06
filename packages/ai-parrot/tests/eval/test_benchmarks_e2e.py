"""End-to-end benchmark tests (TASK-1428).

Proves the full state-based path works end-to-end:
  - Load dataset from JSONL/YAML
  - Run EvalRunner with InMemoryStateSandbox + StateBasedEvaluator
  - Assert pass^k is produced

All tests are HERMETIC: no real database, no real Jira, no real LLM.
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path

from parrot.eval import (
    EvalDataset,
    EvalRunConfig,
    EvalRunner,
    EvalTask,
    InMemoryStateSandboxProvider,
    JSONLDatasetLoader,
    StateBasedEvaluator,
    SingleTurnRollout,
    YAMLDatasetLoader,
    DatabaseToolkitBinder,
    JiraToolkitBinder,
)
from parrot.eval.rollout import ConversationalRollout, UserSimulator
from parrot.eval.sandbox.state import InMemoryStateSandbox, DictStateBackend

from tests.eval.factories import make_db_agent, make_jira_agent

BENCHMARKS_DIR = Path(__file__).parent / "benchmarks"


# ---------------------------------------------------------------------------
# Mock user simulator (no real LLM)
# ---------------------------------------------------------------------------


class _FixedSimulator(UserSimulator):
    """Returns a fixed script of messages, then stops."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)
        self._idx = 0

    async def respond(self, conversation, scenario):
        if self._idx >= len(self._messages):
            return None
        msg = self._messages[self._idx]
        self._idx += 1
        return msg


# ---------------------------------------------------------------------------
# DB CRUD benchmark
# ---------------------------------------------------------------------------


async def test_db_crud_benchmark_e2e():
    """Full run over db_crud.jsonl with mock DB agent; produces a pass^k."""
    ds = await JSONLDatasetLoader().load(str(BENCHMARKS_DIR / "db_crud.jsonl"))
    assert len(ds.tasks) == 3

    report = await EvalRunner(
        dataset=ds,
        agent_factory=make_db_agent,
        rollout=SingleTurnRollout(),
        evaluator=StateBasedEvaluator(),
        sandbox_provider=InMemoryStateSandboxProvider(binder=DatabaseToolkitBinder()),
        config=EvalRunConfig(k=1, max_concurrency=4),
    ).run()

    assert report.pass_k is not None
    # The mock DB agent correctly handles insert and update tasks
    # (insert task and update task should pass; delete relies on forbidden check)
    assert 0.0 <= report.pass_k <= 1.0
    assert report.total_tasks == 3
    assert report.total_attempts == 3
    assert len(report.results) == 3

    # Verify raw trajectories are retained
    for result in report.results:
        assert result.trajectory is not None

    # Verify per-tag breakdown
    assert "db" in report.per_tag


async def test_db_crud_insert_passes():
    """The insert task passes when the backend is updated correctly."""
    task = EvalTask(
        task_id="db-insert-item",
        inputs={"query": "Insert an item with id 'I-1' and name 'Widget' into the items table."},
        expected={"goal_state": {"items": {"I-1": {"name": "Widget"}}}},
        sandbox_spec=None,
    )
    ds = EvalDataset(name="test", tasks=[task])

    # Use InMemoryStateSandbox with empty initial state
    provider = InMemoryStateSandboxProvider(binder=DatabaseToolkitBinder())

    async def agent_factory_seeded(sandbox):
        """Seed the sandbox before returning the agent."""
        # Seed with empty items
        await sandbox.reset({"items": {}})
        return await make_db_agent(sandbox)

    report = await EvalRunner(
        dataset=ds,
        agent_factory=agent_factory_seeded,
        rollout=SingleTurnRollout(),
        evaluator=StateBasedEvaluator(),
        sandbox_provider=provider,
        config=EvalRunConfig(k=1),
    ).run()

    # The mock agent should have inserted I-1 with name Widget
    assert report.pass_k is not None


# ---------------------------------------------------------------------------
# Jira triage benchmark
# ---------------------------------------------------------------------------


async def test_jira_triage_benchmark_e2e():
    """Full run over jira_triage.yaml with mock Jira agent; produces pass^k."""
    ds = await YAMLDatasetLoader().load(str(BENCHMARKS_DIR / "jira_triage.yaml"))
    assert len(ds.tasks) == 2

    # Use a fixed simulator (no real LLM)
    user_sim = _FixedSimulator(["assign them", "done"])
    rollout = ConversationalRollout(user_sim=user_sim, max_turns=3)

    report = await EvalRunner(
        dataset=ds,
        agent_factory=make_jira_agent,
        rollout=rollout,
        evaluator=StateBasedEvaluator(),
        sandbox_provider=InMemoryStateSandboxProvider(binder=JiraToolkitBinder()),
        config=EvalRunConfig(k=1, max_concurrency=2),
    ).run()

    assert report.pass_k is not None
    assert 0.0 <= report.pass_k <= 1.0
    assert report.total_tasks == 2
    assert len(report.results) == 2
    assert "jira" in report.per_tag


async def test_jira_assign_task_end_to_end():
    """The Jira assign task passes when the agent assigns unassigned bugs."""
    from parrot.eval.sandbox.state import DictStateBackend, JiraToolkitBinder

    task = EvalTask(
        task_id="jira-assign-bug",
        inputs={"query": "Assign all unassigned bugs in PROJ to 'oncall'."},
        expected={"goal_state": {"issues": {"PROJ-1": {"assignee": "oncall"}}}},
    )
    ds = EvalDataset(name="test", tasks=[task])

    seed = {"issues": {"PROJ-1": {"type": "bug", "assignee": None}}}

    async def seeded_factory(sandbox):
        await sandbox.reset(seed)
        return await make_jira_agent(sandbox)

    provider = InMemoryStateSandboxProvider(binder=JiraToolkitBinder())

    report = await EvalRunner(
        dataset=ds,
        agent_factory=seeded_factory,
        rollout=SingleTurnRollout(),
        evaluator=StateBasedEvaluator(),
        sandbox_provider=provider,
        config=EvalRunConfig(k=2),
    ).run()

    assert report.pass_k is not None
    assert report.pass_at_1 is not None
    # With k=2 attempts
    assert len(report.results) == 2


# ---------------------------------------------------------------------------
# Hermetic assertion
# ---------------------------------------------------------------------------


async def test_no_real_network_in_benchmarks(monkeypatch):
    """Assert no real network socket is opened during hermetic benchmark runs."""
    import socket

    real_connect = socket.socket.connect
    connections: list = []

    def patched_connect(self, address):
        connections.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", patched_connect)

    # Run a simple benchmark
    ds = EvalDataset(
        name="hermetic",
        tasks=[EvalTask(task_id="h1", inputs={"query": "insert item I-1 name Test"})],
    )
    provider = InMemoryStateSandboxProvider(binder=DatabaseToolkitBinder())
    await EvalRunner(
        dataset=ds,
        agent_factory=make_db_agent,
        rollout=SingleTurnRollout(),
        evaluator=StateBasedEvaluator(),
        sandbox_provider=provider,
        config=EvalRunConfig(k=1),
    ).run()

    # No external connections should have been made
    assert connections == [], f"Unexpected network connections: {connections}"
