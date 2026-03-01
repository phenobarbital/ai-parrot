"""Unit tests for AbstractToolkit Layer 1 permission filtering.

Tests the permission-based filtering in get_tools() per TASK-063 specification.
"""

import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.resolver import DefaultPermissionResolver
from parrot.tools.decorators import requires_permission
from parrot.tools.toolkit import AbstractToolkit


class MockToolkit(AbstractToolkit):
    """Test toolkit with mixed permissions."""

    async def public_search(self, query: str) -> str:
        """Search available to all users."""
        return f"searched: {query}"

    @requires_permission("read")
    async def read_data(self, id: str) -> str:
        """Read requires read permission."""
        return f"data: {id}"

    @requires_permission("write")
    async def write_data(self, id: str, value: str) -> str:
        """Write requires write permission."""
        return f"wrote: {id}={value}"

    @requires_permission("admin")
    async def admin_action(self) -> str:
        """Admin only action."""
        return "admin done"


@pytest.fixture
def resolver() -> DefaultPermissionResolver:
    """Default resolver with role hierarchy."""
    return DefaultPermissionResolver(
        role_hierarchy={
            "admin": {"write", "read"},
            "write": {"read"},
            "read": set(),
        }
    )


@pytest.fixture
def admin_session() -> UserSession:
    """Admin user session."""
    return UserSession(user_id="admin", tenant_id="t1", roles=frozenset({"admin"}))


@pytest.fixture
def admin_context(admin_session: UserSession) -> PermissionContext:
    """Admin permission context."""
    return PermissionContext(session=admin_session)


@pytest.fixture
def reader_session() -> UserSession:
    """Reader user session."""
    return UserSession(user_id="reader", tenant_id="t1", roles=frozenset({"read"}))


@pytest.fixture
def reader_context(reader_session: UserSession) -> PermissionContext:
    """Reader permission context."""
    return PermissionContext(session=reader_session)


@pytest.fixture
def no_roles_context() -> PermissionContext:
    """Context with no roles."""
    session = UserSession(user_id="anon", tenant_id="t1", roles=frozenset())
    return PermissionContext(session=session)


@pytest.fixture
def toolkit() -> MockToolkit:
    """Test toolkit instance."""
    return MockToolkit()


