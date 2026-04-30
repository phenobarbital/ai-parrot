"""Unit tests for IntentClassifierNode (TASK-898).

Covers:
- Shell allowlist validation (rejects disallowed heads)
- FlowtaskCriterion path-traversal validation
- Redis XADD emission (exactly one per call, correct stream key, payload shape)
- No emission when run_id is absent
- ctx propagation: both legacy and new keys are written
- Returns the validated WorkBrief (routing predicate reads result.kind)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    FlowtaskCriterion,
    IntentClassifierNode,
    LogSource,
    ShellCriterion,
    WorkBrief,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def good_brief() -> WorkBrief:
    """Canonical happy-path WorkBrief (bug kind) with allowed criteria."""
    return WorkBrief(
        kind="bug",
        summary="Customer sync drops the last row when input has >1000 rows",
        affected_component="etl/customers/sync.yaml",
        log_sources=[LogSource(kind="cloudwatch", locator="/etl/x")],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="sync-passes", task_path="etl/customers/sync.yaml"
            ),
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def node(monkeypatch) -> IntentClassifierNode:
    """Node with a mocked Redis client so no live Redis is needed."""
    n = IntentClassifierNode(redis_url="redis://localhost:6379/0")
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(n, "_ensure_redis", _ensure_redis)
    n._fake_redis = fake_redis  # type: ignore[attr-defined]
    return n


@pytest.fixture
def sample_kwargs() -> dict:
    """Minimal keyword dict to construct a WorkBrief (no acceptance_criteria)."""
    return {
        "summary": "Customer sync drops the last row when input has >1000 rows",
        "affected_component": "etl/customers/sync.yaml",
        "log_sources": [],
        "escalation_assignee": "oncall@example.com",
        "reporter": "reporter@example.com",
    }


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.asyncio
    async def test_rejects_disallowed_shell_head(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """Shell criteria with heads not in the allowlist must raise ValueError."""
        bad = good_brief.model_copy(
            update={
                "acceptance_criteria": [
                    ShellCriterion(name="bad", command="rm -rf /"),
                ]
            }
        )
        with pytest.raises(ValueError, match="not in allowlist"):
            await node.execute("", {"bug_brief": bad, "run_id": "r1"})

    @pytest.mark.asyncio
    async def test_accepts_task_head(
        self, node: IntentClassifierNode, sample_kwargs: dict
    ):
        """Shell criteria whose head is 'task' are allowed."""
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="task-run", command="task etl/x.yaml"),
            ],
        )
        result = await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        assert result is brief

    @pytest.mark.asyncio
    async def test_accepts_ruff_head(
        self, node: IntentClassifierNode, sample_kwargs: dict
    ):
        """Shell criteria whose head is 'ruff' are allowed."""
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="lint", command="ruff check ."),
            ],
        )
        result = await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        assert result is brief

    @pytest.mark.asyncio
    async def test_flowtask_path_rejects_traversal(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """FlowtaskCriterion with '..' in path must raise ValueError."""
        bad = good_brief.model_copy(
            update={
                "acceptance_criteria": [
                    FlowtaskCriterion(name="x", task_path="../etc/passwd"),
                ]
            }
        )
        with pytest.raises(ValueError, match="Invalid relative task_path"):
            await node.execute("", {"bug_brief": bad, "run_id": "r1"})

    @pytest.mark.asyncio
    async def test_flowtask_path_rejects_absolute(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """FlowtaskCriterion with an absolute path must raise ValueError."""
        bad = good_brief.model_copy(
            update={
                "acceptance_criteria": [
                    FlowtaskCriterion(name="x", task_path="/abs/path.yaml"),
                ]
            }
        )
        with pytest.raises(ValueError, match="Invalid relative task_path"):
            await node.execute("", {"bug_brief": bad, "run_id": "r1"})

    @pytest.mark.asyncio
    async def test_flowtask_relative_path_accepted(
        self, node: IntentClassifierNode, sample_kwargs: dict
    ):
        """FlowtaskCriterion with a safe relative path is accepted."""
        brief = WorkBrief(
            **sample_kwargs,
            acceptance_criteria=[
                FlowtaskCriterion(name="ok", task_path="etl/customers/sync.yaml"),
            ],
        )
        result = await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        assert result is brief


# ---------------------------------------------------------------------------
# Redis emission tests
# ---------------------------------------------------------------------------


class TestEmission:
    @pytest.mark.asyncio
    async def test_emits_one_xadd_per_call(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """Exactly one XADD per execute call."""
        await node.execute("", {"bug_brief": good_brief, "run_id": "r1"})
        assert node._fake_redis.xadd.call_count == 1

    @pytest.mark.asyncio
    async def test_xadd_stream_key_is_correct(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """The XADD target stream key must be flow:{run_id}:flow."""
        await node.execute("", {"bug_brief": good_brief, "run_id": "run-42"})
        call_args = node._fake_redis.xadd.await_args
        assert call_args.args[0] == "flow:run-42:flow"

    @pytest.mark.asyncio
    async def test_event_kind_is_intake_validated(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """The event envelope's kind must be 'flow.intake_validated'."""
        await node.execute("", {"bug_brief": good_brief, "run_id": "r1"})
        call_args = node._fake_redis.xadd.await_args
        fields = call_args.args[1]
        envelope = json.loads(fields["event"])
        assert envelope["kind"] == "flow.intake_validated"

    @pytest.mark.asyncio
    async def test_payload_includes_kind_field(
        self, node: IntentClassifierNode, sample_kwargs: dict
    ):
        """The event payload must include the brief's kind."""
        brief = WorkBrief(
            kind="enhancement",
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="ok", command="ruff check ."),
            ],
        )
        await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        call_args = node._fake_redis.xadd.await_args
        fields = call_args.args[1]
        envelope = json.loads(fields["event"])
        assert envelope["payload"]["kind"] == "enhancement"

    @pytest.mark.asyncio
    async def test_does_not_emit_without_run_id(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """When run_id is absent or empty, no XADD is issued."""
        await node.execute("", {"bug_brief": good_brief, "run_id": ""})
        assert node._fake_redis.xadd.call_count == 0

    @pytest.mark.asyncio
    async def test_does_not_emit_when_run_id_not_in_ctx(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """When run_id is absent from ctx, no XADD is issued."""
        await node.execute("", {"bug_brief": good_brief})
        assert node._fake_redis.xadd.call_count == 0


# ---------------------------------------------------------------------------
# Context propagation tests
# ---------------------------------------------------------------------------


class TestContextPropagation:
    @pytest.mark.asyncio
    async def test_writes_legacy_bug_brief_key(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """ctx['bug_brief'] is populated for back-compat with downstream nodes."""
        ctx: dict = {"bug_brief": good_brief, "run_id": ""}
        await node.execute("", ctx)
        assert ctx["bug_brief"] is good_brief

    @pytest.mark.asyncio
    async def test_writes_new_work_brief_key(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """ctx['work_brief'] is populated for forward-compat."""
        ctx: dict = {"bug_brief": good_brief, "run_id": ""}
        await node.execute("", ctx)
        assert ctx["work_brief"] is good_brief

    @pytest.mark.asyncio
    async def test_returns_brief_for_routing(
        self, node: IntentClassifierNode, sample_kwargs: dict
    ):
        """execute() returns the validated WorkBrief with the correct kind."""
        brief = WorkBrief(
            kind="enhancement",
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="ok", command="ruff check ."),
            ],
        )
        result = await node.execute("", {"bug_brief": brief, "run_id": ""})
        assert result.kind == "enhancement"

    @pytest.mark.asyncio
    async def test_returns_kind_new_feature(
        self, node: IntentClassifierNode, sample_kwargs: dict
    ):
        """execute() returns a WorkBrief with kind='new_feature'."""
        brief = WorkBrief(
            kind="new_feature",
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="ok", command="pytest tests/"),
            ],
        )
        result = await node.execute("", {"bug_brief": brief, "run_id": ""})
        assert result.kind == "new_feature"


