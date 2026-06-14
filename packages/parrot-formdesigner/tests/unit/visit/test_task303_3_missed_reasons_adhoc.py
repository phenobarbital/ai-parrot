"""Unit tests for TASK-303-3: Missed Reasons (per-tenant) + ad-hoc stops.

Tests cover:
- MissedReasonService CRUD (create, get, list, deactivate)
- Per-tenant isolation: tenant A cannot see tenant B's reasons
- VisitService.set_missed_reason(): transitions Shift→MISSED
- When ALL shifts are missed → Event transitions to EventStatus.MISSED
- VisitService.create_adhoc(): Event with is_adhoc=True, one Shift, Visit started
- DDL SQL string for PostgresMissedReasonStorage (no real DB)
"""

from __future__ import annotations


import pytest

from parrot_formdesigner.services.visit.missed_reasons import (
    InMemoryMissedReasonStorage,
    MissedReasonService,
    PostgresMissedReasonStorage,
)
from parrot_formdesigner.services.visit.models import (
    Event,
    EventStatus,
    Shift,
    ShiftStatus,
)
from parrot_formdesigner.services.visit.storage import InMemoryEventStorage
from parrot_formdesigner.services.visit.geofence import GeofenceValidator
from parrot_formdesigner.services.visit.visit_service import VisitService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reason_storage() -> InMemoryMissedReasonStorage:
    return InMemoryMissedReasonStorage()


@pytest.fixture
def reason_service(reason_storage) -> MissedReasonService:
    return MissedReasonService(storage=reason_storage)


@pytest.fixture
def event_storage() -> InMemoryEventStorage:
    return InMemoryEventStorage()


@pytest.fixture
def visit_service(event_storage) -> VisitService:
    return VisitService(
        event_storage=event_storage,
        submission_storage=None,
        partial_save_store=None,
        geofence_validator=GeofenceValidator(),
        registry=None,
        tenant="acme",
    )


@pytest.fixture
def two_shift_event(event_storage) -> Event:
    """Event with two pending shifts — used for multi-shift missed tests."""
    import asyncio

    shift1 = Shift(event_id="evt-multi", staff_id="staff-a")
    shift2 = Shift(event_id="evt-multi", staff_id="staff-b")
    ev = Event(
        event_id="evt-multi",
        org_node_id="store-001",
        shifts=[shift1, shift2],
        status=EventStatus.SCHEDULED,
        tenant="acme",
    )
    asyncio.get_event_loop().run_until_complete(
        event_storage.save(ev, tenant="acme")
    )
    return ev


@pytest.fixture
def one_shift_event(event_storage) -> Event:
    """Event with one pending shift."""
    import asyncio

    shift = Shift(event_id="evt-one", staff_id="staff-x")
    ev = Event(
        event_id="evt-one",
        org_node_id="store-002",
        shifts=[shift],
        status=EventStatus.SCHEDULED,
        tenant="acme",
    )
    asyncio.get_event_loop().run_until_complete(
        event_storage.save(ev, tenant="acme")
    )
    return ev


# ---------------------------------------------------------------------------
# MissedReasonService CRUD tests
# ---------------------------------------------------------------------------


class TestMissedReasonServiceCRUD:
    @pytest.mark.asyncio
    async def test_create_reason(self, reason_service):
        """Create a Missed Reason and get it back."""
        reason = await reason_service.create_reason("No stock", tenant="epson")
        assert reason.label == "No stock"
        assert reason.tenant == "epson"
        assert reason.active is True
        assert len(reason.reason_id) == 36  # UUID

    @pytest.mark.asyncio
    async def test_get_reason(self, reason_service):
        reason = await reason_service.create_reason("Staff sick", tenant="epson")
        fetched = await reason_service.get_reason(reason.reason_id, tenant="epson")
        assert fetched is not None
        assert fetched.label == "Staff sick"

    @pytest.mark.asyncio
    async def test_get_nonexistent_reason(self, reason_service):
        result = await reason_service.get_reason("no-such-id", tenant="epson")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_reasons(self, reason_service):
        await reason_service.create_reason("Reason 1", tenant="epson")
        await reason_service.create_reason("Reason 2", tenant="epson")
        reasons = await reason_service.list_reasons(tenant="epson")
        assert len(reasons) == 2

    @pytest.mark.asyncio
    async def test_deactivate_reason(self, reason_service):
        reason = await reason_service.create_reason("Temp", tenant="epson")
        result = await reason_service.deactivate_reason(reason.reason_id, tenant="epson")
        assert result is True
        reasons = await reason_service.list_reasons(tenant="epson")
        assert len(reasons) == 0  # deactivated reasons not listed

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent(self, reason_service):
        result = await reason_service.deactivate_reason("no-id", tenant="epson")
        assert result is False


