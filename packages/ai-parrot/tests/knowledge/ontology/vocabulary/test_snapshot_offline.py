"""Offline snapshot store tests (FEAT-824 TASK-5263)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import aiohttp
import pytest

from parrot.knowledge.ontology.vocabulary.contracts import VersionContent
from parrot.knowledge.ontology.vocabulary.snapshot import (
    HttpSnapshotSource,
    SnapshotOntologyStore,
    SnapshotSource,
    _create_snapshot,
    build_snapshot,
    snapshot_path,
)


@pytest.fixture
def tmp_snapshot_dir(tmp_path: Path) -> Path:
    """A temporary directory for snapshot files."""
    return tmp_path / "snapshots"


@pytest.fixture
def fake_source() -> SnapshotSource:
    """A fake snapshot source for testing."""

    class FakeSource(SnapshotSource):
        def __init__(self) -> None:
            self.versions: dict[str, int] = {}
            self.downloads: dict[tuple[str, int], Path] = {}

        async def latest_version(self, ontology_id: str) -> int:
            return self.versions.get(ontology_id, 0)

        async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
            path = snapshot_path(dest_root, ontology_id, version)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"fake snapshot {ontology_id} v{version}".encode())
            self.downloads[(ontology_id, version)] = path
            return path

    return FakeSource()


@pytest.fixture
def version_content(golden_v1: bytes, golden_base_iri: str) -> VersionContent:
    """Build a fully materialized v1 fixture, including inverse relations and closure."""
    from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses
    from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle

    content = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    content.relations.extend(materialise_inverses(content.relations))
    closure = build_closure(content.relations, (concept.iri for concept in content.concepts))
    return VersionContent(
        ontology_id="legal_es",
        version=1,
        checksum=content_checksum(content),
        content=content,
        closure=closure,
        embeddings={content.concepts[0].iri: [0.25, -0.5, 1.0]},
    )


@pytest.mark.asyncio
async def test_reads_from_local_file(
    tmp_snapshot_dir: Path, version_content: VersionContent, fake_source: SnapshotSource
) -> None:
    """Local file is read correctly; status.stale is False; no source configured."""
    # Build a snapshot
    await build_snapshot(version_content, tmp_snapshot_dir)

    # Create store without source
    store = SnapshotOntologyStore(snapshot_dir=tmp_snapshot_dir)

    # Read from local file
    concept = await store.get("legal_es", "https://ontology.parrot.dev/legal_es/LegalEntity")
    assert concept is not None
    assert concept.pref_label == "Entidad jurídica"
    assert concept.kind == "class"

    # Status should not be stale
    status = await store.status("legal_es")
    assert status.stale is False
    assert status.backend == "snapshot"

    # Resolve should work
    results = await store.resolve("legal_es", "Entidad")
    assert len(results) > 0
    assert results[0].concept.pref_label == "Entidad jurídica"

    await store.close()


@pytest.mark.asyncio
async def test_offline_source_reports_stale(
    tmp_snapshot_dir: Path, version_content: VersionContent, fake_source: SnapshotSource
) -> None:
    """Source.latest_version raises aiohttp.ClientError → stale=True; reads still served."""
    # Build a snapshot
    await build_snapshot(version_content, tmp_snapshot_dir)

    # Create store with unreachable source
    class UnreachableSource(SnapshotSource):
        async def latest_version(self, ontology_id: str) -> int:
            raise aiohttp.ClientError("Network error")

        async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
            raise aiohttp.ClientError("Network error")

    store = SnapshotOntologyStore(snapshot_dir=tmp_snapshot_dir, source=UnreachableSource())

    # Read should still work
    concept = await store.get("legal_es", "https://ontology.parrot.dev/legal_es/LegalEntity")
    assert concept is not None
    assert concept.pref_label == "Entidad jurídica"

    # Status should be stale
    status = await store.status("legal_es")
    assert status.stale is True
    assert status.backend == "snapshot"

    await store.close()


@pytest.mark.asyncio
async def test_refresh_downloads_newer(
    tmp_snapshot_dir: Path, version_content: VersionContent, fake_source: SnapshotSource
) -> None:
    """Fake source with version 2 writing via build_snapshot → version() == 2."""
    # Build v1
    await build_snapshot(version_content, tmp_snapshot_dir)
    fake_source.versions["legal_es"] = 1

    # Create store with source
    store = SnapshotOntologyStore(snapshot_dir=tmp_snapshot_dir, source=fake_source)

    # Refresh should download v2
    status = await store.refresh("legal_es")
    assert status.version == 2
    assert status.stale is False

    # version() should return 2
    version = await store.version("legal_es")
    assert version == 2

    # Get should work
    concept = await store.get("legal_es", "https://ontology.parrot.dev/legal_es/LegalEntity")
    assert concept is not None
    assert concept.version == 2

    await store.close()


@pytest.mark.asyncio
async def test_no_local_and_unreachable_raises(
    tmp_snapshot_dir: Path, version_content: VersionContent, fake_source: SnapshotSource
) -> None:
    """No local file and unreachable source → OntologyNotFound."""

    # Create store with unreachable source
    class UnreachableSource(SnapshotSource):
        async def latest_version(self, ontology_id: str) -> int:
            raise aiohttp.ClientError("Network error")

        async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
            raise aiohttp.ClientError("Network error")

    store = SnapshotOntologyStore(snapshot_dir=tmp_snapshot_dir, source=UnreachableSource())

    # Should raise OntologyNotFound
    with pytest.raises(Exception) as exc_info:
        await store.version("legal_es")
    assert "not found" in str(exc_info.value).lower()

    await store.close()


@pytest.mark.asyncio
async def test_other_as_of_rejected(
    tmp_snapshot_dir: Path, version_content: VersionContent, fake_source: SnapshotSource
) -> None:
    """as_of=snapshot_version+1 → OntologyVersionNotFound."""
    # Build v1
    await build_snapshot(version_content, tmp_snapshot_dir)
    fake_source.versions["legal_es"] = 1

    # Create store with source
    store = SnapshotOntologyStore(snapshot_dir=tmp_snapshot_dir, source=fake_source)

    # Refresh should download v2
    await store.refresh("legal_es")

    # Get with as_of=3 should raise
    with pytest.raises(Exception) as exc_info:
        await store.get("legal_es", "https://ontology.parrot.dev/legal_es/LegalEntity", as_of=3)
    assert "version" in str(exc_info.value).lower()

    await store.close()


@pytest.mark.asyncio
async def test_http_source_against_local_server(tmp_snapshot_dir: Path, version_content: VersionContent) -> None:
    """aiohttp.web app on 127.0.0.1:0 serving /vocabularies/x/version and /snapshot."""
    import aiohttp.web

    # Build v1
    await build_snapshot(version_content, tmp_snapshot_dir)

    # Create a simple HTTP server
    app = aiohttp.web.Application()

    async def version_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
        ontology_id = request.match_info["id"]
        return aiohttp.web.json_response({"version": 1})

    async def snapshot_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
        ontology_id = request.match_info["id"]
        version = int(request.query["version"])
        path = snapshot_path(tmp_snapshot_dir, ontology_id, version)
        return aiohttp.web.FileResponse(path)

    app.router.add_get("/vocabularies/{id}/version", version_handler)
    app.router.add_get("/vocabularies/{id}/snapshot", snapshot_handler)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    # Get the actual port
    port = site._server.sockets[0].getsockname()[1]

    # Create HttpSnapshotSource
    source = HttpSnapshotSource(f"http://127.0.0.1:{port}")

    # Test latest_version
    async with source:
        version = await source.latest_version("legal_es")
        assert version == 1

        # Test fetch
        dest = await source.fetch("legal_es", 1, tmp_snapshot_dir)
        assert dest.exists()
        # The file should be the snapshot file, not the checksum
        assert dest.read_bytes().startswith(b"SQLite format")

    await runner.cleanup()


@pytest.mark.asyncio
async def test_factory_via_registry(tmp_snapshot_dir: Path) -> None:
    """create_ontology_store("snapshot", snapshot_dir=tmp_path) builds the store."""
    from parrot.knowledge.ontology.vocabulary.backends import create_ontology_store

    store = await create_ontology_store("snapshot", snapshot_dir=tmp_snapshot_dir)
    assert isinstance(store, SnapshotOntologyStore)
    assert store.backend_name == "snapshot"
    assert store._root == tmp_snapshot_dir
    assert store._source is None

    await store.close()
