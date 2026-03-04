"""Unit tests for permission resolvers.

Tests AbstractPermissionResolver, DefaultPermissionResolver, and utility resolvers
per TASK-060 specification.
"""

import pytest

from parrot.auth import (
    AbstractPermissionResolver,
    AllowAllResolver,
    DefaultPermissionResolver,
    DenyAllResolver,
    PermissionContext,
    UserSession,
)
from parrot.auth.resolver import (
    AbstractPermissionResolver as ResolverDirect,
    DefaultPermissionResolver as DefaultDirect,
)


@pytest.fixture
def hierarchy() -> dict[str, set[str]]:
    """Standard test hierarchy: admin > manage > write > read."""
    return {
        "admin": {"manage", "write", "read"},
        "manage": {"write", "read"},
        "write": {"read"},
        "read": set(),
    }


@pytest.fixture
def resolver(hierarchy: dict[str, set[str]]) -> DefaultPermissionResolver:
    """Default resolver with standard hierarchy."""
    return DefaultPermissionResolver(role_hierarchy=hierarchy)


@pytest.fixture
def admin_session() -> UserSession:
    """Admin user session."""
    return UserSession(
        user_id="admin-1",
        tenant_id="tenant-1",
        roles=frozenset({"admin"}),
    )


@pytest.fixture
def admin_context(admin_session: UserSession) -> PermissionContext:
    """Admin permission context."""
    return PermissionContext(session=admin_session, request_id="req-admin")


@pytest.fixture
def reader_session() -> UserSession:
    """Reader user session."""
    return UserSession(
        user_id="reader-1",
        tenant_id="tenant-1",
        roles=frozenset({"read"}),
    )


@pytest.fixture
def reader_context(reader_session: UserSession) -> PermissionContext:
    """Reader permission context."""
    return PermissionContext(session=reader_session, request_id="req-reader")


@pytest.fixture
def no_roles_context() -> PermissionContext:
    """Context with no roles."""
    session = UserSession(
        user_id="nobody",
        tenant_id="tenant-1",
        roles=frozenset(),
    )
    return PermissionContext(session=session)


