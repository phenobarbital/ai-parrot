"""Unit tests for parrot.flows.dev_loop.nodes.development (TASK-882)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    ClaudeCodeDispatchProfile,
    CodexCodeDispatchProfile,
    DevelopmentOutput,
    DispatchOutputValidationError,
    LLMCodeDispatchProfile,
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
        # FEAT-322: no "session_host" in shared state (legacy caller) →
        # dispatch() must be called with session_host=None (its default).
        assert kwargs["session_host"] is None

    @pytest.mark.asyncio
    async def test_dispatch_forwards_session_host_when_present(
        self, research_out, dev_out
    ):
        """FEAT-322: shared["session_host"] must reach dispatcher.dispatch()."""
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)
        sentinel_host = object()

        await node.execute(
            prompt="",
            ctx={
                "run_id": "r1",
                "research_output": research_out,
                "session_host": sentinel_host,
            },
        )

        kwargs = dispatcher.dispatch.await_args.kwargs
        assert kwargs["session_host"] is sentinel_host

    @pytest.mark.asyncio
    async def test_injected_dispatch_profile_used(self, research_out, dev_out):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        profile = CodexCodeDispatchProfile(model="gpt-5.5")
        node = DevelopmentNode(
            dispatcher=dispatcher,
            dispatch_profile=profile,
        )

        await node.execute(
            ctx={"run_id": "r1", "research_output": research_out},
        )

        kwargs = dispatcher.dispatch.await_args.kwargs
        assert kwargs["profile"] is profile

    @pytest.mark.asyncio
    async def test_injected_llm_dispatch_profile_used(self, research_out, dev_out):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        profile = LLMCodeDispatchProfile(llm="nvidia:z-ai/glm-5.1")
        node = DevelopmentNode(
            dispatcher=dispatcher,
            dispatch_profile=profile,
        )

        await node.execute(
            ctx={"run_id": "r1", "research_output": research_out},
        )

        kwargs = dispatcher.dispatch.await_args.kwargs
        assert kwargs["profile"] is profile


class TestPropagatesValidationError:
    @pytest.mark.asyncio
    async def test_validation_error_bubbles_up(self, research_out):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(side_effect=DispatchOutputValidationError("no JSON", raw_payload=""))
        node = DevelopmentNode(dispatcher=dispatcher)
        with pytest.raises(DispatchOutputValidationError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "research_output": research_out},
            )


class TestStoresOutputInContext:
    @pytest.mark.asyncio
    async def test_writes_development_output_to_ctx(self, research_out, dev_out):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=dev_out)
        node = DevelopmentNode(dispatcher=dispatcher)

        ctx = {"run_id": "r1", "research_output": research_out}
        await node.execute(ctx)
        assert ctx["development_output"] is dev_out