class TestLayer1Filtering:
    """Tests for Layer 1 (preventive) permission filtering."""

    @pytest.mark.asyncio
    async def test_no_context_returns_all(self, toolkit: MockToolkit) -> None:
        """Without context, all tools returned (backward compat)."""
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        assert "public_search" in tool_names
        assert "read_data" in tool_names
        assert "write_data" in tool_names
        assert "admin_action" in tool_names
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_admin_sees_all(
        self,
        toolkit: MockToolkit,
        resolver: DefaultPermissionResolver,
        admin_context: PermissionContext,
    ) -> None:
        """Admin sees all tools."""
        tools = await toolkit.get_tools(
            permission_context=admin_context, resolver=resolver
        )
        tool_names = [t.name for t in tools]

        assert "public_search" in tool_names
        assert "read_data" in tool_names
        assert "write_data" in tool_names
        assert "admin_action" in tool_names
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_reader_filtered(
        self,
        toolkit: MockToolkit,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Reader only sees public and read tools."""
        tools = await toolkit.get_tools(
            permission_context=reader_context, resolver=resolver
        )
        tool_names = [t.name for t in tools]

        assert "public_search" in tool_names  # unrestricted
        assert "read_data" in tool_names  # has read permission
        assert "write_data" not in tool_names  # no write permission
        assert "admin_action" not in tool_names  # no admin permission
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_only_context_no_filter(
        self, toolkit: MockToolkit, admin_context: PermissionContext
    ) -> None:
        """Only context without resolver = no filtering."""
        tools = await toolkit.get_tools(permission_context=admin_context)
        # Should return all tools
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_only_resolver_no_filter(
        self, toolkit: MockToolkit, resolver: DefaultPermissionResolver
    ) -> None:
        """Only resolver without context = no filtering."""
        tools = await toolkit.get_tools(resolver=resolver)
        # Should return all tools
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_empty_roles_sees_only_public(
        self,
        toolkit: MockToolkit,
        resolver: DefaultPermissionResolver,
        no_roles_context: PermissionContext,
    ) -> None:
        """User with no roles sees only unrestricted tools."""
        tools = await toolkit.get_tools(
            permission_context=no_roles_context, resolver=resolver
        )
        tool_names = [t.name for t in tools]

        assert tool_names == ["public_search"]
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_tools_cached_and_filtered(
        self,
        toolkit: MockToolkit,
        resolver: DefaultPermissionResolver,
        admin_context: PermissionContext,
        reader_context: PermissionContext,
    ) -> None:
        """Tools are cached but filtering happens each call."""
        # First call with admin
        admin_tools = await toolkit.get_tools(
            permission_context=admin_context, resolver=resolver
        )
        assert len(admin_tools) == 4

        # Second call with reader - should still filter correctly
        reader_tools = await toolkit.get_tools(
            permission_context=reader_context, resolver=resolver
        )
        assert len(reader_tools) == 2

        # Third call with admin again
        admin_tools_again = await toolkit.get_tools(
            permission_context=admin_context, resolver=resolver
        )
        assert len(admin_tools_again) == 4


class TestToolPermissionPropagation:
    """Tests that _required_permissions propagates to ToolkitTool."""

    @pytest.mark.asyncio
    async def test_permission_attribute_on_tool(self, toolkit: MockToolkit) -> None:
        """Tools have _required_permissions from decorated methods."""
        tools = await toolkit.get_tools()
        tool_map = {t.name: t for t in tools}

        # Public method has no _required_permissions
        assert not hasattr(tool_map["public_search"], "_required_permissions")

        # Decorated methods have _required_permissions
        assert tool_map["read_data"]._required_permissions == frozenset({"read"})
        assert tool_map["write_data"]._required_permissions == frozenset({"write"})
        assert tool_map["admin_action"]._required_permissions == frozenset({"admin"})

    @pytest.mark.asyncio
    async def test_tools_still_callable(self, toolkit: MockToolkit) -> None:
        """Tools with permissions are still callable."""
        tools = await toolkit.get_tools()
        tool_map = {t.name: t for t in tools}

        # Execute a tool - should work regardless of permissions attribute
        result = await tool_map["read_data"]._execute(id="test-123")
        assert result == "data: test-123"


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing code."""

    @pytest.mark.asyncio
    async def test_sync_methods_ignored(self) -> None:
        """Sync methods are not converted to tools (same as before)."""

        class MixedToolkit(AbstractToolkit):
            async def async_tool(self, x: str) -> str:
                return x

            def sync_method(self, x: str) -> str:
                return x

        toolkit = MixedToolkit()
        tools = await toolkit.get_tools()
        tool_names = [t.name for t in tools]

        assert "async_tool" in tool_names
        assert "sync_method" not in tool_names

    @pytest.mark.asyncio
    async def test_get_tool_still_works(self, toolkit: MockToolkit) -> None:
        """get_tool() still works for specific tool lookup."""
        # Call get_tools first to generate
        await toolkit.get_tools()

        tool = toolkit.get_tool("read_data")
        assert tool is not None
        assert tool.name == "read_data"

    @pytest.mark.asyncio
    async def test_list_tool_names_still_works(self, toolkit: MockToolkit) -> None:
        """list_tool_names() still works."""
        # Generate tools
        await toolkit.get_tools()

        names = toolkit.list_tool_names()
        assert "public_search" in names
        assert "read_data" in names
        assert len(names) == 4

    @pytest.mark.asyncio
    async def test_get_toolkit_info_still_works(self, toolkit: MockToolkit) -> None:
        """get_toolkit_info() still works."""
        info = toolkit.get_toolkit_info()

        assert info["toolkit_name"] == "MockToolkit"
        assert info["tool_count"] == 4
        assert "public_search" in info["tool_names"]


class TestMultiplePermissions:
    """Tests for tools requiring multiple permissions (OR semantics)."""

    @pytest.mark.asyncio
    async def test_or_permissions_filtering(self) -> None:
        """Multiple permissions use OR semantics in filtering."""

        class MultiPermToolkit(AbstractToolkit):
            @requires_permission("write", "admin")
            async def write_or_admin(self) -> str:
                return "done"

            async def public(self) -> str:
                return "public"

        toolkit = MultiPermToolkit()
        resolver = DefaultPermissionResolver(
            role_hierarchy={"admin": set(), "write": set(), "read": set()}
        )

        # User with only 'write' should see the tool (OR semantics)
        write_session = UserSession(
            user_id="writer", tenant_id="t1", roles=frozenset({"write"})
        )
        write_ctx = PermissionContext(session=write_session)

        tools = await toolkit.get_tools(permission_context=write_ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert "write_or_admin" in tool_names
        assert "public" in tool_names

        # User with only 'read' should NOT see the tool
        read_session = UserSession(
            user_id="reader", tenant_id="t1", roles=frozenset({"read"})
        )
        read_ctx = PermissionContext(session=read_session)

        tools = await toolkit.get_tools(permission_context=read_ctx, resolver=resolver)
        tool_names = [t.name for t in tools]

        assert "write_or_admin" not in tool_names
        assert "public" in tool_names
