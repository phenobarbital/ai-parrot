"""Integration tests for the granular permissions system.

Tests the full permission flow end-to-end:
- Session creation → Context building → Tool filtering → Execution enforcement

Covers:
- Layer 1 (preventive filtering in AbstractToolkit.get_tools)
- Layer 2 (reactive enforcement in AbstractTool.execute)
- ToolManager integration
- Backward compatibility
- Role hierarchy expansion
- OR permission semantics
"""

import pytest
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager
from parrot.tools.decorators import requires_permission
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver


# ── Test Toolkit ───────────────────────────────────────────────────────────────


class IntegrationToolkit(AbstractToolkit):
    """Toolkit for integration testing with mixed permission requirements."""

    async def public_action(self) -> str:
        """Available to everyone - no permission required."""
        return "public"

    @requires_permission('read')
    async def read_action(self) -> str:
        """Requires read permission."""
        return "read"

    @requires_permission('write')
    async def write_action(self) -> str:
        """Requires write permission."""
        return "write"

    @requires_permission('admin')
    async def admin_action(self) -> str:
        """Requires admin permission."""
        return "admin"

    @requires_permission('read', 'special')
    async def or_action(self) -> str:
        """Requires read OR special permission (OR semantics)."""
        return "or"


# ── Local Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def hierarchy():
    """Simple role hierarchy for these tests."""
    return {
        'admin': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    }


@pytest.fixture
def resolver(hierarchy):
    """Permission resolver with simple hierarchy."""
    return DefaultPermissionResolver(role_hierarchy=hierarchy)


@pytest.fixture
def toolkit():
    """Fresh integration toolkit instance."""
    return IntegrationToolkit()


# ── Integration Tests: Full Flow Deny ──────────────────────────────────────────


