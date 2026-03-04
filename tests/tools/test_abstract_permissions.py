"""Tests for AbstractTool Layer 2 permission enforcement."""

import logging
import pytest
from unittest.mock import AsyncMock

from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.auth.permission import UserSession, PermissionContext
from parrot.auth.resolver import DefaultPermissionResolver
from parrot.tools.decorators import requires_permission


class MockTool(AbstractTool):
    """Test tool for permission testing."""

    name = "mock_tool"
    description = "A mock tool"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="executed")


@requires_permission('write')
class RestrictedTool(AbstractTool):
    """Tool requiring write permission."""

    name = "restricted_tool"
    description = "Requires write permission"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="restricted executed")


@requires_permission('admin', 'superuser')
class MultiPermTool(AbstractTool):
    """Tool requiring admin OR superuser permission."""

    name = "multi_perm_tool"
    description = "Requires admin or superuser"

    async def _execute(self, **kwargs):
        return ToolResult(success=True, status="success", result="multi executed")


@pytest.fixture
def resolver():
    return DefaultPermissionResolver(role_hierarchy={
        'admin': {'write', 'read'},
        'write': {'read'},
        'read': set(),
    })


@pytest.fixture
def admin_context():
    session = UserSession(user_id="admin", tenant_id="t1", roles=frozenset({'admin'}))
    return PermissionContext(session=session)


@pytest.fixture
def writer_context():
    session = UserSession(user_id="writer", tenant_id="t1", roles=frozenset({'write'}))
    return PermissionContext(session=session)


@pytest.fixture
def reader_context():
    session = UserSession(user_id="reader", tenant_id="t1", roles=frozenset({'read'}))
    return PermissionContext(session=session)


