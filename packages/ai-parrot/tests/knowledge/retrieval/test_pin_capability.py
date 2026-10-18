"""pin.py consumes SourceCoherencePersistence (FEAT-540 M7 / Q4)."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.protocols import CapabilityUnavailable
from parrot.knowledge.retrieval import pin as pin_module
from parrot.knowledge.retrieval.pin import WorkspacePin, check_pin_coherence


def _workspace_pin() -> WorkspacePin:
    """Return a stable pin suitable for source-coherence checks."""
    return WorkspacePin(
        primary="repository",
        pins={"repository": "1234567"},
        pinned_at=datetime.now(UTC),
        weight_table_version="test",
    )


@pytest.mark.asyncio
async def test_pin_source_coherence_capability_uses_sqlite_file_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SQLite persistence instance supplies rows through ``file_hashes``."""
    content = b"source contents\n"
    ctx = object()
    persistence = SQLitePersistence(tmp_path / "graphindex")
    file_hashes = AsyncMock(return_value=[("source.py", "fc6456d42d3d12434f88d7b002e5be2bc1da77e0")])
    read_at_rev = AsyncMock(return_value=content)
    monkeypatch.setattr(persistence, "file_hashes", file_hashes)
    monkeypatch.setattr(pin_module, "read_at_rev", read_at_rev)

    report = await check_pin_coherence(_workspace_pin(), persistence, ctx, "repository", tmp_path)

    assert report.coherent
    assert report.sampled_paths == ("source.py",)
    file_hashes.assert_awaited_once_with(ctx)
    read_at_rev.assert_awaited_once_with(tmp_path, "1234567", "source.py")


@pytest.mark.asyncio
async def test_pin_source_coherence_requires_capability_before_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-capable persistence object fails before invoking git reads."""
    read_at_rev = AsyncMock()
    monkeypatch.setattr(pin_module, "read_at_rev", read_at_rev)

    with pytest.raises(CapabilityUnavailable, match="source_coherence"):
        await check_pin_coherence(_workspace_pin(), object(), object(), "repository", tmp_path)

    read_at_rev.assert_not_awaited()
