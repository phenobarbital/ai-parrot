"""Unit tests for TenantOntologyManager overlay composition (TASK-1098).

Tests that resolve_with_overlay() correctly composes YAML + PG overlay data
and that existing resolve() behavior is unchanged.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.concept_catalog.models import ConceptRow
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow
from parrot.knowledge.ontology.tenant import TenantOntologyManager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def base_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""
        name: base
        version: "1.0"
        entities:
          Employee:
            collection: employees
            key_field: employee_id
            properties:
              - employee_id:
                  type: string
                  required: true
        relations: {}
        traversal_patterns: {}
    """)
    p = tmp_path / "base.ontology.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def ontology_dir(base_yaml: Path) -> Path:
    return base_yaml.parent


@pytest.fixture
def manager_no_services(ontology_dir: Path) -> TenantOntologyManager:
    return TenantOntologyManager(ontology_dir=ontology_dir)


def _concept_row(slug: str) -> ConceptRow:
    return ConceptRow(
        id=uuid4(),
        tenant_id="tenant-a",
        slug=slug,
        label=slug.title(),
        synonyms=[],
        state="approved",
        asserted_by="seed",
        effective_from=datetime.now(timezone.utc),
    )


def _schema_row(name: str, kind: str = "entity_type") -> SchemaOverlayRow:
    definition = {"collection": f"{name}_coll"}
    return SchemaOverlayRow(
        id=uuid4(),
        tenant_id="tenant-a",
        overlay_kind=kind,
        name=name,
        definition=definition,
        state="approved",
        asserted_by="admin",
    )


def _make_concept_service(rows: list[ConceptRow]) -> MagicMock:
    svc = MagicMock()
    svc.get_live_concepts = AsyncMock(return_value=rows)
    return svc


def _make_schema_service(rows: list[SchemaOverlayRow]) -> MagicMock:
    svc = MagicMock()
    svc.get_pending = AsyncMock(return_value=rows)
    return svc


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_init_no_new_params(self):
        """Init with no new params works exactly as before."""
        mgr = TenantOntologyManager()
        assert mgr._concept_service is None
        assert mgr._schema_service is None

    def test_resolve_without_services_unchanged(self, manager_no_services, base_yaml):
        """resolve() with no PG services returns YAML-only ontology."""
        ctx = manager_no_services.resolve("tenant-a")
        assert ctx.ontology is not None
        assert "Employee" in ctx.ontology.entities

    def test_resolve_still_caches(self, manager_no_services):
        ctx1 = manager_no_services.resolve("tenant-a")
        ctx2 = manager_no_services.resolve("tenant-a")
        assert ctx1 is ctx2  # Same object from cache

    def test_list_tenants_unchanged(self, manager_no_services):
        before = manager_no_services.list_tenants()
        manager_no_services.resolve("tenant-a")
        after = manager_no_services.list_tenants()
        assert len(after) == len(before) + 1


class TestResolveWithConceptOverlay:
    async def test_approved_concepts_appear_in_merged_ontology(
        self, ontology_dir, base_yaml
    ):
        concepts = [_concept_row("sales_comp"), _concept_row("commissions")]
        concept_svc = _make_concept_service(concepts)

        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            concept_catalog_service=concept_svc,
        )
        ctx = await mgr.resolve_with_overlay("tenant-a")

        # Approved concept slugs should be in entities
        assert "sales_comp" in ctx.ontology.entities
        assert "commissions" in ctx.ontology.entities
        # YAML-base entity preserved
        assert "Employee" in ctx.ontology.entities

    async def test_empty_concept_list_is_safe(self, ontology_dir):
        concept_svc = _make_concept_service([])
        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            concept_catalog_service=concept_svc,
        )
        ctx = await mgr.resolve_with_overlay("tenant-a")
        assert ctx.ontology is not None

    async def test_concept_overlay_cached_separately(self, ontology_dir):
        concept_svc = _make_concept_service([_concept_row("project")])
        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            concept_catalog_service=concept_svc,
        )
        ctx1 = await mgr.resolve_with_overlay("tenant-a")
        ctx2 = await mgr.resolve_with_overlay("tenant-a")
        assert ctx1 is ctx2  # Cached


class TestResolveWithSchemaOverlay:
    async def test_approved_schema_overlays_appear_in_merged_ontology(
        self, ontology_dir
    ):
        schema_rows = [_schema_row("Project"), _schema_row("Contract")]
        schema_svc = _make_schema_service(schema_rows)

        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            schema_overlay_service=schema_svc,
        )
        ctx = await mgr.resolve_with_overlay("tenant-a")
        assert "Project" in ctx.ontology.entities
        assert "Contract" in ctx.ontology.entities

    async def test_non_approved_schema_rows_excluded(self, ontology_dir):
        # get_pending returns proposed + pending_review; manager filters approved
        schema_rows = [
            _schema_row("ProposedOnly"),  # state is "approved" by default in our helper
        ]
        schema_rows[0] = SchemaOverlayRow(
            id=uuid4(),
            tenant_id="tenant-a",
            overlay_kind="entity_type",
            name="ProposedOnly",
            definition={"collection": "proposed_col"},
            state="proposed",  # NOT approved
            asserted_by="admin",
        )
        schema_svc = _make_schema_service(schema_rows)
        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            schema_overlay_service=schema_svc,
        )
        ctx = await mgr.resolve_with_overlay("tenant-a")
        # Non-approved overlay should NOT be in entities
        assert "ProposedOnly" not in ctx.ontology.entities


class TestFallbackWithoutServices:
    async def test_falls_back_to_yaml_only_when_no_services(self, ontology_dir):
        mgr = TenantOntologyManager(ontology_dir=ontology_dir)
        ctx = await mgr.resolve_with_overlay("tenant-a")
        # Should still work, YAML only
        assert "Employee" in ctx.ontology.entities
