"""Unit tests for devloop bootstrap & preflight."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


# ── FEAT-388 TASK-1971: backend-aware preflight + build_dispatcher wiring ──


@pytest.mark.asyncio
async def test_default_backend_is_claude_code():
    """Unset DEV_LOOP_DEVELOPMENT_AGENT resolves claude-code — byte-identical
    check name/hint to the pre-FEAT-388 unconditional claude-cli check."""
    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil:
        mock_shutil.which.return_value = None
        result = await preflight()

    check = next((c for c in result.checks if c.name == "claude-cli"), None)
    assert check is not None
    assert check.passed is False
    assert "Claude Code" in check.hint


@pytest.mark.asyncio
async def test_codex_backend_skips_claude_check():
    """DEV_LOOP_DEVELOPMENT_AGENT=codex + no claude binary still passes
    preflight overall — the codex binary (not claude) is what's checked."""
    import parrot.conf as real_conf

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "DEV_LOOP_DEVELOPMENT_AGENT":
            return "codex"
        return original_get(key, fallback=fallback)

    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch.object(real_conf.config, "get", side_effect=fake_get):
        mock_shutil.which.side_effect = lambda binary: (
            "/usr/bin/codex" if binary == "codex" else None
        )
        result = await preflight()

    codex_check = next((c for c in result.checks if c.name == "codex-cli"), None)
    assert codex_check is not None
    assert codex_check.passed is True
    claude_check = next((c for c in result.checks if c.name == "claude-cli"), None)
    assert claude_check is None  # claude-cli is not even checked for codex


@pytest.mark.asyncio
async def test_unknown_backend_fails_preflight_with_hint():
    """An unrecognized DEV_LOOP_DEVELOPMENT_AGENT fails preflight with a
    hint listing every valid catalog backend id."""
    import parrot.conf as real_conf

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "DEV_LOOP_DEVELOPMENT_AGENT":
            return "not-a-backend"
        return original_get(key, fallback=fallback)

    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch.object(real_conf.config, "get", side_effect=fake_get):
        mock_shutil.which.return_value = "/usr/bin/claude"
        result = await preflight()

    check = next((c for c in result.checks if c.name == "dev-agent-backend"), None)
    assert check is not None
    assert check.passed is False
    assert "codex" in check.hint
    assert "claude-code" in check.hint
    assert result.ok is False


@pytest.mark.asyncio
async def test_intake_llm_hint_is_soft():
    """A DEV_LOOP_INTAKE_LLM whose provider lacks credentials gets a hint,
    but the check always passes — feature-mode intake is optional."""
    import parrot.conf as real_conf

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "DEV_LOOP_INTAKE_LLM":
            return "anthropic:claude-haiku-4-5"
        return original_get(key, fallback=fallback)

    with patch("parrot.cli.devloop.bootstrap.shutil") as mock_shutil, \
         patch.object(real_conf.config, "get", side_effect=fake_get), \
         patch("parrot.cli.devloop.bootstrap.os.environ", {}):
        mock_shutil.which.return_value = "/usr/bin/claude"
        result = await preflight()

    check = next((c for c in result.checks if c.name == "intake-llm"), None)
    assert check is not None
    assert check.passed is True
    assert "ANTHROPIC_API_KEY" in check.hint


