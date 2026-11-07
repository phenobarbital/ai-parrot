"""Tests for vocabulary HTTP routes (FEAT-824 TASK-5268)."""
from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from parrot.knowledge.ontology.vocabulary.contracts import (
    ClosureRow,
    OntologyContent,
    ParsedConcept,
    ParsedLabel,
    ParsedRelation,
    ParsedStatement,
    VersionContent,
)
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound
from parrot.knowledge.ontology.vocabulary.http import register_routes


class FakeStore:
    """A fake ontology store for testing HTTP routes."""

    def __init__(self) -> None:
        self._ontologies: dict[str, VersionContent] = {}
        self._versions: dict[str, int] = {}

    def add_ontology(
        self,
        ontology_id: str,
        version: int = 1,
        checksum: str = "abc123",
    ) -> VersionContent:
        """Add a test ontology."""
        content = VersionContent(
            ontology_id=ontology_id,
            version=version,
            checksum=checksum,
            content=OntologyContent(
                base_iri=f"http://example.org/{ontology_id}/",
                concepts=[
                    ParsedConcept(
                        iri=f"http://example.org/{ontology_id}/Concept1",
                        kind="class",
                        pref_label="Test Concept",
                        definition="A test concept",
                    ),
                ],
                labels=[
                    ParsedLabel(
                        iri=f"http://example.org/{ontology_id}/Concept1",
                        lang="en",
                        kind="pref",
                        text="Test Concept",
                    ),
                ],
                relations=[],
                statements=[],
            ),
            closure=[],
            embeddings={},
        )
        self._ontologies[ontology_id] = content
        self._versions[ontology_id] = version
        return content

    async def version(self, ontology_id: str) -> int:
        """Get current version."""
        if ontology_id not in self._versions:
            raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
        return self._versions[ontology_id]

    async def load_version(self, ontology_id: str, version: int | None = None) -> VersionContent:
        """Load a specific version."""
        if ontology_id not in self._ontologies:
            raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
        if version is not None and version > self._versions[ontology_id]:
            raise OntologyVersionNotFound(
                f"Version {version} of ontology {ontology_id!r} was never published"
            )
        return self._ontologies[ontology_id]

    async def export(
        self,
        ontology_id: str,
        fmt: str = "turtle",
        *,
        as_of: int | None = None,
    ) -> bytes:
        """Export ontology."""
        if ontology_id not in self._ontologies:
            raise OntologyNotFound(f"Ontology {ontology_id!r} is not registered")
        if as_of is not None and as_of > self._versions[ontology_id]:
            raise OntologyVersionNotFound(
                f"Version {as_of} of ontology {ontology_id!r} was never published"
            )
        if fmt == "turtle":
            return b"@prefix ex: <http://example.org/> .\nex:Concept1 a ex:Class ."
        elif fmt == "jsonld":
            return b'{"@context": {}, "@graph": []}'
        raise ValueError(f"Unknown format: {fmt}")


def create_app(
    store: FakeStore,
    session: dict[str, Any] | None = None,
) -> web.Application:
    """Create a test application with the vocabulary routes."""
    app = web.Application()

    # Middleware to inject session
    @web.middleware
    async def session_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if session is not None:
            request["session"] = session
        return await handler(request)

    app.middlewares.append(session_middleware)
    app["ontology_store"] = store
    register_routes(app, prefix="/api/ontology")
    return app


@pytest.fixture
def fake_store() -> FakeStore:
    """Create a fake store with test data."""
    store = FakeStore()
    store.add_ontology("test-ontology", version=1, checksum="checksum-v1")
    store.add_ontology("tenant.tenant-a", version=2, checksum="checksum-tenant-a")
    return store


