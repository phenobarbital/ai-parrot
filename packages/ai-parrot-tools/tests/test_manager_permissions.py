"""Unit tests for ToolManager permission resolver injection.

Tests Module 7 of the granular permissions system:
- Resolver injection at init
- Runtime resolver swapping
- Permission context propagation to tools
- Backward compatibility (no resolver = no enforcement)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.resolver import AbstractPermissionResolver, DefaultPermissionResolver
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.decorators import requires_permission, tool
from parrot.tools.manager import ToolManager

# ── Test Fixtures ──────────────────────────────────────────────────────────────


class MockTool(AbstractTool):
    """Unrestricted mock tool for testing."""

    name = "mock_tool"
    description = "Mock tool for testing"

    async def _execute(self, **kwargs):
        return {"message": "mock result", "kwargs": kwargs}


@requires_permission('admin')
class AdminTool(AbstractTool):
    """Admin-only mock tool for testing."""

    name = "admin_tool"
    description = "Admin only tool"

    async def _execute(self, **kwargs):
        return {"message": "admin result", "kwargs": kwargs}


@requires_permission('write')
class WriteTool(AbstractTool):
    """Write permission mock tool."""

    name = "write_tool"
    description = "Write permission tool"

    async def _execute(self, **kwargs):
        return {"message": "write result"}


@pytest.fixture
def role_hierarchy():
    """Standard test role hierarchy."""
    return {
        'admin': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    }


@pytest.fixture
def resolver(role_hierarchy):
    """Default permission resolver with hierarchy."""
    return DefaultPermissionResolver(role_hierarchy=role_hierarchy)


@pytest.fixture
def admin_context():
    """Permission context for admin user."""
    session = UserSession(
        user_id="admin-user",
        tenant_id="test-tenant",
        roles=frozenset({'admin'})
    )
    return PermissionContext(session=session)


@pytest.fixture
def reader_context():
    """Permission context for reader-only user."""
    session = UserSession(
        user_id="reader-user",
        tenant_id="test-tenant",
        roles=frozenset({'read'})
    )
    return PermissionContext(session=session)


@pytest.fixture
def writer_context():
    """Permission context for writer user."""
    session = UserSession(
        user_id="writer-user",
        tenant_id="test-tenant",
        roles=frozenset({'write'})
    )
    return PermissionContext(session=session)


# ── Test: ToolManager Init ─────────────────────────────────────────────────────


class TestToolManagerInit:
    """Tests for ToolManager initialization with resolver."""

    def test_init_without_resolver(self):
        """Manager can initialize without resolver (backward compat)."""
        manager = ToolManager(include_search_tool=False)
        assert manager.resolver is None

    def test_init_with_resolver(self, resolver):
        """Manager accepts resolver at init."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        assert manager.resolver is resolver

    def test_resolver_property_returns_resolver(self, resolver):
        """resolver property returns the configured resolver."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        assert manager.resolver is resolver
        assert isinstance(manager.resolver, DefaultPermissionResolver)


class TestToolManagerSetResolver:
    """Tests for set_resolver() method."""

    def test_set_resolver_from_none(self, resolver):
        """set_resolver works when starting from None."""
        manager = ToolManager(include_search_tool=False)
        assert manager.resolver is None

        manager.set_resolver(resolver)
        assert manager.resolver is resolver

    def test_set_resolver_swaps_resolver(self, role_hierarchy):
        """set_resolver swaps resolver at runtime."""
        resolver1 = DefaultPermissionResolver(role_hierarchy=role_hierarchy)
        resolver2 = DefaultPermissionResolver(role_hierarchy={'other': set()})

        manager = ToolManager(resolver=resolver1, include_search_tool=False)
        assert manager.resolver is resolver1

        manager.set_resolver(resolver2)
        assert manager.resolver is resolver2
        assert manager.resolver is not resolver1


# ── Test: execute_tool Permission Propagation ──────────────────────────────────


class TestToolManagerExecuteWithoutContext:
    """Tests for execute_tool without permission context (backward compat)."""

    @pytest.mark.asyncio
    async def test_execute_without_context_runs_normally(self):
        """Execute without context runs tool normally."""
        manager = ToolManager(include_search_tool=False)
        manager.add_tool(MockTool())

        result = await manager.execute_tool('mock_tool', {})

        assert result is not None
        assert result['message'] == "mock result"

    @pytest.mark.asyncio
    async def test_execute_restricted_without_context_succeeds(self):
        """Restricted tool executes when no context provided."""
        manager = ToolManager(include_search_tool=False)
        manager.add_tool(AdminTool())

        # No context means no enforcement
        result = await manager.execute_tool('admin_tool', {})

        assert result is not None
        assert result['message'] == "admin result"

    @pytest.mark.asyncio
    async def test_execute_not_found_returns_tool_result(self):
        """Execute non-existent tool returns not_found ToolResult."""
        manager = ToolManager(include_search_tool=False)

        result = await manager.execute_tool('nonexistent', {})

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.status == 'not_found'
        assert 'nonexistent' in result.error


class TestToolManagerExecuteWithPermission:
    """Tests for execute_tool with permission enforcement."""

    @pytest.mark.asyncio
    async def test_execute_admin_allowed(self, resolver, admin_context):
        """Admin can execute admin-only tool."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(AdminTool())

        result = await manager.execute_tool(
            'admin_tool',
            {},
            permission_context=admin_context
        )

        assert result is not None
        assert result['message'] == "admin result"

    @pytest.mark.asyncio
    async def test_execute_admin_denied(self, resolver, reader_context):
        """Reader cannot execute admin-only tool."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(AdminTool())

        result = await manager.execute_tool(
            'admin_tool',
            {},
            permission_context=reader_context
        )

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.status == 'forbidden'

    @pytest.mark.asyncio
    async def test_execute_hierarchy_allowed(self, resolver, admin_context):
        """Admin can execute write tool through hierarchy."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(WriteTool())

        # Admin has write through hierarchy
        result = await manager.execute_tool(
            'write_tool',
            {},
            permission_context=admin_context
        )

        assert result is not None
        assert result['message'] == "write result"

    @pytest.mark.asyncio
    async def test_execute_unrestricted_always_allowed(
        self, resolver, reader_context
    ):
        """Unrestricted tools work for all users."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(MockTool())

        result = await manager.execute_tool(
            'mock_tool',
            {'param': 'value'},
            permission_context=reader_context
        )

        assert result is not None
        assert result['message'] == "mock result"


class TestContextPropagation:
    """Tests that context and resolver are correctly propagated."""

    @pytest.mark.asyncio
    async def test_context_propagated_to_tool(self, resolver, admin_context):
        """Context and resolver are passed to tool.execute()."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)

        # Create a mock tool to verify what's passed
        mock_tool = MagicMock(spec=AbstractTool)
        mock_tool.name = 'test_tool'
        mock_tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="ok"
        ))
        manager._tools['test_tool'] = mock_tool

        await manager.execute_tool(
            'test_tool',
            {'custom_arg': 'value'},
            permission_context=admin_context
        )

        mock_tool.execute.assert_called_once()
        call_kwargs = mock_tool.execute.call_args.kwargs
        assert call_kwargs['_permission_context'] is admin_context
        assert call_kwargs['_resolver'] is resolver
        assert call_kwargs['custom_arg'] == 'value'

    @pytest.mark.asyncio
    async def test_no_context_no_propagation(self, resolver):
        """When no context provided, _permission_context not passed."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)

        mock_tool = MagicMock(spec=AbstractTool)
        mock_tool.name = 'test_tool'
        mock_tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="ok"
        ))
        manager._tools['test_tool'] = mock_tool

        await manager.execute_tool('test_tool', {'arg': 'val'})

        call_kwargs = mock_tool.execute.call_args.kwargs
        # Context not passed when None
        assert '_permission_context' not in call_kwargs
        # Resolver still passed
        assert call_kwargs['_resolver'] is resolver

    @pytest.mark.asyncio
    async def test_no_resolver_no_propagation(self, admin_context):
        """When no resolver configured, _resolver not passed."""
        manager = ToolManager(include_search_tool=False)  # No resolver

        mock_tool = MagicMock(spec=AbstractTool)
        mock_tool.name = 'test_tool'
        mock_tool.execute = AsyncMock(return_value=ToolResult(
            success=True, status="success", result="ok"
        ))
        manager._tools['test_tool'] = mock_tool

        await manager.execute_tool(
            'test_tool',
            {'arg': 'val'},
            permission_context=admin_context
        )

        call_kwargs = mock_tool.execute.call_args.kwargs
        # Context passed
        assert call_kwargs['_permission_context'] is admin_context
        # Resolver not passed when None
        assert '_resolver' not in call_kwargs


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    @pytest.mark.asyncio
    async def test_existing_tool_calls_work(self):
        """Existing tool calls without permission params still work."""
        manager = ToolManager(include_search_tool=False)
        manager.add_tool(MockTool())

        # Old-style call
        result = await manager.execute_tool('mock_tool', {'param': 'test'})

        assert result is not None
        assert result['message'] == "mock result"

    @pytest.mark.asyncio
    async def test_restricted_tools_work_without_enforcement(self):
        """Restricted tools work when no resolver configured."""
        manager = ToolManager(include_search_tool=False)  # No resolver
        manager.add_tool(AdminTool())

        # No resolver = no enforcement
        result = await manager.execute_tool('admin_tool', {})

        assert result is not None
        assert result['message'] == "admin result"

    def test_manager_sync_preserves_resolver(self, resolver):
        """Syncing managers doesn't affect resolver."""
        manager1 = ToolManager(resolver=resolver, include_search_tool=False)
        manager2 = ToolManager(include_search_tool=False)

        manager1.add_tool(MockTool())
        manager2.sync(manager1)

        # Resolver preserved on manager1
        assert manager1.resolver is resolver
        # Manager2 still has no resolver
        assert manager2.resolver is None


