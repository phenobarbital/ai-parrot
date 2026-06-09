"""
Tests for DatasetManagerHandler route registration.
"""
import importlib.util


def _read_manager_source() -> str:
    """Return the source of ``parrot.manager.manager`` from its install path.

    Resolves the module location via importlib instead of a hardcoded
    relative path, so the test survives the manager/handlers modules being
    relocated across distributions (e.g. the ai-parrot-server split).
    """
    spec = importlib.util.find_spec("parrot.manager.manager")
    assert spec is not None and spec.origin is not None, (
        "parrot.manager.manager could not be located"
    )
    with open(spec.origin) as f:
        return f.read()


class TestDatasetRouteRegistration:
    """Test that DatasetManagerHandler routes are properly configured."""

    def test_handler_import_from_datasets(self):
        """DatasetManagerHandler can be imported from handlers.datasets."""
        from parrot.handlers.datasets import DatasetManagerHandler
        assert DatasetManagerHandler is not None

    def test_handler_import_from_handlers_init(self):
        """DatasetManagerHandler can be imported from handlers package."""
        from parrot.handlers import DatasetManagerHandler
        assert DatasetManagerHandler is not None

    def test_manager_imports_handler(self):
        """BotManager module source includes DatasetManagerHandler import."""
        source = _read_manager_source()
        assert 'from ..handlers.datasets import DatasetManagerHandler' in source

    def test_handler_has_required_methods(self):
        """DatasetManagerHandler has all required HTTP method handlers."""
        from parrot.handlers.datasets import DatasetManagerHandler

        # Verify all HTTP methods are implemented
        assert hasattr(DatasetManagerHandler, 'get')
        assert callable(getattr(DatasetManagerHandler, 'get'))

        assert hasattr(DatasetManagerHandler, 'patch')
        assert callable(getattr(DatasetManagerHandler, 'patch'))

        assert hasattr(DatasetManagerHandler, 'put')
        assert callable(getattr(DatasetManagerHandler, 'put'))

        assert hasattr(DatasetManagerHandler, 'post')
        assert callable(getattr(DatasetManagerHandler, 'post'))

        assert hasattr(DatasetManagerHandler, 'delete')
        assert callable(getattr(DatasetManagerHandler, 'delete'))

    def test_handler_inherits_baseview(self):
        """DatasetManagerHandler inherits from BaseView."""
        from parrot.handlers.datasets import DatasetManagerHandler
        from navigator.views import BaseView

        assert issubclass(DatasetManagerHandler, BaseView)


class TestRouteConfiguration:
    """Test route configuration in BotManager."""

    def test_route_path_in_manager(self):
        """Route path '/api/v1/agents/datasets/{agent_id}' is registered."""
        source = _read_manager_source()

        # Verify route pattern exists in source
        assert "/api/v1/agents/datasets/{agent_id}" in source
        assert "DatasetManagerHandler" in source

    def test_route_uses_add_view(self):
        """Route uses router.add_view for class-based handler."""
        source = _read_manager_source()

        # Verify the route registration pattern
        assert "router.add_view(" in source
        assert "'/api/v1/agents/datasets/{agent_id}'" in source


class TestHandlerDecorators:
    """Test that handler has proper decorators."""

    def test_handler_is_authenticated(self):
        """DatasetManagerHandler has authentication decorator."""
        from parrot.handlers.datasets import DatasetManagerHandler

        # The @is_authenticated decorator is applied at class level
        # We verify the class definition includes the decorator
        import inspect
        source = inspect.getsource(DatasetManagerHandler)

        # The decorator applies at class definition
        assert "is_authenticated" in source or hasattr(
            DatasetManagerHandler, '_is_authenticated'
        )

    def test_handler_has_user_session(self):
        """DatasetManagerHandler has user_session decorator."""
        from parrot.handlers.datasets import DatasetManagerHandler

        import inspect
        source = inspect.getsource(DatasetManagerHandler)

        # The decorator applies at class definition
        assert "user_session" in source


class TestEndpointDocs:
    """Test endpoint documentation."""

    def test_handler_has_docstring(self):
        """DatasetManagerHandler has descriptive docstring."""
        from parrot.handlers.datasets import DatasetManagerHandler

        assert DatasetManagerHandler.__doc__ is not None
        assert "datasets" in DatasetManagerHandler.__doc__.lower()

    def test_get_method_documented(self):
        """GET method has docstring."""
        from parrot.handlers.datasets import DatasetManagerHandler

        assert DatasetManagerHandler.get.__doc__ is not None

    def test_patch_method_documented(self):
        """PATCH method has docstring."""
        from parrot.handlers.datasets import DatasetManagerHandler

        assert DatasetManagerHandler.patch.__doc__ is not None

    def test_put_method_documented(self):
        """PUT method has docstring."""
        from parrot.handlers.datasets import DatasetManagerHandler

        assert DatasetManagerHandler.put.__doc__ is not None

    def test_post_method_documented(self):
        """POST method has docstring."""
        from parrot.handlers.datasets import DatasetManagerHandler

        assert DatasetManagerHandler.post.__doc__ is not None

    def test_delete_method_documented(self):
        """DELETE method has docstring."""
        from parrot.handlers.datasets import DatasetManagerHandler

        assert DatasetManagerHandler.delete.__doc__ is not None
