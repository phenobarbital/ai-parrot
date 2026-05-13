"""Unit tests for Schema Overlay Pydantic models (TASK-1093)."""
import pytest
from uuid import uuid4

from parrot.knowledge.ontology.schema_overlay.models import DryRunReport, SchemaOverlayRow


class TestSchemaOverlayRow:
    def test_valid_construction_entity_type(self):
        row = SchemaOverlayRow(
            id=uuid4(),
            tenant_id="t",
            overlay_kind="entity_type",
            name="Project",
            definition={"collection": "projects"},
            state="proposed",
            asserted_by="admin",
        )
        assert row.overlay_kind == "entity_type"
        assert row.name == "Project"

    def test_valid_construction_relation_type(self):
        row = SchemaOverlayRow(
            id=uuid4(),
            tenant_id="t",
            overlay_kind="relation_type",
            name="manages",
            definition={"from": "Employee", "to": "Employee", "edge_collection": "manages"},
            state="pending_review",
            asserted_by="admin",
        )
        assert row.overlay_kind == "relation_type"

    def test_valid_construction_traversal_pattern(self):
        row = SchemaOverlayRow(
            id=uuid4(),
            tenant_id="t",
            overlay_kind="traversal_pattern",
            name="team_status",
            definition={
                "description": "Get team status",
                "query_template": "FOR v IN 1..2 OUTBOUND @start manages RETURN v",
            },
            state="proposed",
            asserted_by="admin",
        )
        assert row.overlay_kind == "traversal_pattern"

    def test_rejects_invalid_overlay_kind(self):
        with pytest.raises(Exception):
            SchemaOverlayRow(
                id=uuid4(),
                tenant_id="t",
                overlay_kind="invalid",
                name="X",
                definition={},
                state="proposed",
                asserted_by="a",
            )

    def test_rejects_invalid_state(self):
        with pytest.raises(Exception):
            SchemaOverlayRow(
                id=uuid4(),
                tenant_id="t",
                overlay_kind="entity_type",
                name="X",
                definition={},
                state="invalid",
                asserted_by="a",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            SchemaOverlayRow(
                id=uuid4(),
                tenant_id="t",
                overlay_kind="entity_type",
                name="X",
                definition={},
                state="proposed",
                asserted_by="a",
                extra="boom",
            )

    def test_optional_fields_default_to_none(self):
        row = SchemaOverlayRow(
            id=uuid4(),
            tenant_id="t",
            overlay_kind="entity_type",
            name="X",
            definition={},
            state="proposed",
            asserted_by="a",
        )
        assert row.reviewed_by is None
        assert row.rationale is None
        assert row.dry_run_report is None

    def test_all_valid_states(self):
        states = ["proposed", "pending_review", "approved", "rejected", "deprecated"]
        for state in states:
            row = SchemaOverlayRow(
                id=uuid4(),
                tenant_id="t",
                overlay_kind="entity_type",
                name=f"X_{state}",
                definition={},
                state=state,
                asserted_by="a",
            )
            assert row.state == state


class TestDryRunReport:
    def test_valid_success(self):
        report = DryRunReport(ok=True, checks=[], duration_ms=42)
        assert report.ok
        assert report.error is None

    def test_valid_failure(self):
        report = DryRunReport(
            ok=False,
            checks=[{"check_name": "aql_validation", "passed": False, "details": "syntax error"}],
            error="AQL validation failed",
            duration_ms=100,
        )
        assert not report.ok
        assert len(report.checks) == 1
        assert report.error == "AQL validation failed"

    def test_checks_default_empty(self):
        report = DryRunReport(ok=True, duration_ms=5)
        assert report.checks == []

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            DryRunReport(ok=True, checks=[], duration_ms=1, unexpected="boom")

    def test_duration_required(self):
        with pytest.raises(Exception):
            DryRunReport(ok=True)
