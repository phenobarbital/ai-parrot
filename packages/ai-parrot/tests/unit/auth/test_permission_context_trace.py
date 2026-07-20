"""Unit tests for PermissionContext.trace_context field (TASK-1185, FEAT-176).

The ``trace_context`` field carries a W3C-compatible TraceContext so that
lifecycle events can propagate trace identity across agent → tool and
agent → sub-agent boundaries.  It must default to ``None`` and remain fully
backward compatible.
"""
from __future__ import annotations

import pytest

from parrot.auth.permission import PermissionContext, UserSession
from navigator_eventbus.lifecycle.trace import TraceContext


@pytest.fixture
def session() -> UserSession:
    """Minimal UserSession fixture for PermissionContext construction."""
    return UserSession(
        user_id="user-trace-1",
        tenant_id="acme-corp",
        roles=frozenset({"jira.write"}),
    )


class TestPermissionContextTrace:
    def test_default_is_none(self, session: UserSession) -> None:
        """PermissionContext constructed without trace_context defaults to None."""
        pctx = PermissionContext(session=session)
        assert pctx.trace_context is None

    def test_accepts_trace_context(self, session: UserSession) -> None:
        """PermissionContext stores and returns the provided TraceContext."""
        ctx = TraceContext.new_root()
        pctx = PermissionContext(session=session, trace_context=ctx)
        assert pctx.trace_context is ctx

    def test_trace_context_identity_preserved(self, session: UserSession) -> None:
        """The exact same TraceContext instance is returned, not a copy."""
        ctx = TraceContext.new_root()
        pctx = PermissionContext(session=session, trace_context=ctx)
        assert pctx.trace_context.trace_id == ctx.trace_id
        assert pctx.trace_context.span_id == ctx.span_id

    def test_existing_fields_unchanged(self, session: UserSession) -> None:
        """Adding trace_context does not affect other fields or their defaults."""
        pctx = PermissionContext(
            session=session,
            request_id="req-1",
            channel="cli",
        )
        assert pctx.request_id == "req-1"
        assert pctx.channel == "cli"
        assert pctx.trace_context is None
        assert pctx.extra == {}

    def test_all_fields_together(self, session: UserSession) -> None:
        """All fields can be set simultaneously without conflict."""
        ctx = TraceContext.new_root()
        pctx = PermissionContext(
            session=session,
            request_id="req-42",
            channel="telegram",
            trace_context=ctx,
            extra={"ip": "10.0.0.1"},
        )
        assert pctx.session is session
        assert pctx.request_id == "req-42"
        assert pctx.channel == "telegram"
        assert pctx.trace_context is ctx
        assert pctx.extra == {"ip": "10.0.0.1"}

    def test_trace_context_is_mutable(self, session: UserSession) -> None:
        """PermissionContext is a regular (mutable) dataclass — field can be reassigned."""
        ctx1 = TraceContext.new_root()
        ctx2 = ctx1.child()
        pctx = PermissionContext(session=session, trace_context=ctx1)
        pctx.trace_context = ctx2
        assert pctx.trace_context is ctx2

    def test_child_trace_context(self, session: UserSession) -> None:
        """A child TraceContext shares trace_id with parent but has its own span_id."""
        root_ctx = TraceContext.new_root()
        child_ctx = root_ctx.child()
        pctx = PermissionContext(session=session, trace_context=child_ctx)
        assert pctx.trace_context.trace_id == root_ctx.trace_id
        assert pctx.trace_context.span_id != root_ctx.span_id
        assert pctx.trace_context.parent_span_id == root_ctx.span_id