# ── Test: ToolDefinition (@tool) Enforcement Parity (FEAT-474) ─────────────────


class TestToolDefinitionResolverParity:
    """execute_tool()'s ToolDefinition branch now honors the same resolver
    Layer 2 gate as the AbstractTool branch (FEAT-474 AC-1/AC-4/AC-5)."""

    @pytest.mark.asyncio
    async def test_tooldef_admin_allowed(self, resolver, admin_context):
        """Admin can execute an admin-restricted @tool function."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        result = await manager.execute_tool(
            "admin_fn", {"x": 1}, permission_context=admin_context
        )
        assert result == "admin:1"

    @pytest.mark.asyncio
    async def test_tooldef_reader_denied(self, resolver, reader_context):
        """Reader cannot execute an admin-restricted @tool function."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        calls = []

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            calls.append(x)
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        result = await manager.execute_tool(
            "admin_fn", {"x": 1}, permission_context=reader_context
        )
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.status == "forbidden"
        assert calls == []  # function never invoked

    @pytest.mark.asyncio
    async def test_tooldef_fail_open_without_context(self, resolver):
        """No permission_context ⇒ ToolDefinition executes unrestricted
        (identical to pre-FEAT-474 behaviour) even with a resolver set."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        result = await manager.execute_tool("admin_fn", {"x": 1})
        assert result == "admin:1"

    @pytest.mark.asyncio
    async def test_tooldef_fail_open_without_resolver(self, admin_context):
        """No resolver configured ⇒ ToolDefinition executes unrestricted
        even with a permission_context provided."""
        manager = ToolManager(include_search_tool=False)  # no resolver

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        result = await manager.execute_tool(
            "admin_fn", {"x": 1}, permission_context=admin_context
        )
        assert result == "admin:1"

    @pytest.mark.asyncio
    async def test_tooldef_unrestricted_always_allowed(self, resolver, reader_context):
        """A @tool function with no required_permissions is unrestricted."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)

        @tool
        def plain_fn(x: int) -> str:
            """Doc."""
            return f"plain:{x}"
        manager.register_tool(plain_fn)

        result = await manager.execute_tool(
            "plain_fn", {"x": 1}, permission_context=reader_context
        )
        assert result == "plain:1"

    @pytest.mark.asyncio
    async def test_tooldef_resolver_exception_propagates(self, admin_context):
        """A resolver that raises must propagate — no silent fail-open."""

        class BoomResolver(AbstractPermissionResolver):
            async def can_execute(self, context, tool_name, required_permissions):
                raise RuntimeError("resolver boom")

        manager = ToolManager(resolver=BoomResolver(), include_search_tool=False)

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        with pytest.raises(RuntimeError, match="resolver boom"):
            await manager.execute_tool(
                "admin_fn", {"x": 1}, permission_context=admin_context
            )

    @pytest.mark.asyncio
    async def test_execute_tool_call_threads_permission_context(
        self, resolver, reader_context
    ):
        """execute_tool_call() forwards permission_context to execute_tool()."""
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        calls = []

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            calls.append(x)
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        result = await manager.execute_tool_call(
            {"name": "admin_fn", "input": {"x": 1}, "id": "call-1"},
            permission_context=reader_context,
        )
        assert "forbidden" in result["content"].lower()
        assert calls == []  # denied before the function ran


