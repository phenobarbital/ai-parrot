"""Unit tests for Concept Catalog Pydantic models (TASK-1087)."""
import pytest
from datetime import datetime, timezone
from uuid import uuid4

from parrot.knowledge.ontology.concept_catalog.models import (
    CascadeAlert,
    ConceptRow,
    IsaEdgeRow,
)


class TestConceptRow:
    def test_valid_construction(self):
        row = ConceptRow(
            id=uuid4(),
            tenant_id="tenant-a",
            slug="sales_comp",
            label="Sales Compensation",
            state="proposed",
            asserted_by="user@example.com",
            effective_from=datetime.now(timezone.utc),
        )
        assert row.state == "proposed"
        assert row.synonyms == []

    def test_rejects_invalid_state(self):
        with pytest.raises(Exception):
            ConceptRow(
                id=uuid4(),
                tenant_id="t",
                slug="s",
                label="L",
                state="invalid",
                asserted_by="u",
                effective_from=datetime.now(timezone.utc),
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            ConceptRow(
                id=uuid4(),
                tenant_id="t",
                slug="s",
                label="L",
                state="proposed",
                asserted_by="u",
                effective_from=datetime.now(timezone.utc),
                unknown_field="boom",
            )

    def test_optional_fields_default_to_none(self):
        row = ConceptRow(
            id=uuid4(),
            tenant_id="t",
            slug="s",
            label="L",
            state="proposed",
            asserted_by="u",
            effective_from=datetime.now(timezone.utc),
        )
        assert row.description is None
        assert row.domain is None
        assert row.reviewed_by is None
        assert row.reviewed_at is None
        assert row.rationale is None
        assert row.effective_to is None

    def test_all_valid_states(self):
        states = ["proposed", "pending_review", "approved", "rejected", "deprecated"]
        for state in states:
            row = ConceptRow(
                id=uuid4(),
                tenant_id="t",
                slug=f"slug_{state}",
                label="L",
                state=state,
                asserted_by="u",
                effective_from=datetime.now(timezone.utc),
            )
            assert row.state == state

    def test_synonyms_list(self):
        row = ConceptRow(
            id=uuid4(),
            tenant_id="t",
            slug="s",
            label="L",
            state="proposed",
            asserted_by="u",
            effective_from=datetime.now(timezone.utc),
            synonyms=["comm", "commissions"],
        )
        assert len(row.synonyms) == 2


class TestIsaEdgeRow:
    def test_valid_construction(self):
        row = IsaEdgeRow(
            id=uuid4(),
            tenant_id="t",
            child_id=uuid4(),
            parent_tier="framework",
            parent_ref="Employee",
            state="proposed",
            asserted_by="user",
        )
        assert row.parent_tier == "framework"

    def test_tenant_tier(self):
        row = IsaEdgeRow(
            id=uuid4(),
            tenant_id="t",
            child_id=uuid4(),
            parent_tier="tenant",
            parent_ref=str(uuid4()),
            state="approved",
            asserted_by="u",
        )
        assert row.parent_tier == "tenant"

    def test_rejects_invalid_parent_tier(self):
        with pytest.raises(Exception):
            IsaEdgeRow(
                id=uuid4(),
                tenant_id="t",
                child_id=uuid4(),
                parent_tier="invalid",
                parent_ref="x",
                state="proposed",
                asserted_by="u",
            )

    def test_rejects_invalid_state(self):
        with pytest.raises(Exception):
            IsaEdgeRow(
                id=uuid4(),
                tenant_id="t",
                child_id=uuid4(),
                parent_tier="framework",
                parent_ref="Employee",
                state="invalid",
                asserted_by="u",
            )

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            IsaEdgeRow(
                id=uuid4(),
                tenant_id="t",
                child_id=uuid4(),
                parent_tier="framework",
                parent_ref="Employee",
                state="proposed",
                asserted_by="u",
                bad_field="x",
            )


class TestCascadeAlert:
    def test_valid_construction(self):
        alert = CascadeAlert(
            tenant_id="t",
            concept_id=uuid4(),
            concept_slug="sales",
            affected_edge_ids=[uuid4(), uuid4()],
            notified_at=datetime.now(timezone.utc),
        )
        assert len(alert.affected_edge_ids) == 2

    def test_empty_affected_edge_ids(self):
        alert = CascadeAlert(
            tenant_id="t",
            concept_id=uuid4(),
            concept_slug="sales",
            notified_at=datetime.now(timezone.utc),
        )
        assert alert.affected_edge_ids == []

    def test_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            CascadeAlert(
                tenant_id="t",
                concept_id=uuid4(),
                concept_slug="sales",
                notified_at=datetime.now(timezone.utc),
                extra_field="boom",
            )