# ---------------------------------------------------------------------------
# Brief loading tests
# ---------------------------------------------------------------------------


class TestBriefLoading:
    @pytest.mark.asyncio
    async def test_loads_from_work_brief_key(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """Brief can be loaded from ctx['work_brief'] (new key)."""
        ctx: dict = {"work_brief": good_brief, "run_id": ""}
        result = await node.execute("", ctx)
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_loads_from_bug_brief_key(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """Brief can be loaded from ctx['bug_brief'] (legacy key)."""
        result = await node.execute("", {"bug_brief": good_brief, "run_id": ""})
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_loads_from_dict_in_ctx(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """Brief dict in ctx is coerced to WorkBrief."""
        result = await node.execute(
            "", {"bug_brief": good_brief.model_dump(), "run_id": ""}
        )
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_loads_from_json_prompt(
        self, node: IntentClassifierNode, good_brief: WorkBrief
    ):
        """Brief can be provided as a JSON string in the prompt arg."""
        result = await node.execute(good_brief.model_dump_json(), {"run_id": ""})
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_missing_brief_raises(self, node: IntentClassifierNode):
        """When no brief is available, ValueError is raised."""
        with pytest.raises(ValueError, match="requires ctx"):
            await node.execute("", {"run_id": "r1"})
