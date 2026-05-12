"""Unit tests for ConceptCatalogService (TASK-1088).

Uses MagicMock to avoid requiring a live Postgres database.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.knowledge.ontology.concept_catalog.models import CascadeAlert, ConceptRow
from parrot.knowledge.ontology.concept_catalog.service import (
    ConceptCatalogService,
    _validate_transition,
)
from parrot.knowledge.ontology.exceptions import (
    CycleError,
    InvalidTransitionError,
    SynonymConflictError,
)


# ── Mock helpers ──

def _make_pool(conn_mock: AsyncMock) -> MagicMock:
    """Build a pool mock that yields conn_mock from acquire()."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield conn_mock

    pool.acquire = _acquire
    return pool


def _make_conn(
    fetchval_return=None,
    fetch_return=None,
    fetchrow_return=None,
) -> AsyncMock:
    """Build a connection mock with transaction support."""
    conn = AsyncMock()
    conn.fetchval.return_value = fetchval_return
    conn.fetch.return_value = fetch_return or []
    conn.fetchrow.return_value = fetchrow_return
    conn.execute.return_value = None

    @asynccontextmanager
    async def _transaction():
        yield None

    conn.transaction = _transaction
    return conn


class TestValidateTransition:
    """Test the state machine validation helper."""

    def test_propose_to_pending_review(self):
        state = _validate_transition("concept", "submit", "proposed")
        assert state == "pending_review"

    def test_propose_to_approved(self):
        state = _validate_transition("concept", "approve", "proposed")
        assert state == "approved"

    def test_pending_review_to_approved(self):
        state = _validate_transition("concept", "approve", "pending_review")
        assert state == "approved"

    def test_approved_to_deprecated(self):
        state = _validate_transition("concept", "deprecate", "approved")
        assert state == "deprecated"

    def test_deprecated_to_proposed_restore(self):
        state = _validate_transition("concept", "restore", "deprecated")
        assert state == "proposed"

    def test_rejected_to_proposed_restore(self):
        state = _validate_transition("concept", "restore", "rejected")
        assert state == "proposed"

    def test_rejected_approve_fails(self):
        with pytest.raises(InvalidTransitionError) as exc_info:
            _validate_transition("concept", "approve", "rejected")
        assert exc_info.value.current_state == "rejected"

    def test_deprecated_approve_fails(self):
        with pytest.raises(InvalidTransitionError):
            _validate_transition("concept", "approve", "deprecated")

    def test_isa_edge_transition(self):
        state = _validate_transition("isa_edge", "approve", "proposed")
        assert state == "approved"


class TestConceptCatalogServiceInit:
    def test_init_stores_pool_and_logger(self):
        pool = MagicMock()
        svc = ConceptCatalogService(pool)
        assert svc._pool is pool
        assert svc.logger is not None


class TestProposeConcept:
    """Test propose_concept with mocked DB."""

    async def test_creates_row_and_returns_uuid(self):
        new_id = uuid4()
        conn = _make_conn(fetchval_return=new_id, fetch_return=[])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        result = await svc.propose_concept(
            tenant_id="tenant-a",
            slug="sales_comp",
            label="Sales Compensation",
            asserted_by="curator@test.com",
        )
        assert result == new_id

    async def test_synonym_collision_raises(self):
        # Return a conflicting row for synonym check
        conflict_row = {
            "slug": "existing_concept",
            "synonyms": ["commissions"],
        }
        conn = _make_conn(fetch_return=[conflict_row])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        with pytest.raises(SynonymConflictError) as exc_info:
            await svc.propose_concept(
                tenant_id="tenant-a",
                slug="comp",
                label="Comp",
                asserted_by="c",
                synonyms=["commissions"],
            )
        assert exc_info.value.synonym == "commissions"


class TestStateMachine:
    """Test state machine transitions."""

    async def test_approve_from_proposed_succeeds(self):
        concept_id = uuid4()
        row = {
            "id": concept_id,
            "tenant_id": "tenant-a",
            "state": "proposed",
            "reviewed_by": None,
            "reviewed_at": None,
            "rationale": None,
        }
        conn = _make_conn(fetchrow_return=row, fetch_return=[])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        # Should not raise
        await svc.approve(concept_id, "concept", "reviewer@test.com")

    async def test_approve_from_rejected_fails(self):
        concept_id = uuid4()
        row = {
            "id": concept_id,
            "tenant_id": "tenant-a",
            "state": "rejected",
        }
        conn = _make_conn(fetchrow_return=row)
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        with pytest.raises(InvalidTransitionError) as exc_info:
            await svc.approve(concept_id, "concept", "reviewer@test.com")
        assert exc_info.value.current_state == "rejected"

    async def test_reject_from_proposed(self):
        concept_id = uuid4()
        row = {
            "id": concept_id,
            "tenant_id": "tenant-a",
            "state": "proposed",
        }
        conn = _make_conn(fetchrow_return=row)
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        await svc.reject(concept_id, "concept", "reviewer")

    async def test_deprecate_from_approved_returns_cascade(self):
        concept_id = uuid4()
        row = {
            "id": concept_id,
            "tenant_id": "tenant-a",
            "state": "approved",
        }
        conn = _make_conn(fetchrow_return=row)
        # table_exists returns False (operational service not yet landed)
        conn.fetchval.return_value = False
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        result = await svc.deprecate(concept_id, "concept", "admin")
        # Returns None because topic_authority table doesn't exist yet
        assert result is None


class TestIsaEdge:
    """Test is_a edge operations."""

    async def test_cross_tier_framework_allowed(self):
        edge_id = uuid4()
        conn = _make_conn(fetchval_return=edge_id, fetch_return=[])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        result = await svc.propose_isa_edge(
            tenant_id="tenant-a",
            child_id=uuid4(),
            parent_tier="framework",
            parent_ref="Employee",
            asserted_by="curator",
        )
        assert result == edge_id

    async def test_cycle_detection_raises(self):
        child_id = uuid4()
        parent_id = uuid4()

        # Return edges that form a cycle: parent_id → child_id already exists
        # and we're proposing child_id → parent_id
        cycle_row = {
            "child_id": parent_id,
            "parent_ref": str(child_id),
            "parent_tier": "tenant",
        }
        conn = _make_conn(fetch_return=[cycle_row])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        with pytest.raises(CycleError):
            await svc.propose_isa_edge(
                tenant_id="tenant-a",
                child_id=child_id,
                parent_tier="tenant",
                parent_ref=str(parent_id),
                asserted_by="curator",
            )


class TestGetLiveConcepts:
    async def test_returns_approved_concepts(self):
        concept_id = uuid4()
        now = datetime.now(timezone.utc)
        row = {
            "id": concept_id,
            "tenant_id": "tenant-a",
            "slug": "sales",
            "label": "Sales",
            "synonyms": [],
            "description": None,
            "domain": None,
            "state": "approved",
            "asserted_by": "user",
            "reviewed_by": None,
            "reviewed_at": None,
            "rationale": None,
            "effective_from": now,
            "effective_to": None,
        }
        conn = _make_conn(fetch_return=[row])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        result = await svc.get_live_concepts("tenant-a")
        assert len(result) == 1
        assert isinstance(result[0], ConceptRow)
        assert result[0].state == "approved"

    async def test_returns_empty_when_no_concepts(self):
        conn = _make_conn(fetch_return=[])
        pool = _make_pool(conn)

        svc = ConceptCatalogService(pool)
        result = await svc.get_live_concepts("empty-tenant")
        assert result == []
