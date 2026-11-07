"""Offline snapshot store tests (FEAT-824 TASK-5263)."""

from __future__ import annotations

from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from parrot.knowledge.ontology.vocabulary.backends import create_ontology_store
from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses
from parrot.knowledge.ontology.vocabulary.contracts import VersionContent
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.snapshot import (
    HttpSnapshotSource,
    SnapshotOntologyStore,
    build_snapshot,
    snapshot_path,
)
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle

BASE = "https://ontology.parrot.dev/legal_es/"
ENTITY = BASE + "LegalEntity"
PERSON = BASE + "Person"


def _version_content(turtle: bytes, version: int) -> VersionContent:
    """Materialise one golden Turtle file (inverses and closure included) at ``version``."""
    content = parse_turtle(turtle, base_iri=BASE, default_lang="es")
    content.relations.extend(materialise_inverses(content.relations))
    closure = build_closure(content.relations, (concept.iri for concept in content.concepts))
    return VersionContent(
        ontology_id="legal_es",
        version=version,
        checksum=content_checksum(content),
        content=content,
        closure=closure,
        embeddings={ENTITY: [1.0, 0.0, 0.0], PERSON: [0.0, 1.0, 0.0]},
    )


@pytest.fixture
def snapshot_root(tmp_path: Path) -> Path:
    """Directory holding the snapshot files under test."""
    return tmp_path / "snapshots"


@pytest.fixture
def version_content(golden_v1: bytes) -> VersionContent:
    """The fully materialised v1 fixture."""
    return _version_content(golden_v1, 1)


class _UnreachableSource:
    """A source whose every call fails like a dead network."""

    async def latest_version(self, ontology_id: str) -> int:
        raise aiohttp.ClientError("network down")

    async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
        raise aiohttp.ClientError("network down")


class _BuildingSource:
    """A source that offers ``latest`` and writes that snapshot with build_snapshot."""

    def __init__(self, content: VersionContent, latest: int) -> None:
        self.content, self.latest, self.fetched = content, latest, []

    async def latest_version(self, ontology_id: str) -> int:
        return self.latest

    async def fetch(self, ontology_id: str, version: int, dest_root: Path) -> Path:
        self.fetched.append(version)
        return await build_snapshot(self.content.model_copy(update={"version": version}), dest_root)


@pytest.mark.asyncio
async def test_reads_from_local_file(snapshot_root: Path, version_content: VersionContent) -> None:
    """get / expand / neighbors / resolve work from the local file; no source means stale=False."""
    await build_snapshot(version_content, snapshot_root)
    store = SnapshotOntologyStore(snapshot_root)

    concept = await store.get("legal_es", ENTITY)
    assert concept is not None
    assert concept.pref_label == "Entidad jurídica"
    assert concept.kind == "class"
    assert concept.version == 1
    assert await store.get("legal_es", BASE + "Nope") is None

    status = await store.status("legal_es")
    assert (status.version, status.stale, status.backend) == (1, False, "snapshot")
    assert await store.version("legal_es") == 1

    assert PERSON in await store.expand("legal_es", [ENTITY])
    assert ENTITY in await store.expand("legal_es", [PERSON], direction="up")
    assert ENTITY in await store.expand("legal_es", [ENTITY], direction="up")
    assert ("http://www.w3.org/2000/01/rdf-schema#subClassOf", ENTITY) in await store.neighbors("legal_es", PERSON)

    exact = await store.resolve("legal_es", "entidad JURÍDICA")
    assert exact and exact[0].concept.iri == ENTITY and exact[0].matched_by == "exact"
    fuzzy = await store.resolve("legal_es", "Entidad juridica")
    assert fuzzy and fuzzy[0].concept.iri == ENTITY and fuzzy[0].matched_by == "trgm"
    assert await store.resolve("legal_es", "zzzzqqqq") == []
    vector = await store.resolve("legal_es", "zzzzqqqq", embedding=[0.0, 1.0, 0.0], k=1)
    assert [item.concept.iri for item in vector] == [PERSON] and vector[0].matched_by == "vector"
    await store.close()


@pytest.mark.asyncio
async def test_offline_source_reports_stale(snapshot_root: Path, version_content: VersionContent) -> None:
    """An unreachable source keeps serving the local file and reports stale=True."""
    await build_snapshot(version_content, snapshot_root)
    store = SnapshotOntologyStore(snapshot_root, source=_UnreachableSource())

    concept = await store.get("legal_es", ENTITY)
    assert concept is not None and concept.pref_label == "Entidad jurídica"
    status = await store.status("legal_es")
    assert (status.version, status.stale) == (1, True)
    await store.close()


