"""Shared fixtures for FilesystemTransport integration tests."""

import pytest

from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.transport import FilesystemTransport


@pytest.fixture
def fs_config(tmp_path):
    """Config with fast polling and no inotify for deterministic tests."""
    return FilesystemTransportConfig(
        root_dir=tmp_path,
        presence_interval=0.1,
        poll_interval=0.05,
        use_inotify=False,
        stale_threshold=1.0,
        message_ttl=60.0,
        feed_retention=100,
    )


@pytest.fixture
async def transport_a(fs_config):
    """Started transport for AgentA."""
    t = FilesystemTransport(agent_name="AgentA", config=fs_config)
    await t.start()
    yield t
    await t.stop()


@pytest.fixture
async def transport_b(fs_config):
    """Started transport for AgentB."""
    t = FilesystemTransport(agent_name="AgentB", config=fs_config)
    await t.start()
    yield t
    await t.stop()