class TestFullFlowDeny:
    """Test complete denial flow: filter + execute."""

    @pytest.mark.asyncio
    async def test_layer1_filters_unauthorized_tool(self, toolkit, resolver):
        """Layer 1: unauthorized tools filtered from list."""
        session = UserSession(
            user_id="reader",
            tenant_id="t1",
            roles=frozenset({'read'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # Reader should see public and read tools
        assert 'public_action' in tool_names
        assert 'read_action' in tool_names
        assert 'or_action' in tool_names  # read matches OR

        # Reader should NOT see write or admin tools
        assert 'write_action' not in tool_names
        assert 'admin_action' not in tool_names

    @pytest.mark.asyncio
    async def test_layer2_blocks_if_slips_through(self, resolver):
        """Layer 2: direct execution blocked even if tool somehow bypassed filtering."""
        session = UserSession(
            user_id="reader",
            tenant_id="t1",
            roles=frozenset({'read'})
        )
        ctx = PermissionContext(session=session)

        @requires_permission('admin')
        class RestrictedTool(AbstractTool):
            name = "restricted"
            description = "Admin only"

            async def _execute(self, **kwargs):
                return ToolResult(
                    success=True,
                    status="success",
                    result="should not reach"
                )

        tool = RestrictedTool()
        result = await tool.execute(_permission_context=ctx, _resolver=resolver)

        assert result.success is False
        assert result.status == 'forbidden'
        assert 'Permission denied' in result.error

    @pytest.mark.asyncio
    async def test_forbidden_result_metadata(self, resolver):
        """Forbidden results include helpful metadata."""
        session = UserSession(user_id="u1", tenant_id="t1", roles=frozenset({'read'}))
        ctx = PermissionContext(session=session)

        @requires_permission('superadmin')
        class SuperTool(AbstractTool):
            name = "super_tool"
            description = "Super admin only"

            async def _execute(self, **kwargs):
                return "never"

        tool = SuperTool()
        result = await tool.execute(_permission_context=ctx, _resolver=resolver)

        assert result.metadata['tool_name'] == 'super_tool'
        assert result.metadata['user_id'] == 'u1'
        assert 'superadmin' in result.metadata['required_permissions']


# ── Integration Tests: Full Flow Allow ─────────────────────────────────────────


class TestFullFlowAllow:
    """Test complete allow flow: filter + execute."""

    @pytest.mark.asyncio
    async def test_admin_sees_all_tools(self, toolkit, resolver):
        """Admin sees all tools in filtered list."""
        session = UserSession(
            user_id="admin",
            tenant_id="t1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # Admin sees everything
        assert 'public_action' in tool_names
        assert 'read_action' in tool_names
        assert 'write_action' in tool_names
        assert 'admin_action' in tool_names
        assert 'or_action' in tool_names

    @pytest.mark.asyncio
    async def test_admin_can_execute_all(self, toolkit, resolver):
        """Admin can execute any tool through Layer 2."""
        session = UserSession(
            user_id="admin",
            tenant_id="t1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        admin_tool = next(t for t in tools if t.name == 'admin_action')

        result = await admin_tool.execute(_permission_context=ctx, _resolver=resolver)
        assert result.success is True
        assert result.result == "admin"

    @pytest.mark.asyncio
    async def test_writer_can_execute_write(self, toolkit, resolver):
        """Writer can execute write tools directly."""
        session = UserSession(
            user_id="writer",
            tenant_id="t1",
            roles=frozenset({'write'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        write_tool = next(t for t in tools if t.name == 'write_action')

        result = await write_tool.execute(_permission_context=ctx, _resolver=resolver)
        assert result.success is True
        assert result.result == "write"


# ── Integration Tests: Backward Compatibility ──────────────────────────────────


class TestBackwardCompatibility:
    """Test no context = no enforcement (backward compatible)."""

    @pytest.mark.asyncio
    async def test_no_context_returns_all_tools(self, toolkit):
        """Without context, all tools returned including restricted ones."""
        tools = await toolkit.get_tools()  # No context, no resolver

        tool_names = [t.name for t in tools]
        assert len(tool_names) >= 5  # all tools including restricted ones
        assert 'admin_action' in tool_names
        assert 'write_action' in tool_names

    @pytest.mark.asyncio
    async def test_no_context_executes_restricted(self):
        """Without context, restricted tools execute normally."""
        @requires_permission('super_admin')
        class SuperRestrictedTool(AbstractTool):
            name = "super_restricted"
            description = "Super admin only"

            async def _execute(self, **kwargs):
                return ToolResult(
                    success=True,
                    status="success",
                    result="executed"
                )

        tool = SuperRestrictedTool()
        result = await tool.execute()  # No context, no resolver

        assert result.success is True
        assert result.result == "executed"

    @pytest.mark.asyncio
    async def test_context_without_resolver_returns_all(self, toolkit):
        """Context but no resolver still returns all tools."""
        session = UserSession(user_id="u1", tenant_id="t1", roles=frozenset({'read'}))
        ctx = PermissionContext(session=session)

        # Only context, no resolver
        tools = await toolkit.get_tools(permission_context=ctx)

        tool_names = [t.name for t in tools]
        # Without resolver, all tools returned
        assert 'admin_action' in tool_names

    @pytest.mark.asyncio
    async def test_resolver_without_context_returns_all(self, toolkit, resolver):
        """Resolver but no context still returns all tools."""
        tools = await toolkit.get_tools(resolver=resolver)

        tool_names = [t.name for t in tools]
        # Without context, all tools returned
        assert 'admin_action' in tool_names


# ── Integration Tests: Role Hierarchy Expansion ────────────────────────────────


class TestHierarchyExpansion:
    """Test role hierarchy works correctly."""

    @pytest.mark.asyncio
    async def test_write_implies_read(self, toolkit, resolver):
        """User with write can access read tools through hierarchy."""
        session = UserSession(
            user_id="writer",
            tenant_id="t1",
            roles=frozenset({'write'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # write implies read
        assert 'read_action' in tool_names
        assert 'write_action' in tool_names
        assert 'public_action' in tool_names

        # but not admin
        assert 'admin_action' not in tool_names

    @pytest.mark.asyncio
    async def test_admin_implies_all(self, toolkit, resolver):
        """Admin role implies all lower permissions."""
        session = UserSession(
            user_id="admin",
            tenant_id="t1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # admin implies write, read
        assert 'admin_action' in tool_names
        assert 'write_action' in tool_names
        assert 'read_action' in tool_names

    @pytest.mark.asyncio
    async def test_hierarchy_in_layer2(self, resolver):
        """Hierarchy works in Layer 2 execution checks too."""
        session = UserSession(
            user_id="admin",
            tenant_id="t1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session)

        @requires_permission('read')
        class ReadTool(AbstractTool):
            name = "read_tool"
            description = "Read tool"

            async def _execute(self, **kwargs):
                return "read result"

        tool = ReadTool()
        result = await tool.execute(_permission_context=ctx, _resolver=resolver)

        # admin has read through hierarchy
        assert result.success is True
        assert result.result == "read result"


# ── Integration Tests: OR Permission Semantics ─────────────────────────────────


class TestOrSemantics:
    """Test OR permission matching (any permission grants access)."""

    @pytest.mark.asyncio
    async def test_or_matches_first_permission(self, toolkit, resolver):
        """Tool with OR permissions - first permission matches."""
        session = UserSession(
            user_id="reader",
            tenant_id="t1",
            roles=frozenset({'read'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # or_action requires 'read' OR 'special', reader has 'read'
        assert 'or_action' in tool_names

    @pytest.mark.asyncio
    async def test_or_matches_second_permission(self, toolkit, resolver):
        """Tool with OR permissions - second permission matches."""
        session = UserSession(
            user_id="special_user",
            tenant_id="t1",
            roles=frozenset({'special'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # or_action requires 'read' OR 'special', user has 'special'
        assert 'or_action' in tool_names

    @pytest.mark.asyncio
    async def test_or_fails_without_any(self, toolkit, resolver):
        """OR semantics - fails if no permission matches."""
        session = UserSession(
            user_id="other",
            tenant_id="t1",
            roles=frozenset({'other_role'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # only public_action visible (no permission required)
        assert 'or_action' not in tool_names
        assert 'public_action' in tool_names

    @pytest.mark.asyncio
    async def test_or_in_layer2_execution(self, resolver):
        """OR semantics work in Layer 2 execution too."""
        @requires_permission('perm_a', 'perm_b')
        class OrTool(AbstractTool):
            name = "or_tool"
            description = "OR tool"

            async def _execute(self, **kwargs):
                return "or result"

        tool = OrTool()

        # User with perm_a
        session_a = UserSession(user_id="a", tenant_id="t", roles=frozenset({'perm_a'}))
        ctx_a = PermissionContext(session=session_a)
        result_a = await tool.execute(_permission_context=ctx_a, _resolver=resolver)
        assert result_a.success is True

        # User with perm_b
        session_b = UserSession(user_id="b", tenant_id="t", roles=frozenset({'perm_b'}))
        ctx_b = PermissionContext(session=session_b)
        result_b = await tool.execute(_permission_context=ctx_b, _resolver=resolver)
        assert result_b.success is True

        # User with neither
        session_c = UserSession(user_id="c", tenant_id="t", roles=frozenset({'perm_c'}))
        ctx_c = PermissionContext(session=session_c)
        result_c = await tool.execute(_permission_context=ctx_c, _resolver=resolver)
        assert result_c.success is False
        assert result_c.status == 'forbidden'


# ── Integration Tests: ToolManager with Permissions ────────────────────────────


class TestToolManagerIntegration:
    """Test ToolManager with permission system."""

    @pytest.mark.asyncio
    async def test_manager_enforces_permissions(self, resolver):
        """ToolManager propagates context for Layer 2 enforcement."""
        session = UserSession(
            user_id="reader",
            tenant_id="t1",
            roles=frozenset({'read'})
        )
        ctx = PermissionContext(session=session)

        @requires_permission('admin')
        class AdminTool(AbstractTool):
            name = "admin_tool"
            description = "Admin only"

            async def _execute(self, **kwargs):
                return ToolResult(
                    success=True,
                    status="success",
                    result="admin"
                )

        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(AdminTool())

        result = await manager.execute_tool(
            'admin_tool',
            {},
            permission_context=ctx
        )

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.status == 'forbidden'

    @pytest.mark.asyncio
    async def test_manager_allows_permitted(self, resolver):
        """ToolManager allows execution when user has permission."""
        session = UserSession(
            user_id="admin",
            tenant_id="t1",
            roles=frozenset({'admin'})
        )
        ctx = PermissionContext(session=session)

        @requires_permission('admin')
        class AdminTool(AbstractTool):
            name = "admin_tool"
            description = "Admin only"

            async def _execute(self, **kwargs):
                return {"message": "admin result"}

        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(AdminTool())

        result = await manager.execute_tool(
            'admin_tool',
            {},
            permission_context=ctx
        )

        assert result['message'] == "admin result"

    @pytest.mark.asyncio
    async def test_manager_without_resolver_allows_all(self):
        """ToolManager without resolver allows all executions."""
        session = UserSession(
            user_id="reader",
            tenant_id="t1",
            roles=frozenset({'read'})
        )
        ctx = PermissionContext(session=session)

        @requires_permission('admin')
        class AdminTool(AbstractTool):
            name = "admin_tool"
            description = "Admin only"

            async def _execute(self, **kwargs):
                return {"message": "admin result"}

        # No resolver configured
        manager = ToolManager(include_search_tool=False)
        manager.add_tool(AdminTool())

        result = await manager.execute_tool(
            'admin_tool',
            {},
            permission_context=ctx
        )

        # No enforcement without resolver
        assert result['message'] == "admin result"


# ── Edge Cases ─────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases and unusual scenarios."""

    @pytest.mark.asyncio
    async def test_empty_roles(self, toolkit, resolver):
        """User with no roles sees only public tools."""
        session = UserSession(
            user_id="nobody",
            tenant_id="t1",
            roles=frozenset()  # Empty roles
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # Only public tool visible
        assert tool_names == ['public_action']

    @pytest.mark.asyncio
    async def test_unknown_permission_denied(self, resolver):
        """Tool with unknown permission is denied."""
        session = UserSession(
            user_id="u1",
            tenant_id="t1",
            roles=frozenset({'admin', 'write', 'read'})
        )
        ctx = PermissionContext(session=session)

        @requires_permission('unknown_permission')
        class UnknownTool(AbstractTool):
            name = "unknown_tool"
            description = "Unknown"

            async def _execute(self, **kwargs):
                return "should not reach"

        tool = UnknownTool()
        result = await tool.execute(_permission_context=ctx, _resolver=resolver)

        # Admin doesn't have 'unknown_permission'
        assert result.success is False
        assert result.status == 'forbidden'

    @pytest.mark.asyncio
    async def test_multiple_roles_user(self, toolkit, resolver):
        """User with multiple roles gets combined access."""
        session = UserSession(
            user_id="multi",
            tenant_id="t1",
            roles=frozenset({'read', 'special'})
        )
        ctx = PermissionContext(session=session)

        tools = await toolkit.get_tools(permission_context=ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        # Has read (direct) and special (for OR)
        assert 'public_action' in tool_names
        assert 'read_action' in tool_names
        assert 'or_action' in tool_names
        # But not write or admin
        assert 'write_action' not in tool_names
        assert 'admin_action' not in tool_names

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, resolver):
        """Different tenants are tracked in context."""
        session_t1 = UserSession(
            user_id="u1",
            tenant_id="tenant-1",
            roles=frozenset({'admin'})
        )
        session_t2 = UserSession(
            user_id="u1",  # Same user ID
            tenant_id="tenant-2",
            roles=frozenset({'admin'})
        )

        ctx_t1 = PermissionContext(session=session_t1)
        ctx_t2 = PermissionContext(session=session_t2)

        # Both contexts work independently
        assert ctx_t1.tenant_id == "tenant-1"
        assert ctx_t2.tenant_id == "tenant-2"
        assert ctx_t1.user_id == ctx_t2.user_id  # Same user across tenants

    @pytest.mark.asyncio
    async def test_unrestricted_tool_always_passes(self, resolver):
        """Unrestricted tool passes for any user."""
        session = UserSession(
            user_id="nobody",
            tenant_id="t1",
            roles=frozenset()  # No roles
        )
        ctx = PermissionContext(session=session)

        class UnrestrictedTool(AbstractTool):
            name = "unrestricted"
            description = "No permissions needed"

            async def _execute(self, **kwargs):
                return "open"

        tool = UnrestrictedTool()
        result = await tool.execute(_permission_context=ctx, _resolver=resolver)

        assert result.success is True
        assert result.result == "open"