class TestAuthorization:
    """Tests for authorization rules."""

    async def test_http_auth_401_without_session(self, fake_store: FakeStore) -> None:
        """Request without session returns 401."""
        app = create_app(fake_store, session=None)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/version")
                assert resp.status == 401

    async def test_http_auth_403_other_tenant(self, fake_store: FakeStore) -> None:
        """Session with tenant_id='a' cannot access tenant.b ontology."""
        session = {"tenant_id": "tenant-a", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                # Access tenant.b ontology with tenant.a session
                resp = await client.get("/api/ontology/vocabularies/tenant.tenant-b/version")
                assert resp.status == 403

    async def test_http_auth_200_for_tenant_admin(self, fake_store: FakeStore) -> None:
        """topic_admin can access any tenant ontology."""
        session = {"tenant_id": "tenant-a", "groups": ["topic_admin"]}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                # topic_admin can access tenant.tenant-a
                resp = await client.get("/api/ontology/vocabularies/tenant.tenant-a/version")
                assert resp.status == 200

    async def test_http_auth_200_for_matching_tenant(self, fake_store: FakeStore) -> None:
        """Session tenant can access its own ontology."""
        session = {"tenant_id": "tenant-a", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/tenant.tenant-a/version")
                assert resp.status == 200

    async def test_http_auth_200_for_non_tenant_ontology(self, fake_store: FakeStore) -> None:
        """Non-tenant ontologies only require a session."""
        session = {"tenant_id": "any", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/version")
                assert resp.status == 200


class TestVersionRoute:
    """Tests for the /version endpoint."""

    async def test_version_payload(self, fake_store: FakeStore) -> None:
        """Version endpoint returns correct payload."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/version")
                assert resp.status == 200
                data = await resp.json()
                assert data["ontology_id"] == "test-ontology"
                assert data["version"] == 1
                assert data["checksum"] == "checksum-v1"

    async def test_unknown_ontology_404(self, fake_store: FakeStore) -> None:
        """Unknown ontology returns 404."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/unknown-ontology/version")
                assert resp.status == 404


class TestSnapshotRoute:
    """Tests for the /snapshot endpoint."""

    async def test_snapshot_streams_sqlite(
        self,
        fake_store: FakeStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Snapshot returns a valid SQLite file."""
        # Override ONTOLOGY_SNAPSHOT_DIR
        monkeypatch.setenv("ONTOLOGY_SNAPSHOT_DIR", str(tmp_path))

        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/snapshot")
                assert resp.status == 200
                assert resp.content_type == "application/vnd.sqlite3"

                # Read body and verify SQLite header
                body = await resp.read()
                assert body[:16] == b"SQLite format 3\x00"

                # Verify the file is a valid SQLite database
                db_path = tmp_path / "test-ontology" / "v1.sqlite"
                assert db_path.exists()

                # Check the database content
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute("SELECT value FROM meta WHERE key = 'ontology_id'")
                row = cursor.fetchone()
                assert row is not None
                assert row[0] == "test-ontology"
                conn.close()

    async def test_snapshot_specific_version(
        self,
        fake_store: FakeStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Snapshot with specific version parameter."""
        monkeypatch.setenv("ONTOLOGY_SNAPSHOT_DIR", str(tmp_path))

        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/snapshot?version=1")
                assert resp.status == 200
                assert resp.content_type == "application/vnd.sqlite3"

    async def test_snapshot_unknown_version_404(self, fake_store: FakeStore) -> None:
        """Unknown version returns 404."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/snapshot?version=999")
                assert resp.status == 404


class TestExportRoute:
    """Tests for the /export endpoint."""

    async def test_export_turtle(self, fake_store: FakeStore) -> None:
        """Export in Turtle format."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/export?fmt=turtle")
                assert resp.status == 200
                assert resp.content_type == "text/turtle"
                body = await resp.read()
                assert b"@prefix" in body

    async def test_export_jsonld(self, fake_store: FakeStore) -> None:
        """Export in JSON-LD format."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/export?fmt=jsonld")
                assert resp.status == 200
                assert resp.content_type == "application/ld+json"
                body = await resp.read()
                assert b'"@graph"' in body or b'"@context"' in body

    async def test_export_bad_format_400(self, fake_store: FakeStore) -> None:
        """Invalid format returns 400."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/export?fmt=xml")
                assert resp.status == 400

    async def test_export_default_turtle(self, fake_store: FakeStore) -> None:
        """Default format is Turtle."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/export")
                assert resp.status == 200
                assert resp.content_type == "text/turtle"

    async def test_export_with_as_of(self, fake_store: FakeStore) -> None:
        """Export with as_of parameter."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/test-ontology/export?as_of=1")
                assert resp.status == 200

    async def test_export_unknown_ontology_404(self, fake_store: FakeStore) -> None:
        """Unknown ontology returns 404."""
        session = {"tenant_id": "test", "groups": []}
        app = create_app(fake_store, session=session)
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/ontology/vocabularies/unknown/export")
                assert resp.status == 404