# ---------------------------------------------------------------------------
# Per-tenant isolation tests
# ---------------------------------------------------------------------------


class TestMissedReasonTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_reasons(self, reason_service):
        """Per-tenant isolation: A ≠ B."""
        await reason_service.create_reason("A reason", tenant="tenant_a")
        await reason_service.create_reason("B reason", tenant="tenant_b")

        a_reasons = await reason_service.list_reasons(tenant="tenant_a")
        b_reasons = await reason_service.list_reasons(tenant="tenant_b")

        assert len(a_reasons) == 1
        assert len(b_reasons) == 1
        assert a_reasons[0].label == "A reason"
        assert b_reasons[0].label == "B reason"

    @pytest.mark.asyncio
    async def test_get_reason_cross_tenant_returns_none(self, reason_service):
        """get_reason() scoped by tenant — cross-tenant access returns None."""
        reason = await reason_service.create_reason("Private", tenant="tenant_a")
        result = await reason_service.get_reason(reason.reason_id, tenant="tenant_b")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_list_for_tenant_without_reasons(self, reason_service):
        await reason_service.create_reason("Some reason", tenant="tenant_a")
        result = await reason_service.list_reasons(tenant="tenant_b")
        assert result == []


# ---------------------------------------------------------------------------
# VisitService.set_missed_reason() tests
# ---------------------------------------------------------------------------


class TestSetMissedReason:
    @pytest.mark.asyncio
    async def test_set_missed_reason_transitions_shift(
        self, visit_service, one_shift_event, event_storage
    ):
        """Assigning missed reason transitions Shift → MISSED."""
        shift_id = one_shift_event.shifts[0].shift_id
        visit = await visit_service.set_missed_reason(
            one_shift_event.event_id, shift_id, "reason-001", tenant="acme"
        )
        assert visit.missed_reason_id == "reason-001"

        # Reload and verify shift status
        reloaded = await event_storage.load(one_shift_event.event_id, tenant="acme")
        shift = next(s for s in reloaded.shifts if s.shift_id == shift_id)
        assert shift.status == ShiftStatus.MISSED

    @pytest.mark.asyncio
    async def test_all_shifts_missed_transitions_event(
        self, visit_service, two_shift_event, event_storage
    ):
        """When ALL shifts are MISSED, Event transitions to EventStatus.MISSED."""
        shift1_id = two_shift_event.shifts[0].shift_id
        shift2_id = two_shift_event.shifts[1].shift_id

        await visit_service.set_missed_reason(
            two_shift_event.event_id, shift1_id, "r1", tenant="acme"
        )
        await visit_service.set_missed_reason(
            two_shift_event.event_id, shift2_id, "r2", tenant="acme"
        )

        reloaded = await event_storage.load(two_shift_event.event_id, tenant="acme")
        assert reloaded.status == EventStatus.MISSED

    @pytest.mark.asyncio
    async def test_partial_missed_does_not_transition_event(
        self, visit_service, two_shift_event, event_storage
    ):
        """Only one shift missed — Event should NOT be MISSED yet."""
        shift1_id = two_shift_event.shifts[0].shift_id

        await visit_service.set_missed_reason(
            two_shift_event.event_id, shift1_id, "r1", tenant="acme"
        )

        reloaded = await event_storage.load(two_shift_event.event_id, tenant="acme")
        assert reloaded.status != EventStatus.MISSED

    @pytest.mark.asyncio
    async def test_set_missed_reason_creates_visit_if_none(
        self, visit_service, one_shift_event, event_storage
    ):
        """set_missed_reason() creates a Visit even if none exists yet."""
        shift_id = one_shift_event.shifts[0].shift_id
        visit = await visit_service.set_missed_reason(
            one_shift_event.event_id, shift_id, "reason-xyz", tenant="acme"
        )
        assert visit is not None
        assert visit.missed_reason_id == "reason-xyz"

    @pytest.mark.asyncio
    async def test_set_missed_reason_unknown_event_raises(self, visit_service):
        with pytest.raises(ValueError):
            await visit_service.set_missed_reason(
                "no-event", "no-shift", "r1", tenant="acme"
            )

    @pytest.mark.asyncio
    async def test_set_missed_reason_unknown_shift_raises(
        self, visit_service, one_shift_event
    ):
        with pytest.raises(ValueError):
            await visit_service.set_missed_reason(
                one_shift_event.event_id, "no-such-shift", "r1", tenant="acme"
            )


