"""Unit tests for parrot.flows.dev_loop.nodes.bug_intake (TASK-880, TASK-899).

FEAT-132 scope-down: allowlist / path-traversal validation tests removed from
this file — they now live in test_intent_classifier.py (TASK-898). This file
retains load/emit/pass-through coverage for BugIntakeNode's post-scope-down
responsibilities.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    LogSource,
    ShellCriterion,
)
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode


@pytest.fixture
def good_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[LogSource(kind="cloudwatch", locator="/etl/x")],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="run", task_path="etl/customers/sync.yaml"
            ),
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def node(monkeypatch):
    n = BugIntakeNode(redis_url="redis://localhost:6379/0")
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(n, "_ensure_redis", _ensure_redis)
    n._fake_redis = fake_redis  # type: ignore[attr-defined]
    return n


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_validated_brief(self, node, good_brief):
        """execute() returns the brief unchanged (validation is upstream)."""
        result = await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_writes_brief_to_ctx(self, node, good_brief):
        """ctx['bug_brief'] is populated with the brief after execute()."""
        ctx = {"run_id": "", "bug_brief": good_brief}
        result = await node.execute("", ctx)
        assert result is good_brief
        assert ctx["bug_brief"] is good_brief

    @pytest.mark.asyncio
    async def test_emits_bug_brief_validated_event(self, node, good_brief):
        """Exactly one XADD per execute call when run_id is set."""
        await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        node._fake_redis.xadd.assert_awaited_once()
        call_args = node._fake_redis.xadd.await_args
        assert call_args.args[0] == "flow:r1:flow"

    @pytest.mark.asyncio
    async def test_does_not_emit_without_run_id(self, node, good_brief):
        """No XADD when run_id is empty."""
        await node.execute("", {"run_id": "", "bug_brief": good_brief})
        assert node._fake_redis.xadd.call_count == 0


class TestBriefLoading:
    @pytest.mark.asyncio
    async def test_loads_from_dict_in_ctx(self, node, good_brief):
        result = await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief.model_dump()},
        )
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_loads_from_json_prompt(self, node, good_brief):
        result = await node.execute(
            prompt=good_brief.model_dump_json(),
            ctx={"run_id": "r1"},
        )
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_missing_brief_raises(self, node):
        with pytest.raises(ValueError):
            await node.execute(prompt="", ctx={"run_id": "r1"})
