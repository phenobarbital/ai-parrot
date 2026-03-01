"""Tests for parrot.tools.decorators module."""
import pytest
from parrot.tools.decorators import requires_permission


class TestRequiresPermissionDecorator:
    """Tests for @requires_permission decorator."""

    def test_sets_attribute_on_function(self):
        """Decorator sets _required_permissions on function."""
        @requires_permission('admin')
        async def my_func():
            pass

        assert hasattr(my_func, '_required_permissions')
        assert my_func._required_permissions == frozenset({'admin'})

    def test_sets_attribute_on_class(self):
        """Decorator sets _required_permissions on class."""
        @requires_permission('write', 'admin')
        class MyTool:
            pass

        assert hasattr(MyTool, '_required_permissions')
        assert MyTool._required_permissions == frozenset({'write', 'admin'})

    def test_multiple_permissions_or_semantics(self):
        """Multiple permissions are stored for OR check."""
        @requires_permission('a', 'b', 'c')
        async def multi_perm():
            pass

        assert multi_perm._required_permissions == frozenset({'a', 'b', 'c'})

    def test_single_permission(self):
        """Single permission works."""
        @requires_permission('read')
        async def single():
            pass

        assert single._required_permissions == frozenset({'read'})

    def test_empty_permissions(self):
        """Empty permissions results in empty frozenset."""
        @requires_permission()
        async def unrestricted():
            pass

        assert unrestricted._required_permissions == frozenset()

    def test_preserves_function_metadata(self):
        """Decorator preserves function name and docstring."""
        @requires_permission('admin')
        async def documented_func():
            '''This is the docstring.'''
            pass

        assert documented_func.__name__ == 'documented_func'
        assert 'docstring' in documented_func.__doc__

    def test_function_still_callable(self):
        """Decorated function is still callable."""
        @requires_permission('admin')
        def sync_func(x):
            return x * 2

        assert sync_func(5) == 10

    def test_async_function_still_callable(self):
        """Decorated async function is still callable."""
        @requires_permission('admin')
        async def async_func(x):
            return x * 2

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(async_func(5))
        assert result == 10

    def test_method_still_callable(self):
        """Decorated method in a class is still callable."""
        class MyToolkit:
            @requires_permission('write')
            def my_method(self, value: int) -> int:
                return value + 1

        toolkit = MyToolkit()
        assert toolkit.my_method(10) == 11
        assert hasattr(toolkit.my_method, '_required_permissions')
        # Access via class to check attribute
        assert MyToolkit.my_method._required_permissions == frozenset({'write'})

    def test_permission_is_frozenset(self):
        """Permissions are stored as frozenset (immutable)."""
        @requires_permission('a', 'b')
        def my_func():
            pass

        assert isinstance(my_func._required_permissions, frozenset)
        # Verify immutability by checking it's hashable
        assert hash(my_func._required_permissions) is not None

    def test_duplicate_permissions_deduplicated(self):
        """Duplicate permissions are automatically deduplicated by frozenset."""
        @requires_permission('read', 'read', 'write', 'write')
        def my_func():
            pass

        assert my_func._required_permissions == frozenset({'read', 'write'})
        assert len(my_func._required_permissions) == 2

    def test_class_with_decorated_methods(self):
        """Class can have multiple methods with different permissions."""
        class MultiPermToolkit:
            @requires_permission('read')
            def read_method(self):
                return "read"

            @requires_permission('write', 'admin')
            def write_method(self):
                return "write"

            def unrestricted_method(self):
                return "free"

        # Check each method has correct permissions
        assert MultiPermToolkit.read_method._required_permissions == frozenset({'read'})
        assert MultiPermToolkit.write_method._required_permissions == frozenset({'write', 'admin'})
        assert not hasattr(MultiPermToolkit.unrestricted_method, '_required_permissions')

    def test_nested_decorator_with_other_decorators(self):
        """Decorator works when stacked with other decorators."""
        def other_decorator(func):
            func._other_attr = True
            return func

        @other_decorator
        @requires_permission('admin')
        def stacked_func():
            pass

        assert stacked_func._required_permissions == frozenset({'admin'})
        assert stacked_func._other_attr is True

    def test_permission_strings_preserved_exactly(self):
        """Permission strings are preserved exactly as provided."""
        @requires_permission('jira.admin', 'github.write', 'custom:permission:123')
        def my_func():
            pass

        assert 'jira.admin' in my_func._required_permissions
        assert 'github.write' in my_func._required_permissions
        assert 'custom:permission:123' in my_func._required_permissions
