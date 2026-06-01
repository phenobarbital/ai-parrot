"""Tests for the grant subsystem (FEAT-211 — Tool Grants & Bounded Approval Windows).

Covers:
  - TASK-1403: Grant, GrantConfig, GrantStore, InMemoryGrantStore
  - TASK-1404: GrantGuard, GuardDecision
  - TASK-1405: ToolManager grant guard integration
  - TASK-1406: parrot.auth exports
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot.auth.grants import (
    Grant,
    GrantConfig,
    GrantStore,
    InMemoryGrantStore,
    GrantGuard,
    GuardDecision,
)
from parrot.human.models import InteractionResult, InteractionStatus


# ── TASK-1403: Grant model tests ───────────────────────────────────────────────


class TestGrant:
    """Unit tests for the Grant Pydantic model."""

    def test_grant_is_active_within_window(self):
        """Grant is active before expires_at and not revoked."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1",
            scope="tool:deploy",
            granted_by="admin",
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )
        assert g.is_active(now + timedelta(minutes=5)) is True

    def test_grant_is_active_expired(self):
        """Grant is inactive after expires_at."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1",
            scope="tool:deploy",
            granted_by="admin",
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )
        assert g.is_active(now + timedelta(minutes=20)) is False

    def test_grant_is_active_revoked(self):
        """Revoked grant is inactive even within window."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1",
            scope="tool:deploy",
            granted_by="admin",
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            revoked=True,
        )
        assert g.is_active(now + timedelta(minutes=5)) is False

    def test_grant_is_active_default_now(self):
        """is_active() defaults to UTC now when no argument given."""
        now = datetime.now(timezone.utc)
        g = Grant(
            owner_id="user-1",
            scope="tool:deploy",
            granted_by="admin",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert g.is_active() is True  # within window

    def test_grant_covers_exact_scope(self):
        """Grant covers its exact scope."""
        g = Grant(
            owner_id="u",
            scope="tool:deploy",
            granted_by="a",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        assert g.covers("tool:deploy") is True
        assert g.covers("tool:delete") is False

    def test_grant_covers_wildcard(self):
        """Wildcard scope covers any tool scope."""
        g = Grant(
            owner_id="u",
            scope="tool:*",
            granted_by="a",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        assert g.covers("tool:deploy") is True
        assert g.covers("tool:anything") is True
        assert g.covers("tool:delete") is True

    def test_grant_id_auto_generated(self):
        """grant_id is auto-generated and unique."""
        now = datetime.now(timezone.utc)
        g1 = Grant(
            owner_id="u",
            scope="tool:a",
            granted_by="x",
            created_at=now,
            expires_at=now + timedelta(minutes=1),
        )
        g2 = Grant(
            owner_id="u",
            scope="tool:a",
            granted_by="x",
            created_at=now,
            expires_at=now + timedelta(minutes=1),
        )
        assert g1.grant_id != g2.grant_id


# ── TASK-1403: InMemoryGrantStore tests ───────────────────────────────────────


@pytest.mark.asyncio
class TestInMemoryGrantStore:
    """Unit tests for InMemoryGrantStore."""

    async def test_grant_and_is_allowed(self):
        """grant() creates entry; is_allowed() returns True within window."""
        store = InMemoryGrantStore()
        grant = await store.grant(
            "user-1", "tool:deploy", granted_by="admin", window_seconds=900
        )
        assert grant.owner_id == "user-1"
        assert grant.scope == "tool:deploy"
        assert await store.is_allowed("user-1", "tool:deploy") is True

    async def test_is_allowed_false_after_expiry(self):
        """is_allowed() returns False after grant expires (window_seconds=0)."""
        store = InMemoryGrantStore()
        await store.grant(
            "user-1", "tool:deploy", granted_by="admin", window_seconds=0
        )
        # window_seconds=0 → expires_at == created_at → immediately expired
        assert await store.is_allowed("user-1", "tool:deploy") is False

    async def test_is_allowed_false_for_different_owner(self):
        """Grant is not valid for a different owner."""
        store = InMemoryGrantStore()
        await store.grant(
            "user-1", "tool:deploy", granted_by="admin", window_seconds=900
        )
        assert await store.is_allowed("user-2", "tool:deploy") is False

    async def test_is_allowed_false_for_different_scope(self):
        """Grant is not valid for a different scope (no wildcard)."""
        store = InMemoryGrantStore()
        await store.grant(
            "user-1", "tool:deploy", granted_by="admin", window_seconds=900
        )
        assert await store.is_allowed("user-1", "tool:delete") is False

    async def test_is_allowed_with_wildcard_grant(self):
        """Wildcard grant covers any scope for the owner."""
        store = InMemoryGrantStore()
        await store.grant(
            "user-1", "tool:*", granted_by="admin", window_seconds=900
        )
        assert await store.is_allowed("user-1", "tool:deploy") is True
        assert await store.is_allowed("user-1", "tool:destroy") is True

    async def test_revoke_invalidates_grant(self):
        """revoke() marks grant as revoked; is_allowed() returns False."""
        store = InMemoryGrantStore()
        grant = await store.grant(
            "user-1", "tool:deploy", granted_by="admin", window_seconds=900
        )
        assert await store.revoke(grant.grant_id) is True
        assert await store.is_allowed("user-1", "tool:deploy") is False

    async def test_revoke_unknown_grant_returns_false(self):
        """revoke() returns False for an unknown grant_id."""
        store = InMemoryGrantStore()
        assert await store.revoke("nonexistent-id") is False

    async def test_list_active_filters_expired_and_revoked(self):
        """list_active() only returns non-expired, non-revoked grants."""
        store = InMemoryGrantStore()
        g1 = await store.grant(
            "user-1", "tool:a", granted_by="admin", window_seconds=900
        )
        # Expired immediately
        await store.grant(
            "user-1", "tool:b", granted_by="admin", window_seconds=0
        )
        active = await store.list_active("user-1")
        assert len(active) == 1
        assert active[0].grant_id == g1.grant_id

    async def test_list_active_excludes_other_owners(self):
        """list_active() only returns grants for the specified owner."""
        store = InMemoryGrantStore()
        await store.grant("user-1", "tool:a", granted_by="admin", window_seconds=900)
        await store.grant("user-2", "tool:b", granted_by="admin", window_seconds=900)
        active = await store.list_active("user-1")
        assert len(active) == 1
        assert active[0].owner_id == "user-1"

    async def test_cleanup_removes_expired(self):
        """cleanup() removes expired/revoked grants from memory."""
        store = InMemoryGrantStore()
        g1 = await store.grant(
            "user-1", "tool:a", granted_by="admin", window_seconds=900
        )
        await store.grant(
            "user-1", "tool:b", granted_by="admin", window_seconds=0
        )
        removed = await store.cleanup()
        assert removed == 1
        assert g1.grant_id in store._grants  # still active grant remains


# ── TASK-1404: GrantGuard tests ───────────────────────────────────────────────


def _make_tool(name: str = "pulumi_apply", requires_grant: bool = True, **extra_meta):
    """Create a mock tool with routing_meta."""
    tool = MagicMock()
    tool.name = name
    tool.routing_meta = {"requires_grant": requires_grant, **extra_meta}
    return tool


def _make_pctx(user_id: str = "user-1", channel: str = "telegram"):
    """Create a mock PermissionContext."""
    pctx = MagicMock()
    pctx.user_id = user_id
    pctx.channel = channel
    return pctx


def _approve_manager():
    """Create a mock HumanInteractionManager that always approves."""
    m = MagicMock()

    async def _req(interaction, channel="telegram"):
        return InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
            consolidated_value=True,
        )

    m.request_human_input = AsyncMock(side_effect=_req)
    return m


def _reject_manager():
    """Create a mock HumanInteractionManager that always rejects."""
    m = MagicMock()

    async def _req(interaction, channel="telegram"):
        return InteractionResult(
            interaction_id=interaction.interaction_id,
            status=InteractionStatus.COMPLETED,
            consolidated_value=False,
        )

    m.request_human_input = AsyncMock(side_effect=_req)
    return m


@pytest.mark.asyncio
class TestGrantGuard:
    """Unit tests for GrantGuard (the Governor)."""

    async def test_non_gated_tool_allowed(self):
        """Tool without requires_grant passes through immediately."""
        store = InMemoryGrantStore()
        guard = GrantGuard(store)
        tool = _make_tool(requires_grant=False)
        decision = await guard.authorize(
            tool=tool, parameters={}, permission_context=None
        )
        assert decision.allowed is True

    async def test_allows_with_active_grant(self):
        """Existing active grant → allowed without HITL."""
        store = InMemoryGrantStore()
        await store.grant(
            "user-1", "tool:pulumi_apply", granted_by="admin", window_seconds=900
        )
        guard = GrantGuard(store)
        decision = await guard.authorize(
            tool=_make_tool(),
            parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is True

    async def test_requests_approval_then_grants(self):
        """No grant + approve → creates grant, allows; 2nd call no re-ask."""
        store = InMemoryGrantStore()
        hm = _approve_manager()
        guard = GrantGuard(store, human_manager=hm)
        pctx = _make_pctx()
        tool = _make_tool()

        d1 = await guard.authorize(tool=tool, parameters={}, permission_context=pctx)
        assert d1.allowed is True
        assert hm.request_human_input.call_count == 1

        # Second call within window — no re-ask
        d2 = await guard.authorize(tool=tool, parameters={}, permission_context=pctx)
        assert d2.allowed is True
        assert hm.request_human_input.call_count == 1  # still 1

    async def test_denied_on_reject(self):
        """HITL rejects → denied, no grant created."""
        store = InMemoryGrantStore()
        hm = _reject_manager()
        guard = GrantGuard(store, human_manager=hm)

        decision = await guard.authorize(
            tool=_make_tool(),
            parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is False
        assert await store.is_allowed("user-1", "tool:pulumi_apply") is False

    async def test_failclosed_no_channel(self):
        """requires_grant + no grant + no human_manager → fail-closed."""
        store = InMemoryGrantStore()
        guard = GrantGuard(store, human_manager=None)

        decision = await guard.authorize(
            tool=_make_tool(),
            parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is False

    async def test_none_permission_context_uses_anonymous(self):
        """None permission_context uses 'anonymous' as owner_id (fail-closed)."""
        store = InMemoryGrantStore()
        guard = GrantGuard(store, human_manager=None)

        decision = await guard.authorize(
            tool=_make_tool(),
            parameters={},
            permission_context=None,
        )
        assert decision.allowed is False

    async def test_custom_grant_scope_from_routing_meta(self):
        """grant_scope in routing_meta overrides the default tool:{name} scope."""
        store = InMemoryGrantStore()
        # Grant covers the custom scope
        await store.grant(
            "user-1", "tool:pulumi:write", granted_by="admin", window_seconds=900
        )
        guard = GrantGuard(store)
        tool = _make_tool(name="pulumi_apply", grant_scope="tool:pulumi:write")

        decision = await guard.authorize(
            tool=tool,
            parameters={},
            permission_context=_make_pctx(),
        )
        assert decision.allowed is True

    async def test_grant_window_from_routing_meta(self):
        """grant_window_seconds in routing_meta overrides config default."""
        store = InMemoryGrantStore()
        hm = _approve_manager()
        # Use a short window via routing_meta
        guard = GrantGuard(store, human_manager=hm, config=GrantConfig(window_seconds=900))
        tool = _make_tool(grant_window_seconds=60)

        await guard.authorize(
            tool=tool, parameters={}, permission_context=_make_pctx()
        )
        # A grant should exist
        active = await store.list_active("user-1")
        assert len(active) == 1


# ── TASK-1405: ToolManager integration tests ─────────────────────────────────


@pytest.mark.asyncio
class TestToolManagerGrantIntegration:
    """Integration tests for ToolManager grant guard gating."""

    async def test_no_guard_unaffected(self):
        """Without guard configured, tools with requires_grant execute normally."""
        from parrot.tools.manager import ToolManager
        from parrot.tools.abstract import ToolResult

        tm = ToolManager()
        tool = MagicMock()
        tool.name = "pulumi_apply"
        tool.routing_meta = {"requires_grant": True}
        tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="deployed"
        ))
        tm.register_tool(tool)

        result = await tm.execute_tool("pulumi_apply", {})
        # No guard → tool executes normally
        tool.execute.assert_called_once()

    async def test_gates_requires_grant_approved(self):
        """Guard approves (active grant) → tool executes normally."""
        from parrot.tools.manager import ToolManager
        from parrot.tools.abstract import ToolResult

        tm = ToolManager()
        store = InMemoryGrantStore()
        await store.grant(
            "user-1", "tool:pulumi_apply", granted_by="admin", window_seconds=900
        )
        guard = GrantGuard(store, human_manager=None)
        tm.set_grant_guard(guard)

        tool = MagicMock()
        tool.name = "pulumi_apply"
        tool.routing_meta = {"requires_grant": True}
        tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="deployed"
        ))
        tm.register_tool(tool)

        pctx = MagicMock()
        pctx.user_id = "user-1"
        pctx.channel = None
        result = await tm.execute_tool("pulumi_apply", {}, permission_context=pctx)
        tool.execute.assert_called_once()

    async def test_denied_returns_forbidden(self):
        """Guard denies → execute_tool returns ToolResult(status='forbidden')."""
        from parrot.tools.manager import ToolManager
        from parrot.tools.abstract import ToolResult

        tm = ToolManager()
        store = InMemoryGrantStore()
        guard = GrantGuard(store, human_manager=None)  # no HITL → fail-closed
        tm.set_grant_guard(guard)

        tool = MagicMock()
        tool.name = "pulumi_apply"
        tool.routing_meta = {"requires_grant": True}
        tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="deployed"
        ))
        tm.register_tool(tool)

        pctx = MagicMock()
        pctx.user_id = "user-1"
        pctx.channel = None
        result = await tm.execute_tool("pulumi_apply", {}, permission_context=pctx)
        assert isinstance(result, ToolResult)
        assert result.status == "forbidden"
        tool.execute.assert_not_called()

    async def test_non_gated_tool_passes_with_guard(self):
        """With guard set, tools without requires_grant still execute normally."""
        from parrot.tools.manager import ToolManager
        from parrot.tools.abstract import ToolResult

        tm = ToolManager()
        store = InMemoryGrantStore()
        guard = GrantGuard(store, human_manager=None)
        tm.set_grant_guard(guard)

        tool = MagicMock()
        tool.name = "safe_tool"
        tool.routing_meta = {}  # no requires_grant
        tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="safe_result"
        ))
        tm.register_tool(tool)

        pctx = MagicMock()
        pctx.user_id = "user-1"
        pctx.channel = None
        result = await tm.execute_tool("safe_tool", {}, permission_context=pctx)
        tool.execute.assert_called_once()


# ── TASK-1406: Export smoke test ──────────────────────────────────────────────


def test_grant_exports():
    """All grant types are importable from parrot.auth."""
    from parrot.auth import (
        Grant,
        GrantConfig,
        GrantStore,
        InMemoryGrantStore,
        GrantGuard,
        GuardDecision,
    )
    assert Grant is not None
    assert GrantConfig is not None
    assert GrantStore is not None
    assert InMemoryGrantStore is not None
    assert GrantGuard is not None
    assert GuardDecision is not None