class TestDefaultPermissionResolver:
    """Tests for DefaultPermissionResolver."""

    @pytest.mark.asyncio
    async def test_unrestricted_tool_always_allowed(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Empty required_permissions returns True."""
        result = await resolver.can_execute(reader_context, "search", set())
        assert result is True

    @pytest.mark.asyncio
    async def test_unrestricted_tool_allowed_for_no_roles(
        self,
        resolver: DefaultPermissionResolver,
        no_roles_context: PermissionContext,
    ) -> None:
        """User with no roles can still access unrestricted tools."""
        result = await resolver.can_execute(no_roles_context, "public_search", set())
        assert result is True

    @pytest.mark.asyncio
    async def test_direct_role_match(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """User with direct role is allowed."""
        result = await resolver.can_execute(reader_context, "view", {"read"})
        assert result is True

    @pytest.mark.asyncio
    async def test_hierarchy_expansion_admin(
        self,
        resolver: DefaultPermissionResolver,
        admin_context: PermissionContext,
    ) -> None:
        """Admin has all implied permissions."""
        assert await resolver.can_execute(admin_context, "read_op", {"read"}) is True
        assert await resolver.can_execute(admin_context, "write_op", {"write"}) is True
        assert await resolver.can_execute(admin_context, "manage_op", {"manage"}) is True
        assert await resolver.can_execute(admin_context, "admin_op", {"admin"}) is True

    @pytest.mark.asyncio
    async def test_hierarchy_expansion_transitive(
        self,
        hierarchy: dict[str, set[str]],
    ) -> None:
        """Transitive expansion works correctly."""
        resolver = DefaultPermissionResolver(role_hierarchy=hierarchy)
        # User with 'manage' should have 'write' and 'read' transitively
        session = UserSession(
            user_id="manager",
            tenant_id="t1",
            roles=frozenset({"manage"}),
        )
        ctx = PermissionContext(session=session)

        assert await resolver.can_execute(ctx, "t1", {"manage"}) is True
        assert await resolver.can_execute(ctx, "t2", {"write"}) is True
        assert await resolver.can_execute(ctx, "t3", {"read"}) is True
        assert await resolver.can_execute(ctx, "t4", {"admin"}) is False

    @pytest.mark.asyncio
    async def test_deny_insufficient_role(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Reader cannot access write-only tools."""
        result = await resolver.can_execute(reader_context, "create", {"write"})
        assert result is False

    @pytest.mark.asyncio
    async def test_deny_no_roles(
        self,
        resolver: DefaultPermissionResolver,
        no_roles_context: PermissionContext,
    ) -> None:
        """User with no roles is denied restricted tools."""
        result = await resolver.can_execute(no_roles_context, "anything", {"read"})
        assert result is False

    @pytest.mark.asyncio
    async def test_or_semantics(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Any matching permission grants access (OR logic)."""
        # Reader has 'read', tool requires 'read' OR 'write'
        result = await resolver.can_execute(reader_context, "multi", {"read", "write"})
        assert result is True  # has 'read'

    @pytest.mark.asyncio
    async def test_or_semantics_no_match(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """OR logic fails if no permission matches."""
        result = await resolver.can_execute(
            reader_context, "restricted", {"admin", "manage"}
        )
        assert result is False

    def test_cache_hit(self, resolver: DefaultPermissionResolver) -> None:
        """LRU cache returns same expansion."""
        roles = frozenset({"admin"})
        exp1 = resolver._expand_cached(roles)
        exp2 = resolver._expand_cached(roles)
        assert exp1 is exp2  # same object from cache

    def test_cache_info(self, resolver: DefaultPermissionResolver) -> None:
        """Cache info is accessible."""
        roles = frozenset({"admin"})
        resolver._expand_cached(roles)
        resolver._expand_cached(roles)

        info = resolver.cache_info
        assert info.hits >= 1
        assert info.misses >= 1

    def test_clear_cache(self, resolver: DefaultPermissionResolver) -> None:
        """Cache can be cleared."""
        roles = frozenset({"admin"})
        resolver._expand_cached(roles)
        assert resolver.cache_info.currsize > 0

        resolver.clear_cache()
        assert resolver.cache_info.currsize == 0

    def test_no_hierarchy(self) -> None:
        """Resolver works without hierarchy (direct matching only)."""
        resolver = DefaultPermissionResolver()  # No hierarchy
        roles = frozenset({"admin", "reader"})
        expanded = resolver._expand_cached(roles)
        assert expanded == roles  # No expansion

    def test_custom_cache_size(self) -> None:
        """Custom cache size is respected."""
        resolver = DefaultPermissionResolver(cache_size=10)
        assert resolver._expand_cached.cache_info().maxsize == 10


class TestFilterTools:
    """Tests for filter_tools method."""

    class MockTool:
        """Mock tool for testing."""

        def __init__(self, name: str, perms: set[str] | None = None) -> None:
            self.name = name
            if perms is not None:
                self._required_permissions = perms

    @pytest.mark.asyncio
    async def test_filters_unauthorized(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Unauthorized tools are filtered out."""
        tools = [
            self.MockTool("search", set()),  # unrestricted
            self.MockTool("view", {"read"}),  # allowed
            self.MockTool("create", {"write"}),  # denied
        ]

        filtered = await resolver.filter_tools(reader_context, tools)
        names = [t.name for t in filtered]
        assert "search" in names
        assert "view" in names
        assert "create" not in names

    @pytest.mark.asyncio
    async def test_filters_all_for_no_roles(
        self,
        resolver: DefaultPermissionResolver,
        no_roles_context: PermissionContext,
    ) -> None:
        """User with no roles only sees unrestricted tools."""
        tools = [
            self.MockTool("public", set()),  # unrestricted
            self.MockTool("restricted", {"read"}),  # denied
        ]

        filtered = await resolver.filter_tools(no_roles_context, tools)
        names = [t.name for t in filtered]
        assert names == ["public"]

    @pytest.mark.asyncio
    async def test_allows_all_for_admin(
        self,
        resolver: DefaultPermissionResolver,
        admin_context: PermissionContext,
    ) -> None:
        """Admin sees all tools."""
        tools = [
            self.MockTool("search", set()),
            self.MockTool("view", {"read"}),
            self.MockTool("create", {"write"}),
            self.MockTool("manage", {"manage"}),
            self.MockTool("admin_op", {"admin"}),
        ]

        filtered = await resolver.filter_tools(admin_context, tools)
        assert len(filtered) == 5

    @pytest.mark.asyncio
    async def test_tool_without_permissions_attr(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Tools without _required_permissions are treated as unrestricted."""
        tools = [self.MockTool("legacy_tool")]  # No permissions attr

        filtered = await resolver.filter_tools(reader_context, tools)
        assert len(filtered) == 1
        assert filtered[0].name == "legacy_tool"

    @pytest.mark.asyncio
    async def test_empty_tools_list(
        self,
        resolver: DefaultPermissionResolver,
        reader_context: PermissionContext,
    ) -> None:
        """Empty tools list returns empty list."""
        filtered = await resolver.filter_tools(reader_context, [])
        assert filtered == []


class TestAllowAllResolver:
    """Tests for AllowAllResolver."""

    @pytest.fixture
    def resolver(self) -> AllowAllResolver:
        return AllowAllResolver()

    @pytest.mark.asyncio
    async def test_allows_unrestricted(
        self, resolver: AllowAllResolver, reader_context: PermissionContext
    ) -> None:
        """Allows unrestricted tools."""
        result = await resolver.can_execute(reader_context, "tool", set())
        assert result is True

    @pytest.mark.asyncio
    async def test_allows_restricted(
        self, resolver: AllowAllResolver, reader_context: PermissionContext
    ) -> None:
        """Allows restricted tools regardless of roles."""
        result = await resolver.can_execute(reader_context, "admin_tool", {"admin"})
        assert result is True

    @pytest.mark.asyncio
    async def test_allows_for_no_roles(
        self, resolver: AllowAllResolver, no_roles_context: PermissionContext
    ) -> None:
        """Allows all tools even for users with no roles."""
        result = await resolver.can_execute(no_roles_context, "admin_tool", {"admin"})
        assert result is True


class TestDenyAllResolver:
    """Tests for DenyAllResolver."""

    @pytest.fixture
    def resolver(self) -> DenyAllResolver:
        return DenyAllResolver()

    @pytest.mark.asyncio
    async def test_allows_unrestricted(
        self, resolver: DenyAllResolver, admin_context: PermissionContext
    ) -> None:
        """Allows unrestricted tools."""
        result = await resolver.can_execute(admin_context, "public", set())
        assert result is True

    @pytest.mark.asyncio
    async def test_denies_restricted(
        self, resolver: DenyAllResolver, admin_context: PermissionContext
    ) -> None:
        """Denies all restricted tools regardless of roles."""
        result = await resolver.can_execute(admin_context, "tool", {"read"})
        assert result is False


class TestAbstractResolver:
    """Tests for AbstractPermissionResolver ABC."""

    def test_is_abstract(self) -> None:
        """Cannot instantiate AbstractPermissionResolver directly."""
        with pytest.raises(TypeError):
            AbstractPermissionResolver()  # type: ignore[abstract]

    def test_subclass_must_implement_can_execute(self) -> None:
        """Subclass must implement can_execute."""

        class IncompleteResolver(AbstractPermissionResolver):
            pass

        with pytest.raises(TypeError):
            IncompleteResolver()  # type: ignore[abstract]

    def test_subclass_can_use_default_filter_tools(self) -> None:
        """Subclass can use default filter_tools implementation."""

        class MinimalResolver(AbstractPermissionResolver):
            async def can_execute(
                self,
                context: PermissionContext,
                tool_name: str,
                required_permissions: set[str],
            ) -> bool:
                return True

        resolver = MinimalResolver()
        assert hasattr(resolver, "filter_tools")


class TestModuleExports:
    """Tests for module-level exports."""

    def test_import_from_package(self) -> None:
        """Can import resolvers from parrot.auth package."""
        assert AbstractPermissionResolver is ResolverDirect
        assert DefaultPermissionResolver is DefaultDirect

    def test_all_exports(self) -> None:
        """__all__ contains expected exports."""
        from parrot import auth

        assert "AbstractPermissionResolver" in auth.__all__
        assert "DefaultPermissionResolver" in auth.__all__
        assert "AllowAllResolver" in auth.__all__
        assert "DenyAllResolver" in auth.__all__


class TestComplexHierarchies:
    """Tests for complex role hierarchy scenarios."""

    @pytest.mark.asyncio
    async def test_diamond_hierarchy(self) -> None:
        """Diamond-shaped hierarchy expands correctly."""
        # Diamond: admin -> (manager, developer) -> contributor
        hierarchy = {
            "admin": {"manager", "developer"},
            "manager": {"contributor"},
            "developer": {"contributor"},
            "contributor": set(),
        }
        resolver = DefaultPermissionResolver(role_hierarchy=hierarchy)

        session = UserSession(
            user_id="u1", tenant_id="t1", roles=frozenset({"admin"})
        )
        ctx = PermissionContext(session=session)

        # Admin should have all roles through diamond
        assert await resolver.can_execute(ctx, "t", {"admin"}) is True
        assert await resolver.can_execute(ctx, "t", {"manager"}) is True
        assert await resolver.can_execute(ctx, "t", {"developer"}) is True
        assert await resolver.can_execute(ctx, "t", {"contributor"}) is True

    @pytest.mark.asyncio
    async def test_multiple_user_roles(self) -> None:
        """User with multiple roles gets union of permissions."""
        hierarchy = {
            "jira.write": {"jira.read"},
            "github.write": {"github.read"},
        }
        resolver = DefaultPermissionResolver(role_hierarchy=hierarchy)

        # User has both jira.write and github.write
        session = UserSession(
            user_id="u1",
            tenant_id="t1",
            roles=frozenset({"jira.write", "github.write"}),
        )
        ctx = PermissionContext(session=session)

        # Should have all expanded permissions
        assert await resolver.can_execute(ctx, "t", {"jira.write"}) is True
        assert await resolver.can_execute(ctx, "t", {"jira.read"}) is True
        assert await resolver.can_execute(ctx, "t", {"github.write"}) is True
        assert await resolver.can_execute(ctx, "t", {"github.read"}) is True

    @pytest.mark.asyncio
    async def test_deep_hierarchy(self) -> None:
        """Deep hierarchy (5 levels) expands correctly."""
        hierarchy = {
            "level1": {"level2"},
            "level2": {"level3"},
            "level3": {"level4"},
            "level4": {"level5"},
            "level5": set(),
        }
        resolver = DefaultPermissionResolver(role_hierarchy=hierarchy)

        session = UserSession(
            user_id="u1", tenant_id="t1", roles=frozenset({"level1"})
        )
        ctx = PermissionContext(session=session)

        # Should have all levels
        for level in ["level1", "level2", "level3", "level4", "level5"]:
            assert await resolver.can_execute(ctx, "t", {level}) is True
