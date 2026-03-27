"""Tests for package-level imports — all public classes must be importable."""


class TestImports:
    def test_transport_import(self):
        """FilesystemTransport is importable from the package."""
        from parrot.transport.filesystem import FilesystemTransport

        assert FilesystemTransport is not None

    def test_config_import(self):
        """FilesystemTransportConfig is importable from the package."""
        from parrot.transport.filesystem import FilesystemTransportConfig

        assert FilesystemTransportConfig is not None

    def test_hook_import(self):
        """FilesystemHook is importable from the package."""
        from parrot.transport.filesystem import FilesystemHook

        assert FilesystemHook is not None

    def test_abstract_transport_import(self):
        """AbstractTransport is importable from parrot.transport.base."""
        from parrot.transport.base import AbstractTransport

        assert AbstractTransport is not None

    def test_abstract_transport_from_package(self):
        """AbstractTransport is importable from parrot.transport."""
        from parrot.transport import AbstractTransport

        assert AbstractTransport is not None

    def test_hook_config_from_models(self):
        """FilesystemHookConfig is importable from hooks models."""
        from parrot.autonomous.hooks.models import FilesystemHookConfig

        assert FilesystemHookConfig is not None

    def test_all_exports(self):
        """__all__ in filesystem package lists expected names."""
        import parrot.transport.filesystem as pkg

        assert "FilesystemTransport" in pkg.__all__
        assert "FilesystemTransportConfig" in pkg.__all__
        assert "FilesystemHook" in pkg.__all__

    def test_transport_is_abstract_subclass(self):
        """FilesystemTransport inherits from AbstractTransport."""
        from parrot.transport.base import AbstractTransport
        from parrot.transport.filesystem import FilesystemTransport

        assert issubclass(FilesystemTransport, AbstractTransport)
