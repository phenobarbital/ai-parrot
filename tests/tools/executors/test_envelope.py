"""Tests for ToolExecutionEnvelope construction and projection helpers."""
from __future__ import annotations

import pytest

from parrot.tools.executors.abstract import (
    ToolExecutionEnvelope,
    build_envelope_from_tool,
    project_permission_context,
    project_trace_context,
)
from parrot.tools.executors import LocalToolExecutor

from ._fixtures import EchoTool, GreetingToolkit


def test_envelope_roundtrips_through_json():
    """Envelopes survive JSON serialization unchanged."""
    env = ToolExecutionEnvelope(
        tool_import_path="parrot.tools.x:Y",
        tool_init_kwargs={"name": "y"},
        arguments={"q": 1},
        timeout_seconds=42,
    )
    parsed = ToolExecutionEnvelope.model_validate_json(env.model_dump_json())
    assert parsed == env


def test_build_envelope_strips_executor_from_init_kwargs():
    """Live executor references must not travel in the envelope."""
    tool = EchoTool(executor=LocalToolExecutor())
    env = build_envelope_from_tool(tool, arguments={"msg": "hi"})
    assert env.tool_import_path.endswith(":EchoTool")
    assert "executor" not in env.tool_init_kwargs
    assert env.tool_init_kwargs.get("name") is None or "name" in env.tool_init_kwargs
    assert env.arguments == {"msg": "hi"}
    assert env.method_name is None


def test_build_envelope_for_toolkit_method_records_method_name():
    """Toolkit-bound tools reference the toolkit class + the method."""
    toolkit = GreetingToolkit(executor=LocalToolExecutor())
    tools = toolkit.get_tools()
    hello = next(t for t in tools if t.name == "greeting_hello")
    env = build_envelope_from_tool(hello, arguments={"name": "alice"})
    # Toolkit import path, not ToolkitTool's, because the worker has to
    # reconstruct the *toolkit* instance to bind the method properly.
    assert env.tool_import_path.endswith(":GreetingToolkit")
    assert env.method_name == "hello"
    assert env.arguments == {"name": "alice"}


def test_project_trace_context_returns_none_for_none():
    assert project_trace_context(None) is None


def test_project_trace_context_projects_fields():
    from parrot.core.events.lifecycle.trace import TraceContext

    tc = TraceContext.new_root()
    projected = project_trace_context(tc)
    assert projected["trace_id"] == tc.trace_id
    assert projected["span_id"] == tc.span_id
    assert projected["parent_span_id"] is None


def test_project_permission_context_returns_none_for_none():
    assert project_permission_context(None) is None


def test_project_permission_context_serializes_session():
    from parrot.auth.permission import PermissionContext, UserSession

    session = UserSession(
        user_id="u1",
        tenant_id="t1",
        roles=frozenset({"admin", "user"}),
    )
    ctx = PermissionContext(
        session=session,
        request_id="r1",
        channel="cli",
        extra={"src": "test"},
    )
    projected = project_permission_context(ctx)
    assert projected["session"]["user_id"] == "u1"
    assert projected["session"]["tenant_id"] == "t1"
    assert projected["session"]["roles"] == ["admin", "user"]
    assert projected["request_id"] == "r1"
    assert projected["channel"] == "cli"
    assert projected["extra"] == {"src": "test"}