# ── Test: Branch-Parity Denial (FEAT-474 TASK-2582) ────────────────────────────


class TestBranchParityDenial:
    """Under one identical resolver, a @tool function and an equivalent
    AbstractTool are BOTH denied with the same status/error/metadata shape —
    locks the abstract.py:880-890 mirroring so the two branches can't drift
    apart again (FEAT-474 AC-1/AC-2)."""

    @pytest.mark.asyncio
    async def test_denial_shape_identical_across_branches(self, resolver, reader_context):
        manager = ToolManager(resolver=resolver, include_search_tool=False)
        manager.add_tool(AdminTool())

        @tool(required_permissions={"admin"})
        def admin_fn(x: int) -> str:
            """Doc."""
            return f"admin:{x}"
        manager.register_tool(admin_fn)

        abstract_result = await manager.execute_tool(
            "admin_tool", {}, permission_context=reader_context
        )
        tooldef_result = await manager.execute_tool(
            "admin_fn", {"x": 1}, permission_context=reader_context
        )

        # Same status
        assert abstract_result.status == tooldef_result.status == "forbidden"
        assert abstract_result.success is False
        assert tooldef_result.success is False

        # Same error message shape: "Permission denied: '<name>' requires {...}"
        assert abstract_result.error.startswith("Permission denied: 'admin_tool' requires")
        assert tooldef_result.error.startswith("Permission denied: 'admin_fn' requires")

        # Same metadata keys
        assert set(abstract_result.metadata.keys()) == {
            "tool_name", "user_id", "required_permissions"
        }
        assert set(tooldef_result.metadata.keys()) == {
            "tool_name", "user_id", "required_permissions"
        }
        assert abstract_result.metadata["user_id"] == tooldef_result.metadata["user_id"]
        assert abstract_result.metadata["required_permissions"] == ["admin"]
        assert tooldef_result.metadata["required_permissions"] == ["admin"]
