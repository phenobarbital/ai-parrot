"""Unit tests for parrot.flows.dev_loop.nodes.development (TASK-882)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    ClaudeCodeDispatchProfile,
    DevelopmentOutput,
    DispatchOutputValidationError,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.development import DevelopmentNode


@pytest.fixture
def research_out() -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path="/abs/.claude/worktrees/feat-130-fix",
        log_excerpts=[],
    )


@pytest.fixture
def dev_out() -> DevelopmentOutput:
    return DevelopmentOutput(
        files_changed=["a.py", "b.py"],
        commit_shas=["abc1234", "def5678"],
        summary="implemented the spec",
    )


class TestDispatchArguments:
    @pytest.mark.asyncio
    async def test_dispatch_kwargs_correct(self, research_out, dev_out):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)

        result = await node.execute(
            prompt="",
            ctx={"run_id": "r1", "research_output": research_out},
        )
        assert result is dev_out

        kwargs = dispatcher.dispatch.await_args.kwargs
        assert kwargs["cwd"] == research_out.worktree_path
        assert kwargs["output_model"] is DevelopmentOutput
        profile: ClaudeCodeDispatchProfile = kwargs["profile"]
        assert profile.subagent == "sdd-worker"
        assert profile.permission_mode == "acceptEdits"
        assert "Edit" in profile.allowed_tools
        assert "Write" in profile.allowed_tools


class TestPropagatesValidationError:
    @pytest.mark.asyncio
    async def test_validation_error_bubbles_up(self, research_out):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=DispatchOutputValidationError(
                "no JSON", raw_payload=""
            )
        )
        node = DevelopmentNode(dispatcher=dispatcher)
        with pytest.raises(DispatchOutputValidationError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "research_output": research_out},
            )


class TestStoresOutputInContext:
    @pytest.mark.asyncio
    async def test_writes_development_output_to_ctx(
        self, research_out, dev_out
    ):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)

        ctx = {"run_id": "r1", "research_output": research_out}
        await node.execute(prompt="", ctx=ctx)
        assert ctx["development_output"] is dev_out
