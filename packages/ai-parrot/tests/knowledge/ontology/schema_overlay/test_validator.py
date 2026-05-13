"""Unit tests for dry_run_overlay (TASK-1094).

Validates the sandboxed overlay validation pipeline.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema_overlay.models import DryRunReport, SchemaOverlayRow
from parrot.knowledge.ontology.schema_overlay.validator import dry_run_overlay
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
          Department:
            collection: departments
            key_field: dept_id
            properties:
              - dept_id:
                  type: string
                  required: true
        relations:
          belongs_to:
            from: Employee
            to: Department
            edge_collection: belongs_to
        traversal_patterns:
          find_team:
            description: Find team members
            query_template: "FOR v IN 1..2 OUTBOUND @start belongs_to RETURN v"
    """)
    p = tmp_path / "base.ontology.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def tenant_manager(tmp_path: Path, base_yaml: Path) -> TenantOntologyManager:
    mgr = TenantOntologyManager(
        ontology_dir=tmp_path,
        base_file="base.ontology.yaml",
    )
    return mgr


@pytest.fixture
def merger() -> OntologyMerger:
    return OntologyMerger()


def _overlay(
    kind: str,
    name: str,
    definition: dict,
    state: str = "pending_review",
) -> SchemaOverlayRow:
    return SchemaOverlayRow(
        id=uuid4(),
        tenant_id="tenant-a",
        overlay_kind=kind,
        name=name,
        definition=definition,
        state=state,
        asserted_by="admin",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestValidEntityOverlay:
    async def test_new_entity_passes(self, tenant_manager, merger):
        overlay = _overlay(
            "entity_type", "Project",
            {"collection": "projects"},
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert report.ok
        assert report.error is None

    async def test_all_checks_pass(self, tenant_manager, merger):
        overlay = _overlay(
            "entity_type", "Contract",
            {"collection": "contracts"},
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert all(c.passed for c in report.checks)  # N3 fix: checks are DryRunCheck objects


class TestFrameworkOverrideBlocked:
    async def test_employee_entity_blocked(self, tenant_manager, merger):
        overlay = _overlay(
            "entity_type", "Employee",
            {"collection": "employees_v2"},
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert not report.ok
        assert any("FrameworkOverrideError" in (c.details or "") for c in report.checks)

    async def test_framework_relation_blocked(self, tenant_manager, merger):
        overlay = _overlay(
            "relation_type", "belongs_to",
            {"from": "Employee", "to": "Department", "edge_collection": "bt_v2"},
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert not report.ok

    async def test_framework_pattern_blocked(self, tenant_manager, merger):
        overlay = _overlay(
            "traversal_pattern", "find_team",
            {
                "description": "Override find_team",
                "query_template": "FOR v IN 1..2 OUTBOUND @start belongs_to RETURN v",
            },
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert not report.ok


class TestAQLValidation:
    async def test_valid_traversal_pattern_passes(self, tenant_manager, merger):
        overlay = _overlay(
            "traversal_pattern", "new_pattern",
            {
                "description": "Safe query",
                "query_template": "FOR v IN 1..2 OUTBOUND @start belongs_to RETURN v",
            },
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert report.ok
        aql_check = next((c for c in report.checks if c.check_name == "aql_validation"), None)
        assert aql_check is not None
        assert aql_check.passed

    async def test_mutation_aql_fails(self, tenant_manager, merger):
        overlay = _overlay(
            "traversal_pattern", "bad_pattern",
            {
                "description": "Broken",
                "query_template": "FOR doc IN employees REMOVE doc IN employees",
            },
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert not report.ok
        aql_check = next((c for c in report.checks if c.check_name == "aql_validation"), None)
        assert aql_check is not None
        assert not aql_check.passed

    async def test_empty_aql_fails(self, tenant_manager, merger):
        overlay = _overlay(
            "traversal_pattern", "empty_aql",
            {
                "description": "No query",
                "query_template": "",
            },
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert not report.ok


class TestSandboxIsolation:
    async def test_cache_not_mutated_after_successful_dry_run(self, tenant_manager, merger):
        tenants_before = tenant_manager.list_tenants()
        overlay = _overlay(
            "entity_type", "NewProject",
            {"collection": "new_projects"},
        )
        await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        # Cache should not have grown
        assert tenant_manager.list_tenants() == tenants_before

    async def test_cache_not_mutated_after_failed_dry_run(self, tenant_manager, merger):
        tenants_before = tenant_manager.list_tenants()
        overlay = _overlay(
            "entity_type", "Employee",
            {"collection": "employees_bad"},
        )
        await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert tenant_manager.list_tenants() == tenants_before


class TestDurationTracking:
    async def test_report_has_positive_duration(self, tenant_manager, merger):
        overlay = _overlay(
            "entity_type", "TimedEntity",
            {"collection": "timed"},
        )
        report = await dry_run_overlay("tenant-a", overlay, tenant_manager, merger)
        assert report.duration_ms >= 0
