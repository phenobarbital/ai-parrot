"""Tests for package-level imports — all public classes must be importable."""

import importlib

import pytest


class TestImports:
    def test_transport_import(self):
        """FilesystemTransport is importable from the package."""
        from parrot.autonomous.transport.filesystem import FilesystemTransport

        assert FilesystemTransport is not None

    def test_config_import(self):
        """FilesystemTransportConfig is importable from the package."""
        from parrot.autonomous.transport.filesystem import FilesystemTransportConfig

        assert FilesystemTransportConfig is not None

    def test_hook_import(self):
        """FilesystemHook is importable from the package."""
        from parrot.autonomous.transport.filesystem import FilesystemHook

        assert FilesystemHook is not None

    def test_abstract_transport_import(self):
        """AbstractTransport is importable from parrot.autonomous.transport.base."""
        from parrot.autonomous.transport.base import AbstractTransport

        assert AbstractTransport is not None

    def test_abstract_transport_from_package(self):
        """AbstractTransport is importable from parrot.autonomous.transport."""
        from parrot.autonomous.transport import AbstractTransport

        assert AbstractTransport is not None

    def test_hook_config_from_models(self):
        """FilesystemHookConfig is importable from core hooks models."""
        from navigator_eventbus.hooks.models import FilesystemHookConfig

        assert FilesystemHookConfig is not None

    def test_all_exports(self):
        """__all__ in filesystem package lists expected names."""
        import parrot.autonomous.transport.filesystem as pkg

        assert "FilesystemTransport" in pkg.__all__
        assert "FilesystemTransportConfig" in pkg.__all__
        assert "FilesystemHook" in pkg.__all__

    def test_transport_is_abstract_subclass(self):
        """FilesystemTransport inherits from AbstractTransport."""
        from parrot.autonomous.transport.base import AbstractTransport
        from parrot.autonomous.transport.filesystem import FilesystemTransport

        assert issubclass(FilesystemTransport, AbstractTransport)

    @pytest.mark.skip(
        reason=(
            "Post-merge regression guard for FEAT-196. "
            "parrot.transport still resolves pre-merge because the dev venv is an "
            "editable install of the main repo where packages/ai-parrot/src/parrot/transport/ "
            "has not yet been removed. Un-skip after feat-196-fix-parrot-transport is merged "
            "into dev and the venv is refreshed to verify the old namespace is gone."
        )
    )
    def test_old_import_path_raises(self):
        """Importing from the old parrot.transport path must raise ModuleNotFoundError.

        Post-merge regression guard: the parrot.transport namespace was removed in
        FEAT-196. If it ever reappears (e.g., an accidental shim), this test will
        catch it immediately.
        """
        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("parrot.transport")
