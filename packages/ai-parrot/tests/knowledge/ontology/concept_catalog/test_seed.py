"""Unit tests for seed_concepts_from_yaml (TASK-1090).

Uses mock ConceptCatalogService to avoid requiring a live database.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.concept_catalog.models import ConceptRow
from parrot.knowledge.ontology.concept_catalog.seed import seed_concepts_from_yaml
from parrot.knowledge.ontology.exceptions import SynonymConflictError


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_yaml(tmp_path: Path) -> Path:
    """Two-entity YAML ontology with one is_a edge."""
    content = textwrap.dedent("""
        name: test
        version: "1.0"
        entities:
          SalesDepartment:
            label: Sales Department
            description: The sales org
          SalesRep:
            label: Sales Representative
            parent_entity: SalesDepartment
    """)
    p = tmp_path / "test.ontology.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def empty_yaml(tmp_path: Path) -> Path:
    content = "name: empty\nversion: '1.0'\nentities: {}\n"
    p = tmp_path / "empty.yaml"
    p.write_text(content)
    return p


def _make_service(live_concepts: list | None = None) -> MagicMock:
    """Build a mock ConceptCatalogService."""
    svc = MagicMock()
    svc.get_live_concepts = AsyncMock(return_value=live_concepts or [])
    svc.propose_concept = AsyncMock(side_effect=lambda **kw: uuid4())
    svc.approve = AsyncMock(return_value=None)
    svc.propose_isa_edge = AsyncMock(return_value=uuid4())
    return svc


def _concept_row(slug: str) -> ConceptRow:
    from datetime import datetime, timezone
    return ConceptRow(
        id=uuid4(),
        tenant_id="tenant-a",
        slug=slug,
        label=slug.replace("_", " ").title(),
        synonyms=[],
        state="approved",
        asserted_by="seed",
        effective_from=datetime.now(timezone.utc),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSeedConceptsBasic:
    async def test_seeds_entities_from_yaml(self, sample_yaml: Path):
        svc = _make_service()
        count = await seed_concepts_from_yaml("tenant-a", sample_yaml, svc)
        assert count == 2  # SalesDepartment + SalesRep
        assert svc.propose_concept.call_count == 2
        assert svc.approve.call_count == 2

    async def test_returns_zero_for_empty_yaml(self, empty_yaml: Path):
        svc = _make_service()
        count = await seed_concepts_from_yaml("tenant-a", empty_yaml, svc)
        assert count == 0

    async def test_asserted_by_includes_file_hash(self, sample_yaml: Path):
        svc = _make_service()
        await seed_concepts_from_yaml("tenant-a", sample_yaml, svc)
        call_kwargs = svc.propose_concept.call_args_list[0].kwargs
        asserted_by = call_kwargs["asserted_by"]
        assert asserted_by.startswith("seed:yaml@")
        assert len(asserted_by) == len("seed:yaml@") + 12  # 12-char hash

    async def test_raises_for_missing_file(self, tmp_path: Path):
        svc = _make_service()
        with pytest.raises(FileNotFoundError):
            await seed_concepts_from_yaml("tenant-a", tmp_path / "absent.yaml", svc)

    async def test_seeds_isa_edge_when_parent_defined(self, sample_yaml: Path):
        svc = _make_service()
        await seed_concepts_from_yaml("tenant-a", sample_yaml, svc)
        # propose_isa_edge called once (SalesRep → SalesDepartment)
        assert svc.propose_isa_edge.call_count == 1


class TestSeedIdempotency:
    async def test_skips_existing_concepts(self, sample_yaml: Path):
        """Running twice on the same tenant: second run skips all."""
        existing = [
            _concept_row("salesdepartment"),
            _concept_row("salesrep"),
        ]
        svc = _make_service(live_concepts=existing)
        count = await seed_concepts_from_yaml("tenant-a", sample_yaml, svc)
        # Both already exist → 0 seeded
        assert count == 0
        assert svc.propose_concept.call_count == 0

    async def test_seed_twice_same_tenant_idempotent(self, sample_yaml: Path):
        """Simulate first run seeding, second run seeing existing concepts."""
        # First run — nothing exists
        svc = _make_service(live_concepts=[])
        count1 = await seed_concepts_from_yaml("tenant-a", sample_yaml, svc)
        assert count1 == 2

        # Second run — all concepts "now" exist
        existing = [
            _concept_row("salesdepartment"),
            _concept_row("salesrep"),
        ]
        svc2 = _make_service(live_concepts=existing)
        count2 = await seed_concepts_from_yaml("tenant-a", sample_yaml, svc2)
        assert count2 == 0

    async def test_synonym_conflict_is_skipped_gracefully(self, sample_yaml: Path):
        """SynonymConflictError during propose → concept skipped, no crash."""
        svc = _make_service()
        svc.propose_concept.side_effect = SynonymConflictError(
            "conflict", synonym="sales", existing_slug="existing"
        )
        count = await seed_concepts_from_yaml("tenant-a", sample_yaml, svc)
        assert count == 0  # all skipped due to conflict
