"""Schema-plane wiring tests for ``DatabaseAgent``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.bots.database import DatabaseAgent
from parrot.bots.database.cache import CachePartition
from parrot.knowledge.wiki.schema.service import SchemaPlaneService


@pytest.mark.asyncio
async def test_plane_service_wires_partitions(fake_postgres_toolkit):
    """A supplied service configures the toolkit's cache partition."""
    plane = MagicMock()
    fake_postgres_toolkit.origin = "warehouse"
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit], schema_plane=plane)

    await agent.configure()

    partition = fake_postgres_toolkit.cache_partition
    assert partition is not None
    assert partition.plane is plane
    assert partition.plane_write is True
    assert partition.origin == "warehouse"
    assert partition.dialect == fake_postgres_toolkit.database_type


@pytest.mark.asyncio
async def test_plane_path_opens_service_and_wires_existing_partition(tmp_path, fake_postgres_toolkit, monkeypatch):
    """A directory path opens a writable plane and configures an existing partition."""
    plane = MagicMock()
    from_dir = MagicMock(return_value=plane)
    monkeypatch.setattr(SchemaPlaneService, "from_dir", from_dir)
    existing_partition = CachePartition(namespace="existing")
    fake_postgres_toolkit.cache_partition = existing_partition

    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit], schema_plane=tmp_path / "schema")
    await agent.configure()

    from_dir.assert_called_once_with(Path(tmp_path / "schema"), read_only=False)
    assert existing_partition.plane is plane
    assert existing_partition.plane_write is True
    assert existing_partition.origin == fake_postgres_toolkit.database_type
    assert existing_partition.dialect == fake_postgres_toolkit.database_type


@pytest.mark.asyncio
async def test_no_plane_leaves_partition_unconfigured(fake_postgres_toolkit):
    """No schema plane preserves the cache partition's default behavior."""
    agent = DatabaseAgent(toolkits=[fake_postgres_toolkit])

    await agent.configure()

    partition = fake_postgres_toolkit.cache_partition
    assert partition is not None
    assert partition.plane is None
    assert partition.plane_write is False
    assert partition.origin is None
    assert partition.dialect is None