class TestLayer2Enforcement:
    """Tests for Layer 2 permission enforcement in AbstractTool.execute()."""

    @pytest.mark.asyncio
    async def test_no_context_no_enforcement(self):
        """Without context, no permission check runs."""
        tool = MockTool()
        result = await tool.execute()
        assert result.success is True
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_no_resolver_no_enforcement(self, admin_context):
        """Without resolver, no permission check runs (even with context)."""
        tool = RestrictedTool()
        result = await tool.execute(_permission_context=admin_context)
        assert result.success is True
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_no_context_with_resolver_no_enforcement(self, resolver):
        """Without context, no permission check runs (even with resolver)."""
        tool = RestrictedTool()
        result = await tool.execute(_resolver=resolver)
        assert result.success is True
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_unrestricted_tool_allowed(self, resolver, reader_context):
        """Unrestricted tool (no decorator) is always allowed."""
        tool = MockTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )
        assert result.success is True
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_restricted_tool_denied(self, resolver, reader_context):
        """Restricted tool denies user without permission."""
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )
        assert result.success is False
        assert result.status == "forbidden"
        assert "Permission denied" in result.error
        assert "restricted_tool" in result.error

    @pytest.mark.asyncio
    async def test_restricted_tool_allowed_direct_role(self, resolver, writer_context):
        """Restricted tool allows user with direct permission."""
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=writer_context,
            _resolver=resolver
        )
        assert result.success is True
        assert result.result == "restricted executed"

    @pytest.mark.asyncio
    async def test_restricted_tool_allowed_hierarchy(self, resolver, admin_context):
        """Restricted tool allows user with permission through hierarchy."""
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver
        )
        assert result.success is True
        assert result.result == "restricted executed"

    @pytest.mark.asyncio
    async def test_multi_perm_or_semantics(self, resolver, admin_context):
        """Multiple permissions use OR semantics."""
        tool = MultiPermTool()
        result = await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver
        )
        assert result.success is True
        assert result.result == "multi executed"

    @pytest.mark.asyncio
    async def test_denial_logged(self, resolver, reader_context, caplog):
        """Permission denial is logged as warning."""
        with caplog.at_level(logging.WARNING):
            tool = RestrictedTool()
            await tool.execute(
                _permission_context=reader_context,
                _resolver=resolver
            )

        assert "Permission denied" in caplog.text
        assert "reader" in caplog.text
        assert "restricted_tool" in caplog.text

    @pytest.mark.asyncio
    async def test_kwargs_not_passed_to_execute(self, resolver, admin_context):
        """_permission_context and _resolver are not passed to _execute."""
        from pydantic import BaseModel, Field

        class InspectArgs(BaseModel):
            actual_arg: str = Field(default="")

        class InspectingTool(AbstractTool):
            name = "inspect_tool"
            description = "Inspects kwargs"
            args_schema = InspectArgs
            captured_kwargs = None

            async def _execute(self, **kwargs):
                InspectingTool.captured_kwargs = kwargs
                return ToolResult(success=True, status="success", result="ok")

        tool = InspectingTool()
        await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver,
            actual_arg="value"
        )

        assert '_permission_context' not in InspectingTool.captured_kwargs
        assert '_resolver' not in InspectingTool.captured_kwargs
        assert InspectingTool.captured_kwargs.get('actual_arg') == "value"

    @pytest.mark.asyncio
    async def test_forbidden_result_metadata(self, resolver, reader_context):
        """Forbidden result includes useful metadata."""
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )

        assert result.metadata.get("tool_name") == "restricted_tool"
        assert result.metadata.get("user_id") == "reader"
        assert "write" in result.metadata.get("required_permissions", [])

    @pytest.mark.asyncio
    async def test_existing_kwargs_preserved(self, resolver, admin_context):
        """Normal kwargs are preserved and passed to _execute."""
        from pydantic import BaseModel, Field

        class EchoArgs(BaseModel):
            message: str = Field(default="")

        class EchoTool(AbstractTool):
            name = "echo_tool"
            description = "Echoes input"
            args_schema = EchoArgs

            async def _execute(self, message: str = "", **kwargs):
                return ToolResult(success=True, status="success", result=message)

        tool = EchoTool()
        result = await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver,
            message="hello world"
        )

        assert result.success is True
        assert result.result == "hello world"

    @pytest.mark.asyncio
    async def test_empty_required_permissions_allowed(self, resolver, reader_context):
        """Tool decorated with empty permissions is allowed."""

        @requires_permission()
        class EmptyPermTool(AbstractTool):
            name = "empty_perm_tool"
            description = "No permissions required"

            async def _execute(self, **kwargs):
                return ToolResult(success=True, status="success", result="empty ok")

        tool = EmptyPermTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )

        assert result.success is True
        assert result.result == "empty ok"

    @pytest.mark.asyncio
    async def test_tool_error_handling_preserved(self, resolver, admin_context):
        """Tool errors are still handled properly after permission check."""

        class FailingTool(AbstractTool):
            name = "failing_tool"
            description = "Always fails"

            async def _execute(self, **kwargs):
                raise ValueError("Intentional failure")

        tool = FailingTool()
        result = await tool.execute(
            _permission_context=admin_context,
            _resolver=resolver
        )

        # Error is captured and returned in result (existing behavior)
        assert result.status == "error"
        assert "Intentional failure" in result.error

    @pytest.mark.asyncio
    async def test_custom_resolver_integration(self, reader_context):
        """Custom resolver is properly called."""

        class CustomResolver:
            def __init__(self):
                self.calls = []

            async def can_execute(self, context, tool_name, required_permissions):
                self.calls.append((context, tool_name, required_permissions))
                return True  # Allow all

        resolver = CustomResolver()
        tool = RestrictedTool()
        result = await tool.execute(
            _permission_context=reader_context,
            _resolver=resolver
        )

        assert result.success is True
        assert len(resolver.calls) == 1
        assert resolver.calls[0][1] == "restricted_tool"
        assert resolver.calls[0][2] == frozenset({'write'})

    @pytest.mark.asyncio
    async def test_backward_compatibility_no_breaking_changes(self):
        """Existing tool code without permission args still works."""
        from pydantic import BaseModel, Field

        class LegacyArgs(BaseModel):
            value: int = Field(default=0)

        class LegacyTool(AbstractTool):
            name = "legacy_tool"
            description = "Old-style tool"
            args_schema = LegacyArgs

            async def _execute(self, value: int = 0, **kwargs):
                return ToolResult(success=True, status="success", result=value * 2)

        tool = LegacyTool()
        result = await tool.execute(value=21)

        assert result.success is True
        assert result.result == 42
