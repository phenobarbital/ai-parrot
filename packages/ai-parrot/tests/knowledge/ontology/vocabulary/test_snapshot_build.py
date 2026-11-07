"""Snapshot construction and trigram parity tests (FEAT-824 TASK-5262)."""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
import numpy as np
import pytest

from parrot.knowledge.ontology.vocabulary.closure import build_closure, materialise_inverses
from parrot.knowledge.ontology.vocabulary.contracts import VersionContent
from parrot.knowledge.ontology.vocabulary.snapshot import (
    SNAPSHOT_FORMAT_VERSION,
    build_snapshot,
    snapshot_path,
    trigram_similarity,
)
from parrot.knowledge.ontology.vocabulary.turtle import content_checksum, parse_turtle


def _version_content(golden_v1: bytes, golden_base_iri: str, *, checksum: str | None = None) -> VersionContent:
    """Build a fully materialized v1 fixture, including inverse relations and closure."""
    content = parse_turtle(golden_v1, base_iri=golden_base_iri, default_lang="es")
    content.relations.extend(materialise_inverses(content.relations))
    closure = build_closure(content.relations, (concept.iri for concept in content.concepts))
    return VersionContent(
        ontology_id="legal_es",
        version=1,
        checksum=checksum or content_checksum(content),
        content=content,
        closure=closure,
        embeddings={content.concepts[0].iri: [0.25, -0.5, 1.0]},
    )


def test_snapshot_path_layout(tmp_path: Path) -> None:
    """Snapshots are grouped by ontology and named for their version."""
    assert snapshot_path(tmp_path, "legal_es", 7) == tmp_path / "legal_es" / "v7.sqlite"


@pytest.mark.asyncio
async def test_build_snapshot_contents(tmp_path: Path, golden_v1: bytes, golden_base_iri: str) -> None:
    """The database contains all materialized rows, metadata, vectors and searchable labels."""
    version_content = _version_content(golden_v1, golden_base_iri)

    path = await build_snapshot(version_content, tmp_path)

    async with aiosqlite.connect(path) as database:
        metadata = dict(await database.execute_fetchall("SELECT key, value FROM meta"))
        concept_count = (await database.execute_fetchall("SELECT COUNT(*) FROM concept"))[0][0]
        closure_count = (await database.execute_fetchall("SELECT COUNT(*) FROM closure"))[0][0]
        extra_json, embedding = (
            await database.execute_fetchall(
                "SELECT extra, embedding FROM concept WHERE iri = ?",
                (version_content.content.concepts[0].iri,),
            )
        )[0]
        matches = await database.execute_fetchall(
            "SELECT iri, text FROM label_fts WHERE label_fts MATCH ?",
            ("Entidad",),
        )

    assert metadata["format_version"] == str(SNAPSHOT_FORMAT_VERSION)
    assert metadata["ontology_id"] == version_content.ontology_id
    assert metadata["version"] == str(version_content.version)
    assert metadata["checksum"] == version_content.checksum
    assert metadata["base_iri"] == golden_base_iri
    assert metadata["built_at"]
    assert concept_count == len(version_content.content.concepts)
    assert closure_count == len(version_content.closure)
    assert json.loads(extra_json) == version_content.content.concepts[0].extra
    assert np.frombuffer(embedding, dtype=np.float32).tolist() == [0.25, -0.5, 1.0]
    assert (golden_base_iri + "LegalEntity", "Entidad jurídica") in matches


@pytest.mark.asyncio
async def test_build_is_atomic_and_idempotent(tmp_path: Path, golden_v1: bytes, golden_base_iri: str) -> None:
    """Successful writes leave no temporary file, and identical rebuilds reuse the result."""
    version_content = _version_content(golden_v1, golden_base_iri)

    first = await build_snapshot(version_content, tmp_path)
    first_mtime = first.stat().st_mtime_ns
    second = await build_snapshot(version_content, tmp_path)

    assert second == first
    assert second.stat().st_mtime_ns == first_mtime
    assert not Path(f"{first}.tmp").exists()


@pytest.mark.asyncio
async def test_build_refuses_conflicting_checksum(tmp_path: Path, golden_v1: bytes, golden_base_iri: str) -> None:
    """A destination for different content is preserved rather than overwritten."""
    original = _version_content(golden_v1, golden_base_iri)
    path = await build_snapshot(original, tmp_path)
    before = path.read_bytes()
    conflicting = _version_content(golden_v1, golden_base_iri, checksum="different-checksum")

    with pytest.raises(ValueError, match="already exists with checksum"):
        await build_snapshot(conflicting, tmp_path)

    assert path.read_bytes() == before
    assert not Path(f"{path}.tmp").exists()


# Values recorded with PostgreSQL 16.6 and pg_trgm 1.6 using
# ``SELECT similarity(a, b)``. Accents remain distinct trigrams.
REFERENCE = [
    ("cat", "cat", 1.0),
    ("cat", "cats", 0.5),
    ("hello world", "hello there", 1.0 / 3.0),
    ("Entidad jurídica", "entidad juridica", 0.7),
    ("acción legal", "accion legal", 0.625),
    ("Public Law", "public-law", 1.0),
    ("café", "cafe", 3.0 / 7.0),
]


@pytest.mark.parametrize(("a", "b", "expected"), REFERENCE)
def test_trigram_similarity_reference_values(a: str, b: str, expected: float) -> None:
    """The pure-Python scores stay within the task's pg_trgm parity tolerance."""
    assert abs(trigram_similarity(a, b) - expected) <= 0.02


def test_trigram_similarity_empty_or_punctuation_only() -> None:
    """Inputs without word trigrams have zero similarity."""
    assert trigram_similarity("", "value") == 0.0
    assert trigram_similarity("---", "...") == 0.0
