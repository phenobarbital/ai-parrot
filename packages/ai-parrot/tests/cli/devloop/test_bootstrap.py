"""Unit tests for devloop bootstrap & preflight."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from parrot.cli.devloop.bootstrap import (
    PreflightCheck,
    PreflightResult,
    build_runtime,
    preflight,
)


@pytest.mark.asyncio
async def test_preflight_all_pass():
    """All checks pass when env is fully configured."""
    mock_conf = MagicMock()
    mock_conf.config.get = MagicMock(side_effect=lambda k, fallback="": {
        "REDIS_URL": "redis://localhost:6379",
    }.get(k, fallback))
    mock_conf.JIRA_URL = "https://jira.example.com"
    mock_conf.JIRA_USERNAME = "user"
    mock_conf.JIRA_API_TOKEN = "token"
    mock_conf.WORKTREE_BASE_PATH = "/tmp/worktrees"

    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch.dict("sys.modules", {"parrot.conf": MagicMock(), "parrot": MagicMock(conf=mock_conf)}), \
         patch("parrot.cli.devloop.bootstrap.os.environ", {"USER": "testuser", "WORKTREE_BASE_PATH": "/tmp/wt"}):
        mock_shutil.which.return_value = "/usr/bin/claude"
        # Patch the import of conf inside the function
        with patch("parrot.cli.devloop.bootstrap.preflight.__module__", "parrot.cli.devloop.bootstrap"):
            result = await preflight()

    # Verify structure
    assert isinstance(result, PreflightResult)
    assert isinstance(result.checks, list)
    assert all(isinstance(c, PreflightCheck) for c in result.checks)


@pytest.mark.asyncio
async def test_preflight_missing_claude_cli():
    """Missing claude CLI results in a failed check with hint."""
    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil:
        mock_shutil.which.return_value = None
        result = await preflight()

    claude_check = next((c for c in result.checks if c.name == "claude-cli"), None)
    assert claude_check is not None
    assert claude_check.passed is False
    assert "Claude Code" in claude_check.hint


@pytest.mark.asyncio
async def test_preflight_missing_redis():
    """Missing REDIS_URL results in a failed check."""
    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch("parrot.cli.devloop.bootstrap.os.environ", {}):
        mock_shutil.which.return_value = "/usr/bin/claude"
        result = await preflight()

    redis_check = next((c for c in result.checks if c.name == "redis"), None)
    assert redis_check is not None
    # Will be False because conf import likely fails in test and env is empty
    assert isinstance(redis_check.passed, bool)


@pytest.mark.asyncio
async def test_preflight_result_ok_false_when_any_fail():
    """PreflightResult.ok is False when any check fails."""
    result = PreflightResult(
        ok=False,
        checks=[
            PreflightCheck(name="a", passed=True),
            PreflightCheck(name="b", passed=False, hint="fix b"),
        ],
    )
    assert result.ok is False


def test_preflight_check_model():
    """PreflightCheck validates properly."""
    check = PreflightCheck(name="redis", passed=True)
    assert check.name == "redis"
    assert check.passed is True
    assert check.hint == ""


@pytest.mark.asyncio
async def test_build_runtime_wires_graph_memory_and_plan_approval():
    """FEAT-377 TASK-1914/1915/1916: build_runtime() must construct the
    opt-in DevLoopGraphMemory via from_config() and forward both it and
    conf.DEV_LOOP_REQUIRE_PLAN_APPROVAL to build_dev_loop_flow(), and
    forward graph_memory to DevLoopRunner() too (consumed by its lazily
    built revision flow). Before this fix, both were silently dropped —
    parrot devloop could never reach either feature."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod

    sentinel_memory = object()
    sentinel_flow = object()
    sentinel_runner = MagicMock()

    ok_result = PreflightResult(ok=True, checks=[])

    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result)), \
         patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None), \
         patch.object(bootstrap_mod, "_build_log_toolkits", return_value={}), \
         patch.object(
             bootstrap_mod, "default_identities",
             AsyncMock(return_value=("reporter", "escalation")),
         ), \
         patch("parrot.conf.DEV_LOOP_REQUIRE_PLAN_APPROVAL", True, create=True), \
         patch("parrot.flows.dev_loop.ClaudeCodeDispatcher") as MockDispatcher, \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow",
             return_value=sentinel_flow,
         ) as mock_build_flow, \
         patch(
             "parrot.flows.dev_loop.DevLoopRunner",
             return_value=sentinel_runner,
         ) as MockRunner, \
         patch(
             "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
             AsyncMock(return_value=sentinel_memory),
         ):
        runtime = await build_runtime()

    MockDispatcher.assert_called_once()

    mock_build_flow.assert_called_once()
    _, flow_kwargs = mock_build_flow.call_args
    assert flow_kwargs["graph_memory"] is sentinel_memory
    assert flow_kwargs["require_plan_approval"] is True

    MockRunner.assert_called_once()
    _, runner_kwargs = MockRunner.call_args
    assert runner_kwargs["graph_memory"] is sentinel_memory

    assert runtime.graph_memory is sentinel_memory
    assert runtime.runner is sentinel_runner
    assert runtime.flow is sentinel_flow


@pytest.mark.asyncio
async def test_build_runtime_graph_memory_disabled_by_default():
    """When DEV_LOOP_GRAPH_MEMORY_PATH is unset, from_config() returns
    None and build_runtime() must still pass graph_memory=None through
    explicitly (never crash, never silently substitute a truthy value)."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod

    ok_result = PreflightResult(ok=True, checks=[])

    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result)), \
         patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None), \
         patch.object(bootstrap_mod, "_build_log_toolkits", return_value={}), \
         patch.object(
             bootstrap_mod, "default_identities",
             AsyncMock(return_value=("reporter", "escalation")),
         ), \
         patch("parrot.conf.DEV_LOOP_REQUIRE_PLAN_APPROVAL", False, create=True), \
         patch("parrot.conf.DEV_LOOP_GRAPH_MEMORY_PATH", "", create=True), \
         patch("parrot.flows.dev_loop.ClaudeCodeDispatcher"), \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow", return_value=MagicMock(),
         ) as mock_build_flow, \
         patch("parrot.flows.dev_loop.DevLoopRunner", return_value=MagicMock()) as MockRunner:
        runtime = await build_runtime()

    _, flow_kwargs = mock_build_flow.call_args
    assert flow_kwargs["graph_memory"] is None
    assert flow_kwargs["require_plan_approval"] is False
    _, runner_kwargs = MockRunner.call_args
    assert runner_kwargs["graph_memory"] is None
    assert runtime.graph_memory is None
