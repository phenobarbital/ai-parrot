"""Unit tests for parrot.flows.dev_loop.nodes.bug_intake (TASK-880)."""

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
        result = await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        assert result.summary == good_brief.summary

    @pytest.mark.asyncio
    async def test_emits_validated_event(self, node, good_brief):
        await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        node._fake_redis.xadd.assert_awaited_once()
        # First positional arg is the stream key
        call_args = node._fake_redis.xadd.await_args
        assert call_args.args[0] == "flow:r1:flow"


class TestValidationErrors:
    @pytest.mark.asyncio
    async def test_shell_command_must_be_in_allowlist(self, node, good_brief):
        bad = good_brief.model_copy(
            update={
                "acceptance_criteria": [
                    ShellCriterion(name="x", command="rm -rf /"),
                ]
            }
        )
        with pytest.raises(ValueError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": bad},
            )

    @pytest.mark.asyncio
    async def test_flowtask_path_rejects_traversal(self, node, good_brief):
        bad = good_brief.model_copy(
            update={
                "acceptance_criteria": [
                    FlowtaskCriterion(name="x", task_path="../etc/passwd"),
                ]
            }
        )
        with pytest.raises(ValueError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": bad},
            )

    @pytest.mark.asyncio
    async def test_flowtask_path_rejects_absolute(self, node, good_brief):
        bad = good_brief.model_copy(
            update={
                "acceptance_criteria": [
                    FlowtaskCriterion(name="x", task_path="/abs/path.yaml"),
                ]
            }
        )
        with pytest.raises(ValueError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": bad},
            )


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