# ---------------------------------------------------------------------------
# VisitService.create_adhoc() tests
# ---------------------------------------------------------------------------


class TestCreateAdhoc:
    @pytest.mark.asyncio
    async def test_adhoc_event_flagged(self, visit_service):
        """create_adhoc() returns Event with is_adhoc=True and one Shift."""
        event = await visit_service.create_adhoc("store-001", "staff-bob")
        assert event.is_adhoc is True
        assert len(event.shifts) == 1
        assert event.shifts[0].staff_id == "staff-bob"

    @pytest.mark.asyncio
    async def test_adhoc_event_has_active_visit(self, visit_service):
        """create_adhoc() immediately starts the Visit (check_in set)."""
        event = await visit_service.create_adhoc("store-001", "staff-bob")
        shift = event.shifts[0]
        assert shift.visit is not None
        assert shift.visit.check_in is not None

    @pytest.mark.asyncio
    async def test_adhoc_event_status_in_progress(self, visit_service):
        event = await visit_service.create_adhoc("store-001", "staff-bob")
        assert event.status == EventStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_adhoc_event_shift_in_progress(self, visit_service):
        event = await visit_service.create_adhoc("store-001", "staff-bob")
        assert event.shifts[0].status == ShiftStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_adhoc_event_persisted(self, visit_service, event_storage):
        event = await visit_service.create_adhoc("store-001", "staff-bob")
        loaded = await event_storage.load(event.event_id, tenant="acme")
        assert loaded is not None
        assert loaded.is_adhoc is True

    @pytest.mark.asyncio
    async def test_adhoc_uses_tenant(self, event_storage):
        """create_adhoc() uses the provided tenant."""
        svc = VisitService(
            event_storage=event_storage,
            submission_storage=None,
            partial_save_store=None,
            geofence_validator=GeofenceValidator(),
            registry=None,
            tenant="custom_tenant",
        )
        event = await svc.create_adhoc("store-001", "staff-x")
        assert event.tenant == "custom_tenant"


# ---------------------------------------------------------------------------
# PostgresMissedReasonStorage DDL string tests (no real DB)
# ---------------------------------------------------------------------------


class TestPostgresMissedReasonStorageDDL:
    def test_create_table_sql_uses_fieldsync_schema(self):
        store = PostgresMissedReasonStorage(pool=object())
        sql = store._create_table_sql()
        assert '"fieldsync"' in sql
        assert "missed_reasons" in sql
        assert "reason_id" in sql
        assert "tenant" in sql

    def test_upsert_sql_has_on_conflict(self):
        store = PostgresMissedReasonStorage(pool=object())
        sql = store._upsert_sql()
        assert "ON CONFLICT" in sql

    def test_list_sql_filters_by_tenant_and_active(self):
        store = PostgresMissedReasonStorage(pool=object())
        sql = store._list_sql()
        assert "tenant" in sql
        assert "active" in sql

    def test_invalid_schema_raises(self):
        with pytest.raises(ValueError):
            PostgresMissedReasonStorage(pool=object(), schema="bad-schema!")