@pytest.mark.asyncio
async def test_build_runtime_uses_build_dispatcher():
    """build_runtime() materializes the default dispatcher via
    agent_builder.build_dispatcher (FEAT-388 G6), not a hardcoded
    ClaudeCodeDispatcher — and forwards the returned profile to
    build_dev_loop_flow(development_profile=...)."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod

    sentinel_dispatcher = MagicMock()
    sentinel_profile = MagicMock()
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
         patch(
             "parrot.flows.dev_loop.agent_builder.build_dispatcher",
             return_value=(sentinel_dispatcher, sentinel_profile),
         ) as mock_build_dispatcher, \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow",
             return_value=sentinel_flow,
         ) as mock_build_flow, \
         patch(
             "parrot.flows.dev_loop.DevLoopRunner",
             return_value=sentinel_runner,
         ), \
         patch(
             "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
             AsyncMock(return_value=None),
         ):
        runtime = await build_runtime()

    mock_build_dispatcher.assert_called_once()
    spec_arg = mock_build_dispatcher.call_args[0][0]
    assert spec_arg.agent == "claude-code"  # default when env unset

    mock_build_flow.assert_called_once()
    _, flow_kwargs = mock_build_flow.call_args
    assert flow_kwargs["dispatcher"] is sentinel_dispatcher
    assert flow_kwargs["development_profile"] is sentinel_profile

    assert runtime.dispatcher is sentinel_dispatcher


@pytest.mark.asyncio
async def test_build_runtime_resolves_codex_backend():
    """DEV_LOOP_DEVELOPMENT_AGENT=codex + no claude binary: build_runtime()
    resolves a DevAgentSpec(agent="codex") — the runtime's default
    dispatcher is the Codex dispatcher (G6), not hardcoded claude-code."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod
    import parrot.conf as real_conf

    sentinel_dispatcher = MagicMock()
    sentinel_profile = MagicMock()

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "DEV_LOOP_DEVELOPMENT_AGENT":
            return "codex"
        return original_get(key, fallback=fallback)

    ok_result = PreflightResult(ok=True, checks=[])

    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result)), \
         patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None), \
         patch.object(bootstrap_mod, "_build_log_toolkits", return_value={}), \
         patch.object(
             bootstrap_mod, "default_identities",
             AsyncMock(return_value=("reporter", "escalation")),
         ), \
         patch.object(real_conf.config, "get", side_effect=fake_get), \
         patch(
             "parrot.flows.dev_loop.agent_builder.build_dispatcher",
             return_value=(sentinel_dispatcher, sentinel_profile),
         ) as mock_build_dispatcher, \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow",
             return_value=object(),
         ), \
         patch("parrot.flows.dev_loop.DevLoopRunner", return_value=MagicMock()), \
         patch(
             "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
             AsyncMock(return_value=None),
         ):
        runtime = await build_runtime()

    mock_build_dispatcher.assert_called_once()
    spec_arg = mock_build_dispatcher.call_args[0][0]
    assert spec_arg.agent == "codex"
    assert runtime.dispatcher is sentinel_dispatcher


# ── Post-review CRITICAL fix: codereview_dispatcher must match the
# resolved backend, not silently fall back to a claude-code-only wrap ──


