"""Tests for ExecutionPolicy / ExecutorSpec / build_executor.

Covers rule-matching precedence, spec-level executor caching, the
"explicit executor wins" contract, ToolManager integration, and
lifecycle (close) behaviour.
"""
from __future__ import annotations

import pytest

from parrot.tools.executors import LocalToolExecutor
from parrot.tools.executors.policy import (
    EXECUTOR_REGISTRY,
    ExecutionPolicy,
    ExecutorSpec,
    build_executor,
)

from ._fixtures import ClosableExecutor, EchoTool, GreetingToolkit

_CLOSABLE_PATH = "tests.tools.executors._fixtures:ClosableExecutor"


# ── ExecutorSpec coercion ────────────────────────────────────────────


def test_spec_accepts_string_shorthand():
    spec = ExecutorSpec.model_validate("local")
    assert spec.name == "local"
    assert spec.options == {}


def test_spec_accepts_live_instance():
    ex = ClosableExecutor()
    spec = ExecutorSpec.model_validate(ex)
    assert spec.instance is ex


def test_spec_requires_name_or_instance():
    with pytest.raises(Exception):
        ExecutorSpec.model_validate({})


# ── build_executor ───────────────────────────────────────────────────


def test_build_executor_local():
    ex = build_executor("local")
    assert isinstance(ex, LocalToolExecutor)


def test_build_executor_unknown_name():
    with pytest.raises(KeyError, match="Unknown executor"):
        build_executor("teleport")


def test_build_executor_reserved_docker_sandbox():
    with pytest.raises(NotImplementedError, match="reserved"):
        build_executor("docker-sandbox")


def test_build_executor_passes_options(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    ex = build_executor(ExecutorSpec(name="closable", options={"tag": "x"}))
    # NOTE: compared by name, not isinstance — pytest can import the
    # fixtures module under two identities (relative vs registry path).
    assert type(ex).__name__ == "ClosableExecutor"
    assert ex.kwargs == {"tag": "x"}


# ── rule matching precedence ─────────────────────────────────────────


def _policy(rules: dict) -> ExecutionPolicy:
    return ExecutionPolicy.model_validate({"rules": rules})


def test_exact_tool_name_wins_over_everything():
    a, b, c = ClosableExecutor(), ClosableExecutor(), ClosableExecutor()
    policy = _policy({"echo_tool": a, "echo_*": b, "*": c})
    key, spec = policy.match(EchoTool())
    assert key == "echo_tool"
    assert spec.instance is a


def test_toolkit_name_matches_generated_tools():
    a, b = ClosableExecutor(), ClosableExecutor()
    policy = _policy({"GreetingToolkit": a, "greeting_*": b})
    toolkit = GreetingToolkit()
    hello = next(t for t in toolkit.get_tools() if t.name == "greeting_hello")
    key, spec = policy.match(hello)
    assert key == "GreetingToolkit"
    assert spec.instance is a


def test_toolkit_prefix_also_matches():
    a = ClosableExecutor()
    policy = _policy({"greeting": a})  # tool_prefix of GreetingToolkit
    toolkit = GreetingToolkit()
    hello = next(t for t in toolkit.get_tools() if t.name == "greeting_hello")
    key, _ = policy.match(hello)
    assert key == "greeting"


def test_wildcard_matches_tool_name():
    a = ClosableExecutor()
    policy = _policy({"greeting_*": a})
    toolkit = GreetingToolkit()
    add = next(t for t in toolkit.get_tools() if t.name == "greeting_add")
    key, _ = policy.match(add)
    assert key == "greeting_*"


def test_catch_all_and_no_match():
    a = ClosableExecutor()
    policy = _policy({"*": a})
    key, _ = policy.match(EchoTool())
    assert key == "*"
    assert _policy({"other_tool": a}).match(EchoTool()) is None


# ── resolution & application ─────────────────────────────────────────


def test_spec_instances_are_cached_per_rule(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    policy = _policy({"*": {"name": "closable"}})
    toolkit = GreetingToolkit()
    tools = toolkit.get_tools()
    resolved = {id(policy.resolve(t)) for t in tools}
    assert len(resolved) == 1  # one executor shared by every match


def test_apply_to_tool_sets_executor_and_overrides(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    policy = _policy(
        {
            "echo_tool": {
                "name": "closable",
                "remote_timeout_seconds": 42,
                "webhook_callback_url": "https://cb.example/hook",
            }
        }
    )
    tool = EchoTool()
    assert policy.apply_to_tool(tool) is True
    assert type(tool.executor).__name__ == "ClosableExecutor"
    assert tool.remote_timeout_seconds == 42
    assert tool.webhook_callback_url == "https://cb.example/hook"


def test_explicit_executor_wins_over_policy():
    mine = ClosableExecutor()
    other = ClosableExecutor()
    policy = _policy({"*": other})
    tool = EchoTool(executor=mine)
    assert policy.apply_to_tool(tool) is False
    assert tool.executor is mine


@pytest.mark.asyncio
async def test_policy_close_closes_built_instances_not_user_ones(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    user_owned = ClosableExecutor()
    policy = _policy({"echo_tool": {"name": "closable"}, "*": user_owned})
    built = policy.resolve(EchoTool())
    assert type(built).__name__ == "ClosableExecutor"

    await policy.close()
    assert built.closed is True
    assert user_owned.closed is False
    # Idempotent.
    await policy.close()


# ── ToolManager integration ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_manager_applies_policy_at_registration(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    from parrot.tools.manager import ToolManager

    tm = ToolManager(
        execution_policy={"rules": {"echo_tool": {"name": "closable"}}}
    )
    tool = EchoTool()
    tm.register_tool(tool)
    assert type(tool.executor).__name__ == "ClosableExecutor"

    # The routed tool actually dispatches through the executor.
    result = await tool.execute(msg="hi")
    assert result.result == "from-closable"
    assert len(tool.executor.envelopes) == 1

    await tm.close_executors()
    assert tool.executor.closed is True


def test_tool_manager_set_policy_applies_to_registered_tools(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    from parrot.tools.manager import ToolManager

    tm = ToolManager()
    tool = EchoTool()
    tm.register_tool(tool)
    assert tool.executor is None

    tm.set_execution_policy({"rules": {"echo_*": "closable"}})
    assert type(tool.executor).__name__ == "ClosableExecutor"


def test_tool_manager_applies_policy_to_toolkits(monkeypatch):
    monkeypatch.setitem(EXECUTOR_REGISTRY, "closable", _CLOSABLE_PATH)
    from parrot.tools.manager import ToolManager

    tm = ToolManager(
        execution_policy={"rules": {"GreetingToolkit": {"name": "closable"}}}
    )
    registered = tm.register_toolkit(GreetingToolkit())
    assert registered
    executors = {id(t.executor) for t in registered}
    assert len(executors) == 1  # shared instance across the toolkit
    assert all(type(t.executor).__name__ == "ClosableExecutor" for t in registered)


def test_tool_manager_rejects_bad_policy_type():
    from parrot.tools.manager import ToolManager

    with pytest.raises(TypeError):
        ToolManager(execution_policy=42)
