"""Unit tests for ConceptEmbeddingPipeline (FEAT-159 TASK-1085).

All tests mock the vector store and embedder — no real DB or LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.ontology.concept_embedding import (
    ConceptEmbeddingPipeline,
    ConceptSyncResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_concept(concept_id: str, label: str, synonyms=None, description=""):
    """Return a SimpleNamespace that acts as a concept object."""
    return SimpleNamespace(
        concept_id=concept_id,
        label=label,
        synonyms=synonyms or [],
        description=description,
    )


def make_pipeline(tmp_path: Path, *, delete_return=0):
    """Return a pipeline with a mock vector store."""
    vs = MagicMock()
    vs.add_documents = AsyncMock(return_value=None)
    vs.delete_documents_by_filter = AsyncMock(return_value=delete_return)
    embedder = MagicMock()
    pipeline = ConceptEmbeddingPipeline(
        vector_store=vs,
        embedder=embedder,
        ontology_dir=tmp_path,
        schema="ontology",
        table="concepts",
    )
    return pipeline, vs


# ---------------------------------------------------------------------------
# ConceptSyncResult
# ---------------------------------------------------------------------------


class TestConceptSyncResult:
    def test_is_frozen(self):
        result = ConceptSyncResult(added=1, updated=0, removed=0, unchanged=0, duration_ms=5)
        with pytest.raises(Exception):
            result.added = 99  # type: ignore[misc]

    def test_fields(self):
        result = ConceptSyncResult(added=1, updated=2, removed=3, unchanged=4, duration_ms=10)
        assert result.added == 1
        assert result.updated == 2
        assert result.removed == 3
        assert result.unchanged == 4
        assert result.duration_ms == 10


# ---------------------------------------------------------------------------
# Content hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        c1 = make_concept("c1", "Commissions", ["comisiones", "bonos"], "Earnings")
        c2 = make_concept("c1", "Commissions", ["bonos", "comisiones"], "Earnings")
        # Different synonym order → same hash
        assert pipeline._content_hash(c1) == pipeline._content_hash(c2)

    def test_label_change_changes_hash(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        c1 = make_concept("c1", "Commissions", ["x"])
        c2 = make_concept("c1", "Bonuses", ["x"])
        assert pipeline._content_hash(c1) != pipeline._content_hash(c2)

    def test_synonym_added_changes_hash(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        c1 = make_concept("c1", "Commissions", ["comisiones"])
        c2 = make_concept("c1", "Commissions", ["comisiones", "bonos"])
        assert pipeline._content_hash(c1) != pipeline._content_hash(c2)

    def test_description_change_changes_hash(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        c1 = make_concept("c1", "Commissions", [], "old desc")
        c2 = make_concept("c1", "Commissions", [], "new desc")
        assert pipeline._content_hash(c1) != pipeline._content_hash(c2)

    def test_dict_concept_hashed(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        c = {"concept_id": "c1", "label": "X", "synonyms": ["a"], "description": "d"}
        h = pipeline._content_hash(c)
        assert isinstance(h, str) and len(h) == 64


# ---------------------------------------------------------------------------
# Atomic cache write
# ---------------------------------------------------------------------------


class TestAtomicCacheWrite:
    def test_atomic_cache_write(self, tmp_path):
        """Hash cache file is written atomically (no partial writes)."""
        pipeline, _ = make_pipeline(tmp_path)
        hashes = {"c1": "aabbcc", "c2": "ddeeff"}
        pipeline._save_hash_cache("tenant1", hashes)
        cache_path = pipeline._cache_path("tenant1")
        assert cache_path.exists()
        loaded = json.loads(cache_path.read_text())
        assert loaded == hashes

    def test_load_missing_returns_empty(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        result = pipeline._load_hash_cache("no_such_tenant")
        assert result == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        pipeline, _ = make_pipeline(tmp_path)
        cache_dir = tmp_path / ".concept_hashes"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "bad.json").write_text("not json")
        result = pipeline._load_hash_cache("bad")
        assert result == {}


# ---------------------------------------------------------------------------
# sync() — core behaviour
# ---------------------------------------------------------------------------


class TestConceptEmbeddingPipelineSync:
    @pytest.mark.asyncio
    async def test_first_run_all_added(self, tmp_path):
        """5 Concepts, no hash cache → all 5 embedded, added=5."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [make_concept(f"c{i}", f"Label{i}") for i in range(5)]

        result = await pipeline.sync("acme", concepts)

        assert result.added == 5
        assert result.updated == 0
        assert result.removed == 0
        assert result.unchanged == 0
        # add_documents called once per concept
        assert vs.add_documents.call_count == 5
        # hash cache written
        cache_path = pipeline._cache_path("acme")
        assert cache_path.exists()

    @pytest.mark.asyncio
    async def test_no_change_no_embedding(self, tmp_path):
        """Re-run with identical concepts → unchanged=5; no embedding calls made."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [make_concept(f"c{i}", f"Label{i}") for i in range(5)]

        # First run seeds the cache
        await pipeline.sync("acme", concepts)
        vs.reset_mock()

        result = await pipeline.sync("acme", concepts)

        assert result.unchanged == 5
        assert result.added == 0
        assert result.updated == 0
        assert result.removed == 0
        vs.add_documents.assert_not_called()

    @pytest.mark.asyncio
    async def test_synonym_changed_re_embedded(self, tmp_path):
        """Add a synonym to one concept → only that concept re-embedded (updated=1)."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [
            make_concept("c1", "Commissions", ["comisiones"]),
            make_concept("c2", "Bonuses", ["bonos"]),
        ]
        await pipeline.sync("acme", concepts)
        vs.reset_mock()

        # Mutate one concept
        concepts_v2 = [
            make_concept("c1", "Commissions", ["comisiones", "nuevos"]),
            make_concept("c2", "Bonuses", ["bonos"]),
        ]
        result = await pipeline.sync("acme", concepts_v2)

        assert result.updated == 1
        assert result.unchanged == 1
        assert result.added == 0
        assert vs.add_documents.call_count == 1

    @pytest.mark.asyncio
    async def test_concept_removed(self, tmp_path):
        """Remove a concept → delete called; removed=1."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [
            make_concept("c1", "Commissions"),
            make_concept("c2", "Bonuses"),
        ]
        await pipeline.sync("acme", concepts)
        vs.reset_mock()

        # Only c1 remains
        result = await pipeline.sync("acme", [make_concept("c1", "Commissions")])

        assert result.removed == 1
        assert result.unchanged == 1
        vs.delete_documents_by_filter.assert_called_once_with(
            filter_dict={"tenant_id": "acme", "concept_id": "c2"},
            table="concepts",
            schema="ontology",
        )

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, tmp_path):
        """Two tenants with overlapping concept_ids → separate caches."""
        pipeline_a, vs_a = make_pipeline(tmp_path)
        pipeline_b, vs_b = make_pipeline(tmp_path)

        concepts = [make_concept("c1", "Commissions")]
        await pipeline_a.sync("tenant_a", concepts)
        await pipeline_b.sync("tenant_b", concepts)

        cache_a = pipeline_a._load_hash_cache("tenant_a")
        cache_b = pipeline_b._load_hash_cache("tenant_b")

        # Both contain c1 but are separate files
        assert "c1" in cache_a
        assert "c1" in cache_b
        assert pipeline_a._cache_path("tenant_a") != pipeline_b._cache_path("tenant_b")

    @pytest.mark.asyncio
    async def test_metadata_contains_tenant_and_concept_id(self, tmp_path):
        """Metadata passed to add_documents includes tenant_id and concept_id."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [make_concept("c1", "Commissions")]

        await pipeline.sync("acme", concepts)

        call_kwargs = vs.add_documents.call_args
        assert call_kwargs is not None
        meta_filters = call_kwargs.kwargs.get("metadata_filters") or call_kwargs[1].get(
            "metadata_filters"
        )
        assert meta_filters == {"tenant_id": "acme", "concept_id": "c1"}

    @pytest.mark.asyncio
    async def test_concept_without_id_skipped(self, tmp_path):
        """Concept with empty concept_id is skipped gracefully."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [
            make_concept("", "NoId"),
            make_concept("c1", "WithId"),
        ]
        result = await pipeline.sync("acme", concepts)
        assert result.added == 1  # only c1

    @pytest.mark.asyncio
    async def test_dict_concepts_work(self, tmp_path):
        """Concepts passed as dicts (not objects) are handled correctly."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [
            {"concept_id": "c1", "label": "Commissions", "synonyms": ["x"], "description": ""}
        ]
        result = await pipeline.sync("acme", concepts)
        assert result.added == 1

    @pytest.mark.asyncio
    async def test_hash_cache_updated_after_sync(self, tmp_path):
        """After sync, the on-disk cache reflects the current hashes."""
        pipeline, vs = make_pipeline(tmp_path)
        concepts = [make_concept("c1", "Commissions", ["comisiones"])]
        await pipeline.sync("acme", concepts)

        cache = pipeline._load_hash_cache("acme")
        expected_hash = pipeline._content_hash(concepts[0])
        assert cache["c1"] == expected_hash

    @pytest.mark.asyncio
    async def test_duration_ms_positive(self, tmp_path):
        """duration_ms is a non-negative integer."""
        pipeline, _ = make_pipeline(tmp_path)
        result = await pipeline.sync("acme", [])
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms >= 0
