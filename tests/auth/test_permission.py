"""Unit tests for permission data models.

Tests UserSession and PermissionContext dataclasses per TASK-059 specification.
"""

import pytest

from parrot.auth import PermissionContext, UserSession
from parrot.auth.permission import PermissionContext as PermissionContextDirect
from parrot.auth.permission import UserSession as UserSessionDirect


class TestUserSession:
    """Tests for UserSession frozen dataclass."""

    def test_frozen_immutable(self) -> None:
        """UserSession is immutable."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"role-a"}),
        )
        with pytest.raises(AttributeError):
            session.user_id = "changed"  # type: ignore[misc]

    def test_roles_is_frozenset(self) -> None:
        """Roles must be frozenset."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin", "user"}),
        )
        assert isinstance(session.roles, frozenset)
        assert "admin" in session.roles

    def test_hashable(self) -> None:
        """UserSession is hashable (for cache keys)."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"role-a"}),
        )
        # Should not raise
        hash_value = hash(session)
        assert isinstance(hash_value, int)

    def test_default_metadata(self) -> None:
        """Metadata defaults to empty dict."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset(),
        )
        assert session.metadata == {}

    def test_custom_metadata(self) -> None:
        """Custom metadata is preserved."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset(),
            metadata={"auth_provider": "oauth2", "mfa_enabled": True},
        )
        assert session.metadata["auth_provider"] == "oauth2"
        assert session.metadata["mfa_enabled"] is True

    def test_has_role(self) -> None:
        """has_role returns True for present roles."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin", "user"}),
        )
        assert session.has_role("admin") is True
        assert session.has_role("superuser") is False

    def test_has_any_role(self) -> None:
        """has_any_role returns True if any role matches."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"jira.write", "github.read"}),
        )
        assert session.has_any_role({"jira.write", "jira.admin"}) is True
        assert session.has_any_role({"jira.admin", "github.admin"}) is False

    def test_empty_roles(self) -> None:
        """Session with empty roles is valid."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset(),
        )
        assert len(session.roles) == 0
        assert session.has_role("anything") is False

    def test_equality(self) -> None:
        """Two sessions with same data are equal."""
        session1 = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        session2 = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        assert session1 == session2

    def test_inequality(self) -> None:
        """Sessions with different data are not equal."""
        session1 = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        session2 = UserSession(
            user_id="user-2",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        assert session1 != session2


class TestPermissionContext:
    """Tests for PermissionContext dataclass."""

    def test_wraps_session(self) -> None:
        """Context wraps UserSession."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        ctx = PermissionContext(session=session)
        assert ctx.session is session

    def test_property_proxies(self) -> None:
        """Context proxies session properties."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        ctx = PermissionContext(session=session, request_id="req-123")
        assert ctx.user_id == "user-1"
        assert ctx.tenant_id == "tenant-1"
        assert ctx.roles == frozenset({"admin"})
        assert ctx.request_id == "req-123"

    def test_extra_metadata(self) -> None:
        """Context accepts extra metadata."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset(),
        )
        ctx = PermissionContext(
            session=session,
            extra={"source": "api"},
        )
        assert ctx.extra["source"] == "api"

    def test_default_values(self) -> None:
        """Context has sensible defaults."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset(),
        )
        ctx = PermissionContext(session=session)
        assert ctx.request_id is None
        assert ctx.extra == {}

    def test_has_role_proxy(self) -> None:
        """Context proxies has_role method."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin", "user"}),
        )
        ctx = PermissionContext(session=session)
        assert ctx.has_role("admin") is True
        assert ctx.has_role("superuser") is False

    def test_has_any_role_proxy(self) -> None:
        """Context proxies has_any_role method."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"jira.write"}),
        )
        ctx = PermissionContext(session=session)
        assert ctx.has_any_role({"jira.write", "jira.admin"}) is True
        assert ctx.has_any_role({"github.admin"}) is False

    def test_mutable_extra(self) -> None:
        """Context extra dict is mutable (request-scoped)."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset(),
        )
        ctx = PermissionContext(session=session)
        ctx.extra["added_key"] = "value"
        assert ctx.extra["added_key"] == "value"


class TestModuleExports:
    """Tests for module-level exports."""

    def test_import_from_package(self) -> None:
        """Can import from parrot.auth package."""
        assert UserSession is UserSessionDirect
        assert PermissionContext is PermissionContextDirect

    def test_all_exports(self) -> None:
        """__all__ contains expected exports."""
        from parrot import auth

        assert "UserSession" in auth.__all__
        assert "PermissionContext" in auth.__all__


class TestRealWorldScenarios:
    """Integration-style tests for realistic usage patterns."""

    def test_jira_role_hierarchy_scenario(self) -> None:
        """Simulate Jira-style role checking."""
        # Admin user
        admin_session = UserSession(
            user_id="admin-1",
            tenant_id="acme-corp",
            roles=frozenset({"jira.admin"}),
        )
        admin_ctx = PermissionContext(
            session=admin_session,
            request_id="req-001",
            extra={"source": "slack"},
        )

        # Reader user
        reader_session = UserSession(
            user_id="reader-1",
            tenant_id="acme-corp",
            roles=frozenset({"jira.read"}),
        )
        reader_ctx = PermissionContext(
            session=reader_session,
            request_id="req-002",
        )

        # Admin has admin role
        assert admin_ctx.has_role("jira.admin") is True
        # Reader doesn't have admin role
        assert reader_ctx.has_role("jira.admin") is False
        # Both are in same tenant
        assert admin_ctx.tenant_id == reader_ctx.tenant_id

    def test_multi_tenant_isolation(self) -> None:
        """Sessions from different tenants are isolated."""
        tenant_a_session = UserSession(
            user_id="user-1",
            tenant_id="tenant-a",
            roles=frozenset({"admin"}),
        )
        tenant_b_session = UserSession(
            user_id="user-1",  # Same user ID
            tenant_id="tenant-b",
            roles=frozenset({"admin"}),
        )

        # Same user ID but different tenants = different sessions
        assert tenant_a_session != tenant_b_session
        # Can use as different cache keys
        assert hash(tenant_a_session) != hash(tenant_b_session)

    def test_session_as_dict_key(self) -> None:
        """UserSession can be used as dictionary key (caching)."""
        session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )

        # Simulate a permission cache
        cache: dict[UserSession, bool] = {}
        cache[session] = True

        # Lookup with equivalent session
        lookup_session = UserSession(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=frozenset({"admin"}),
        )
        assert cache[lookup_session] is True
