"""Unit tests for FilesystemTransportConfig."""

import pytest
from pathlib import Path

from parrot.transport.filesystem.config import FilesystemTransportConfig


class TestFilesystemTransportConfig:
    """Tests for FilesystemTransportConfig defaults, validation, and overrides."""

    def test_defaults(self):
        """All default values are set correctly."""
        config = FilesystemTransportConfig()
        assert config.presence_interval == 10.0
        assert config.stale_threshold == 60.0
        assert config.scope_to_cwd is False
        assert config.poll_interval == 0.5
        assert config.use_inotify is True
        assert config.message_ttl == 3600.0
        assert config.keep_processed is True
        assert config.feed_retention == 500
        assert config.default_channels == ["general"]
        assert config.reservation_timeout == 300.0
        assert config.routes is None

    def test_path_resolution(self):
        """root_dir is resolved to absolute path."""
        config = FilesystemTransportConfig(root_dir="relative/path")
        assert config.root_dir.is_absolute()

    def test_default_root_dir_is_absolute(self):
        """Default root_dir (.parrot) is also resolved to absolute."""
        config = FilesystemTransportConfig()
        assert config.root_dir.is_absolute()
        assert config.root_dir.name == ".parrot"

    def test_custom_values(self, tmp_path: Path):
        """Custom values override defaults."""
        config = FilesystemTransportConfig(
            root_dir=tmp_path,
            poll_interval=1.0,
            use_inotify=False,
            feed_retention=100,
        )
        assert config.root_dir == tmp_path
        assert config.poll_interval == 1.0
        assert config.use_inotify is False
        assert config.feed_retention == 100

    def test_custom_channels(self):
        """Custom default_channels override the default list."""
        config = FilesystemTransportConfig(
            default_channels=["dev", "alerts"],
        )
        assert config.default_channels == ["dev", "alerts"]

    def test_routes_accepts_list(self):
        """Routes field accepts a list of routing rules."""
        rules = [{"pattern": "*.error", "target": "error-handler"}]
        config = FilesystemTransportConfig(routes=rules)
        assert config.routes == rules

    def test_import_from_package(self):
        """Import works from the package __init__."""
        from parrot.transport.filesystem import FilesystemTransportConfig as Cfg
        assert Cfg is FilesystemTransportConfig
