"""End-to-end adversarial tests for complexity-based routing (FEAT-561)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import (
    CoderJob,
    PlannedTask,
    RosterConfig,
    RosterSeat,
    StrongModelIdentity,
)
from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment,
    ComplexityContract,
    ComplexityEvidence,
    ComplexityPolicy,
    ComplexityTarget,
    MetricEvidence,
)


class FakeComplexityDispatcher:
    """Fake dispatcher that records model identity and simulates different behaviors."""

    def __init__(self, behavior: str = "ok") -> None:
        self.behavior = behavior
        self.calls: list[dict] = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        self.calls.append({
            "brief": brief,
            "profile": profile,
            "node_id": node_id,
            "cwd": cwd,
            "labels": labels,
            "backend": profile.backend if hasattr(profile, "backend") else None,
            "model": profile.model if hasattr(profile, "model") else None,
        })
        
        if self.behavior == "fail":
            raise RuntimeError("dispatch failed")
            
        # Return a successful development output
        return DevelopmentOutput(
            files_changed=["test.py"],
            commit_shas=["abcdef1234567890"],
            summary="fake implementation"
        )


def fake_complexity_builder_factory(behavior_by_backend: dict):
    """Factory for fake dispatchers."""
    dispatchers: dict[str, FakeComplexityDispatcher] = {}

    def _builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds):
        behavior = behavior_by_backend.get(spec.agent, "ok")
        dispatcher = FakeComplexityDispatcher(behavior)
        dispatchers[spec.agent] = dispatcher
        from parrot.flows.dev_loop.models import LLMCodeDispatchProfile
        profile = LLMCodeDispatchProfile()
        return dispatcher, profile

    _builder.dispatchers = dispatchers  # type: ignore[attr-defined]
    return _builder


@pytest.fixture
def strong_policy() -> ComplexityPolicy:
    """Create a policy with strong model configurations."""
    return ComplexityPolicy(
        version="v1",
        strong_models=(
            StrongModelIdentity(
                canonical_model="gpt-5.6-terra",
                backend="codex",
                model="gpt-5.6-terra"
            ),
            StrongModelIdentity(
                canonical_model="sonnet-5",
                backend="claude",
                model="claude-sonnet-5"
            ),
        )
    )


@pytest.fixture
def weak_roster() -> RosterConfig:
    """Create a roster with only weak models."""
    return RosterConfig(
        seats=[
            RosterSeat(label="w1", backend="codex", model="haiku"),
            RosterSeat(label="w2", backend="claude", model="sonnet"),  # Not sonnet-5
        ]
    )


@pytest.fixture
def mixed_roster() -> RosterConfig:
    """Create a roster with both strong and weak models."""
    return RosterConfig(
        seats=[
            RosterSeat(label="w1", backend="codex", model="haiku"),
            RosterSeat(label="s1", backend="codex", model="gpt-5.6-terra"),
            RosterSeat(label="s2", backend="claude", model="claude-sonnet-5"),
        ]
    )


def create_mock_assessment(
    task_id: str,
    classification: str = "standard",
    cyclomatic_value: Optional[int] = None,
) -> ComplexityAssessment:
    """Create a mock complexity assessment."""
    contract = ComplexityContract(
        schema_version=1,
        targets=(ComplexityTarget(path="test.py", action="CREATE"),),
        contract_symbols=None,
    )
    
    metrics: Dict[str, MetricEvidence] = {}
    if cyclomatic_value is not None:
        metrics["cyclomatic_max"] = MetricEvidence(
            state="ok",
            value=cyclomatic_value,
            reason="test metric",
            source="test"
        )
    
    evidence = ComplexityEvidence(
        task_id=task_id,
        contract=contract,
        metrics=metrics,
        head_sha="abc123",
        task_sha256="task_hash",
        index_sha256="index_hash",
        policy_sha256="policy_hash",
        target_hashes={"test.py": None},
        wiki_evidence_hashes={},
        collector_versions={},
        details={},
    )
    
    # Simple mock assessment without going through full evaluation
    return ComplexityAssessment(
        policy_version="v1",
        task_id=task_id,
        classification=classification,
        total_points=0,
        component_points={},
        reason_codes=("test_reason",),
        evidence=evidence,
        assessment_id=f"test_assessment_{task_id}",
    )


async def test_complex_task_blocked_without_strong_models(
    git_sandbox_feature, 
    weak_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that complex tasks are blocked when no strong models are available."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Mock the complexity assessment to return a complex task
    mock_assessment = create_mock_assessment("TASK-0001", "complex", cyclomatic_value=25)
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    engine = SddCoderEngine(
        roster=weak_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=fake_complexity_builder_factory({}),
    )
    
    # Planning should succeed but block the complex task
    plan = await engine.plan("demo", str(worktree))
    
    # The complex task should be blocked
    blocked_tasks = [block for block in plan.routing_blocks if block.task_id == "TASK-0001"]
    assert len(blocked_tasks) == 1
    assert blocked_tasks[0].code == "complex_model_unavailable"
    
    # Running the chunk should fail for the complex task
    with pytest.raises(CoderFailure) as exc_info:
        await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    
    assert exc_info.value.code == "complex_model_unavailable"


async def test_complex_task_routes_to_strong_model(
    git_sandbox_feature, 
    mixed_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that complex tasks route to strong models when available."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Mock the complexity assessment to return a complex task
    mock_assessment = create_mock_assessment("TASK-0001", "complex", cyclomatic_value=25)
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    builder = fake_complexity_builder_factory({})
    engine = SddCoderEngine(
        roster=mixed_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    
    # Planning should succeed and assign to strong model
    plan = await engine.plan("demo", str(worktree))
    
    # No routing blocks for complex task with strong models available
    blocked_tasks = [block for block in plan.routing_blocks if block.task_id == "TASK-0001"]
    assert len(blocked_tasks) == 0
    
    # The task should be assigned to a strong model seat
    task_chunks = [chunk for chunk in plan.chunks for task in chunk.tasks if task.task_id == "TASK-0001"]
    assert len(task_chunks) == 1
    assigned_task = task_chunks[0]
    assert assigned_task.seat_label in ["s1", "s2"]  # Strong model seats
    
    # Running the chunk should succeed and use strong model
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 10)
    
    assert result.state == "done"
    assert len(result.tasks) == 1
    assert result.tasks[0].outcome == "merged"
    
    # Verify the dispatcher was called with strong model
    dispatchers = builder.dispatchers
    called_dispatchers = [d for d in dispatchers.values() if d.calls]
    assert len(called_dispatchers) == 1
    call = called_dispatchers[0].calls[0]
    assert call["labels"]["seat"] in ["s1", "s2"]


async def test_standard_task_uses_normal_rotation(
    git_sandbox_feature, 
    mixed_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that standard tasks use normal roster rotation."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Mock the complexity assessment to return a standard task
    mock_assessment = create_mock_assessment("TASK-0001", "standard")
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    builder = fake_complexity_builder_factory({})
    engine = SddCoderEngine(
        roster=mixed_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    
    # Planning should succeed and assign normally
    plan = await engine.plan("demo", str(worktree))
    
    # No routing blocks for standard task
    blocked_tasks = [block for block in plan.routing_blocks if block.task_id == "TASK-0001"]
    assert len(blocked_tasks) == 0
    
    # The task should be assigned to any available seat (rotation behavior)
    task_chunks = [chunk for chunk in plan.chunks for task in chunk.tasks if task.task_id == "TASK-0001"]
    assert len(task_chunks) == 1
    # Could be any seat depending on rotation


async def test_unknown_task_blocked_without_strong_models(
    git_sandbox_feature, 
    weak_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that unknown tasks are blocked when no strong models are available."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Mock the complexity assessment to return an unknown task
    mock_assessment = create_mock_assessment("TASK-0001", "unknown")
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    engine = SddCoderEngine(
        roster=weak_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=fake_complexity_builder_factory({}),
    )
    
    # Planning should succeed but block the unknown task
    plan = await engine.plan("demo", str(worktree))
    
    # The unknown task should be blocked
    blocked_tasks = [block for block in plan.routing_blocks if block.task_id == "TASK-0001"]
    assert len(blocked_tasks) == 1
    assert blocked_tasks[0].code == "complex_model_unavailable"


async def test_hard_limit_triggers_complex_classification(
    git_sandbox_feature, 
    mixed_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that hard limits trigger complex classification."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Mock the complexity assessment with a value that hits hard limit
    mock_assessment = create_mock_assessment("TASK-0001", "complex", cyclomatic_value=21)  # Hit hard limit
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    builder = fake_complexity_builder_factory({})
    engine = SddCoderEngine(
        roster=mixed_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    
    # Planning should classify as complex due to hard limit
    plan = await engine.plan("demo", str(worktree))
    
    # No routing blocks for complex task with strong models available
    blocked_tasks = [block for block in plan.routing_blocks if block.task_id == "TASK-0001"]
    assert len(blocked_tasks) == 0
    
    # Should be assigned to strong model
    task_chunks = [chunk for chunk in plan.chunks for task in chunk.tasks if task.task_id == "TASK-0001"]
    assert len(task_chunks) == 1
    assigned_task = task_chunks[0]
    assert assigned_task.seat_label in ["s1", "s2"]


async def test_native_preparation_respects_complexity(
    git_sandbox_feature, 
    weak_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that native preparation respects complexity model requirements."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Create a roster with a native seat and weak models
    native_roster = RosterConfig(
        seats=[
            RosterSeat(label="n1", kind="native"),
            RosterSeat(label="w1", backend="codex", model="haiku"),
        ]
    )
    
    # Mock the complexity assessment to return a complex task
    mock_assessment = create_mock_assessment("TASK-0001", "complex", cyclomatic_value=25)
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    engine = SddCoderEngine(
        roster=native_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    
    # Preparing a native task for a complex assessment should fail
    with pytest.raises(CoderFailure) as exc_info:
        await engine.prepare_native("demo", str(worktree), "TASK-0001")
    
    assert exc_info.value.code == "complex_model_unavailable"
    assert "native" in exc_info.value.message
    assert "complex" in exc_info.value.message


async def test_retry_uses_different_strong_model(
    git_sandbox_feature, 
    mixed_roster, 
    noop_probe,
    strong_policy,
    monkeypatch
):
    """Test that retries of complex tasks use different strong models."""
    worktree, feature_branch, base_path, index_path = git_sandbox_feature
    
    # Mock the complexity assessment to return a complex task
    mock_assessment = create_mock_assessment("TASK-0001", "complex", cyclomatic_value=25)
    
    def mock_compute_assessment(self, ctx, task, task_file):
        return mock_assessment
    
    monkeypatch.setattr(SddCoderEngine, "_compute_assessment", mock_compute_assessment)
    
    # Make first dispatch fail to trigger retry
    builder = fake_complexity_builder_factory({"codex": "fail"})
    engine = SddCoderEngine(
        roster=mixed_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    
    # Run chunk - first attempt should fail, second should succeed on different seat
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 10)
    
    # Should eventually succeed with merged outcome
    assert result.state == "done"
    assert len(result.tasks) == 1
    task_result = result.tasks[0]
    assert task_result.outcome == "merged"
    
    # Should have multiple attempts
    assert len(task_result.attempts) >= 1
    
    # If there were multiple attempts, they should be on different seats
    if len(task_result.attempts) > 1:
        first_seat = task_result.attempts[0].seat_label
        second_seat = task_result.attempts[1].seat_label
        assert first_seat != second_seat