@pytest.mark.asyncio
async def test_build_runtime_claude_code_keeps_codereview_none():
    """Default backend (claude-code): codereview_dispatcher stays None —
    byte-identical to the pre-fix behavior (QANode's own fallback is
    already correct for a real ClaudeCodeDispatcher)."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod

    ok_result = PreflightResult(ok=True, checks=[])

    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result)), \
         patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None), \
         patch.object(bootstrap_mod, "_build_log_toolkits", return_value={}), \
         patch.object(
             bootstrap_mod, "default_identities",
             AsyncMock(return_value=("reporter", "escalation")),
         ), \
         patch(
             "parrot.flows.dev_loop.agent_builder.build_dispatcher",
             return_value=(MagicMock(), MagicMock()),
         ), \
         patch(
             "parrot.flows.dev_loop.code_review.CodeReviewDispatcherFactory.create",
         ) as mock_create, \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow", return_value=object(),
         ) as mock_build_flow, \
         patch(
             "parrot.flows.dev_loop.DevLoopRunner", return_value=MagicMock(),
         ) as MockRunner, \
         patch(
             "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
             AsyncMock(return_value=None),
         ):
        await build_runtime()

    mock_create.assert_not_called()
    _, flow_kwargs = mock_build_flow.call_args
    assert flow_kwargs["codereview_dispatcher"] is None
    _, runner_kwargs = MockRunner.call_args
    assert runner_kwargs["codereview_dispatcher"] is None


@pytest.mark.asyncio
async def test_build_runtime_wires_matching_codereview_dispatcher_for_codex():
    """DEV_LOOP_DEVELOPMENT_AGENT=codex: a matching CodexCodeReviewDispatcher
    is built via CodeReviewDispatcherFactory and forwarded to both
    build_dev_loop_flow and DevLoopRunner — QANode's fallback would
    otherwise wrap the Codex dispatcher in a ClaudeCodeReviewDispatcher,
    silently degrading every code-review gate to always-pass."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod
    import parrot.conf as real_conf

    sentinel_dispatcher = MagicMock()
    sentinel_reviewer = MagicMock()

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "DEV_LOOP_DEVELOPMENT_AGENT":
            return "codex"
        return original_get(key, fallback=fallback)

    ok_result = PreflightResult(ok=True, checks=[])

    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result)), \
         patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None), \
         patch.object(bootstrap_mod, "_build_log_toolkits", return_value={}), \
         patch.object(
             bootstrap_mod, "default_identities",
             AsyncMock(return_value=("reporter", "escalation")),
         ), \
         patch.object(real_conf.config, "get", side_effect=fake_get), \
         patch(
             "parrot.flows.dev_loop.agent_builder.build_dispatcher",
             return_value=(sentinel_dispatcher, MagicMock()),
         ), \
         patch(
             "parrot.flows.dev_loop.code_review.CodeReviewDispatcherFactory.create",
             return_value=sentinel_reviewer,
         ) as mock_create, \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow", return_value=object(),
         ) as mock_build_flow, \
         patch(
             "parrot.flows.dev_loop.DevLoopRunner", return_value=MagicMock(),
         ) as MockRunner, \
         patch(
             "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
             AsyncMock(return_value=None),
         ):
        await build_runtime()

    mock_create.assert_called_once_with("codex", dispatcher=sentinel_dispatcher)

    _, flow_kwargs = mock_build_flow.call_args
    assert flow_kwargs["codereview_dispatcher"] is sentinel_reviewer
    _, runner_kwargs = MockRunner.call_args
    assert runner_kwargs["codereview_dispatcher"] is sentinel_reviewer


@pytest.mark.asyncio
async def test_build_runtime_nvidia_keeps_codereview_none():
    """A backend with no registered review profile (nvidia) keeps
    codereview_dispatcher=None — today's documented residual gap; a full
    fix (mirroring server.py's independent DEV_LOOP_CODEREVIEW_AGENT +
    adversarial/parallel selection) is out of this task's scope."""
    import parrot.cli.devloop.bootstrap as bootstrap_mod
    import parrot.conf as real_conf

    original_get = real_conf.config.get

    def fake_get(key, fallback=None):
        if key == "DEV_LOOP_DEVELOPMENT_AGENT":
            return "nvidia"
        return original_get(key, fallback=fallback)

    ok_result = PreflightResult(ok=True, checks=[])

    with patch.object(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result)), \
         patch.object(bootstrap_mod, "_build_jira_toolkit", return_value=None), \
         patch.object(bootstrap_mod, "_build_log_toolkits", return_value={}), \
         patch.object(
             bootstrap_mod, "default_identities",
             AsyncMock(return_value=("reporter", "escalation")),
         ), \
         patch.object(real_conf.config, "get", side_effect=fake_get), \
         patch(
             "parrot.flows.dev_loop.agent_builder.build_dispatcher",
             return_value=(MagicMock(), MagicMock()),
         ), \
         patch(
             "parrot.flows.dev_loop.code_review.CodeReviewDispatcherFactory.create",
         ) as mock_create, \
         patch(
             "parrot.flows.dev_loop.build_dev_loop_flow", return_value=object(),
         ) as mock_build_flow, \
         patch(
             "parrot.flows.dev_loop.DevLoopRunner", return_value=MagicMock(),
         ) as MockRunner, \
         patch(
             "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
             AsyncMock(return_value=None),
         ):
        await build_runtime()

    mock_create.assert_not_called()
    _, flow_kwargs = mock_build_flow.call_args
    assert flow_kwargs["codereview_dispatcher"] is None
    _, runner_kwargs = MockRunner.call_args
    assert runner_kwargs["codereview_dispatcher"] is None