@pytest.mark.asyncio
async def test_refresh_downloads_newer(snapshot_root: Path, version_content: VersionContent) -> None:
    """A source offering version 2 is fetched; the newest local file becomes current."""
    await build_snapshot(version_content, snapshot_root)
    source = _BuildingSource(version_content, latest=2)
    store = SnapshotOntologyStore(snapshot_root, source=source)

    status = await store.refresh("legal_es")
    assert (status.version, status.stale) == (2, False)
    assert source.fetched == [2]
    assert await store.version("legal_es") == 2
    concept = await store.get("legal_es", ENTITY)
    assert concept is not None and concept.version == 2
    await store.get("legal_es", ENTITY)
    assert source.fetched == [2]  # refreshed once per ontology
    await store.close()


@pytest.mark.asyncio
async def test_no_local_and_unreachable_raises(snapshot_root: Path) -> None:
    """No local file and no reachable source raises OntologyNotFound."""
    store = SnapshotOntologyStore(snapshot_root, source=_UnreachableSource())
    with pytest.raises(OntologyNotFound):
        await store.version("legal_es")
    with pytest.raises(OntologyNotFound):
        await SnapshotOntologyStore(snapshot_root).version("legal_es")
    await store.close()


@pytest.mark.asyncio
async def test_other_as_of_rejected(snapshot_root: Path, version_content: VersionContent) -> None:
    """A snapshot rejects every as_of except its own version."""
    await build_snapshot(version_content, snapshot_root)
    store = SnapshotOntologyStore(snapshot_root)
    assert (await store.get("legal_es", ENTITY, as_of=1)) is not None
    for bad in (2, 0):
        with pytest.raises(OntologyVersionNotFound):
            await store.get("legal_es", ENTITY, as_of=bad)
    with pytest.raises(OntologyVersionNotFound):
        await store.expand("legal_es", [ENTITY], as_of=2)
    with pytest.raises(OntologyVersionNotFound):
        await store.export("legal_es", as_of=2)
    await store.close()


@pytest.mark.asyncio
async def test_canonical_and_deprecated_excluded(snapshot_root: Path, golden_v2: bytes) -> None:
    """v2 deprecates Contract in favour of ModernContract: canonical maps it, resolve hides it."""
    await build_snapshot(_version_content(golden_v2, 2), snapshot_root)
    store = SnapshotOntologyStore(snapshot_root)
    assert await store.canonical("legal_es", [BASE + "Contract", ENTITY]) == {
        BASE + "Contract": BASE + "ModernContract"
    }
    assert all(item.concept.iri != BASE + "Contract" for item in await store.resolve("legal_es", "Contrato"))
    assert BASE + "Contract" not in await store.expand("legal_es", [ENTITY])
    assert BASE + "Contract" in await store.expand("legal_es", [ENTITY], include_deprecated=True)
    await store.close()


@pytest.mark.asyncio
async def test_export_round_trips_asserted_graph(snapshot_root: Path, version_content: VersionContent) -> None:
    """export yields Turtle that parses back to the asserted concepts."""
    await build_snapshot(version_content, snapshot_root)
    store = SnapshotOntologyStore(snapshot_root)
    data = await store.export("legal_es")
    reparsed = parse_turtle(data, base_iri=BASE, default_lang="es")
    assert {concept.iri for concept in reparsed.concepts} == {c.iri for c in version_content.content.concepts}
    assert not any(relation.inferred for relation in reparsed.relations)
    await store.close()


@pytest.mark.asyncio
async def test_http_source_against_local_server(tmp_path: Path, version_content: VersionContent) -> None:
    """HttpSnapshotSource downloads a snapshot from a local aiohttp server (streamed, atomic)."""
    served = await build_snapshot(version_content, tmp_path / "server")

    async def version(_: web.Request) -> web.Response:
        return web.json_response({"version": 1})

    async def snapshot(request: web.Request) -> web.Response:
        assert request.query["version"] == "1"
        return web.Response(body=served.read_bytes())

    app = web.Application()
    app.router.add_get("/vocabularies/legal_es/version", version)
    app.router.add_get("/vocabularies/legal_es/snapshot", snapshot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        source = HttpSnapshotSource(f"http://127.0.0.1:{port}")
        client_root = tmp_path / "client"
        store = SnapshotOntologyStore(client_root, source=source)
        concept = await store.get("legal_es", ENTITY)
        assert concept is not None and concept.pref_label == "Entidad jurídica"
        assert snapshot_path(client_root, "legal_es", 1).is_file()
        assert not list(client_root.rglob("*.download"))
        assert (await store.status("legal_es")).stale is False
        await store.close()
        await source.close()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_http_source_unreachable_is_client_error(tmp_path: Path) -> None:
    """A refused connection surfaces as aiohttp.ClientError, which the store turns into stale."""
    source = HttpSnapshotSource("http://127.0.0.1:1")
    with pytest.raises(aiohttp.ClientError):
        await source.latest_version("legal_es")
    await source.close()


def test_factory_via_registry(tmp_path: Path) -> None:
    """create_ontology_store('snapshot', ...) builds the store through the registry."""
    store = create_ontology_store("snapshot", snapshot_dir=tmp_path)
    assert isinstance(store, SnapshotOntologyStore)
    assert store.backend_name == "snapshot"
