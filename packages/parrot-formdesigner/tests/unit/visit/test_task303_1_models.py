"""Unit tests for TASK-303-1: Event/Shift/Visit models + state machine + EventStorage.

Tests cover:
- Model defaults and validation
- EventStatus / ShiftStatus state machine (valid + invalid transitions)
- EventService CRUD + transition
- ShiftService.assign_staff() including no-overlap enforcement
- EventStorage round-trip (InMemoryEventStorage)
- DDL string test for PostgresEventStorage
- Tenant isolation
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.services.visit.models import (
    Event,
    EventStatus,
    GpsCoord,
    MissedReason,
    Shift,
    ShiftStatus,
    Visit,
    EVENT_TRANSITIONS,
    SHIFT_TRANSITIONS,
)
from parrot_formdesigner.services.visit.errors import (
    InvalidTransitionError,
    OverlappingShiftError,
)
from parrot_formdesigner.services.visit.storage import (
    InMemoryEventStorage,
    PostgresEventStorage,
)
from parrot_formdesigner.services.visit.event_service import EventService
from parrot_formdesigner.services.visit.shift_service import ShiftService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def storage() -> InMemoryEventStorage:
    return InMemoryEventStorage()


@pytest.fixture
def mock_registry():
    """A minimal FormRegistry mock (not needed for Model tests, but required
    by EventService constructor)."""
    from unittest.mock import AsyncMock, MagicMock
    reg = MagicMock()
    reg.get = AsyncMock(return_value=None)
    reg.default_tenant = "default"
    return reg


@pytest.fixture
def event_service(storage, mock_registry) -> EventService:
    return EventService(storage=storage, registry=mock_registry, tenant="epson")


@pytest.fixture
def shift_service(storage) -> ShiftService:
    return ShiftService(storage=storage, tenant="epson")


@pytest.fixture
def sample_event() -> Event:
    return Event(
        org_node_id="store-001",
        recap_ids=["recap-form-001"],
        shifts=[
            Shift(event_id="evt-001", staff_id="staff-001"),
        ],
        meta={
            "geofence_lat": 40.7128,
            "geofence_lon": -74.0060,
            "geofence_radius_m": 200,
        },
        tenant="epson",
    )


# ---------------------------------------------------------------------------
# Model default tests
# ---------------------------------------------------------------------------


class TestVisitModelDefaults:
    def test_visit_defaults(self):
        """Visit defaults: gps_outside=False, breadcrumb=[], submission_id=None."""
        v = Visit(shift_id="s1")
        assert v.gps_outside is False
        assert v.gps_breadcrumb == []
        assert v.submission_id is None
        assert v.missed_reason_id is None
        assert v.check_in is None
        assert v.check_out is None

    def test_visit_has_uuid(self):
        v1 = Visit(shift_id="s1")
        v2 = Visit(shift_id="s1")
        assert v1.visit_id != v2.visit_id

    def test_shift_defaults(self):
        s = Shift(event_id="e1", staff_id="user-1")
        assert s.status == ShiftStatus.PENDING
        assert s.visit is None

    def test_event_defaults(self):
        e = Event(org_node_id="store-1")
        assert e.status == EventStatus.REQUESTED
        assert e.recap_ids == []
        assert e.shifts == []
        assert e.is_adhoc is False

    def test_gps_coord_extra_forbidden(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GpsCoord(lat=1.0, lon=2.0, unknown_field="oops")

    def test_event_extra_forbidden(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Event(org_node_id="x", unknown="oops")

    def test_missed_reason_model(self):
        r = MissedReason(label="No stock", tenant="epson")
        assert r.active is True
        assert len(r.reason_id) == 36  # UUID


# ---------------------------------------------------------------------------
# State machine — EventStatus
# ---------------------------------------------------------------------------


class TestEventStateMachine:
    def test_valid_transitions_requested_to_scheduled(self):
        assert EventStatus.SCHEDULED in EVENT_TRANSITIONS[EventStatus.REQUESTED]

    def test_valid_transitions_scheduled_to_in_progress(self):
        assert EventStatus.IN_PROGRESS in EVENT_TRANSITIONS[EventStatus.SCHEDULED]

    def test_valid_transitions_in_progress_to_completed(self):
        assert EventStatus.COMPLETED in EVENT_TRANSITIONS[EventStatus.IN_PROGRESS]

    def test_terminal_states_have_no_transitions(self):
        assert EVENT_TRANSITIONS[EventStatus.COMPLETED] == set()
        assert EVENT_TRANSITIONS[EventStatus.CANCELLED] == set()
        assert EVENT_TRANSITIONS[EventStatus.MISSED] == set()

    def test_invalid_transition_requested_to_completed(self):
        assert EventStatus.COMPLETED not in EVENT_TRANSITIONS[EventStatus.REQUESTED]


class TestShiftStateMachine:
    def test_valid_pending_to_in_progress(self):
        assert ShiftStatus.IN_PROGRESS in SHIFT_TRANSITIONS[ShiftStatus.PENDING]

    def test_valid_in_progress_to_completed(self):
        assert ShiftStatus.COMPLETED in SHIFT_TRANSITIONS[ShiftStatus.IN_PROGRESS]

    def test_terminal_states_have_no_transitions(self):
        assert SHIFT_TRANSITIONS[ShiftStatus.COMPLETED] == set()
        assert SHIFT_TRANSITIONS[ShiftStatus.MISSED] == set()


# ---------------------------------------------------------------------------
# EventService tests
# ---------------------------------------------------------------------------


class TestEventService:
    @pytest.mark.asyncio
    async def test_create_event_with_shifts(self, event_service):
        """create_event() with N shifts produces Event with len(shifts)==N."""
        event = await event_service.create_event({
            "org_node_id": "store-001",
            "recap_ids": ["f1"],
            "shifts": [
                {"event_id": "dummy", "staff_id": "staff-1"},
                {"event_id": "dummy", "staff_id": "staff-2"},
            ],
        })
        assert len(event.shifts) == 2
        assert event.tenant == "epson"

    @pytest.mark.asyncio
    async def test_get_event(self, event_service, storage):
        event = await event_service.create_event({"org_node_id": "store-1"})
        fetched = await event_service.get_event(event.event_id)
        assert fetched is not None
        assert fetched.event_id == event.event_id

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, event_service):
        result = await event_service.get_event("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_events(self, event_service):
        await event_service.create_event({"org_node_id": "store-1"})
        await event_service.create_event({"org_node_id": "store-2"})
        events = await event_service.list_events()
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_event_state_machine_valid(self, event_service):
        """Valid transitions succeed."""
        event = await event_service.create_event({
            "org_node_id": "s1",
            "status": "requested",
        })
        event = await event_service.transition(event.event_id, EventStatus.SCHEDULED)
        assert event.status == EventStatus.SCHEDULED

        event = await event_service.transition(event.event_id, EventStatus.IN_PROGRESS)
        assert event.status == EventStatus.IN_PROGRESS

        event = await event_service.transition(event.event_id, EventStatus.COMPLETED)
        assert event.status == EventStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_event_state_machine_invalid(self, event_service):
        """Invalid transition raises InvalidTransitionError."""
        event = await event_service.create_event({
            "org_node_id": "s1",
            "status": "requested",
        })
        with pytest.raises(InvalidTransitionError):
            await event_service.transition(event.event_id, EventStatus.COMPLETED)

    @pytest.mark.asyncio
    async def test_transition_unknown_event_raises(self, event_service):
        with pytest.raises(ValueError):
            await event_service.transition("no-such-id", EventStatus.SCHEDULED)


# ---------------------------------------------------------------------------
# ShiftService tests
# ---------------------------------------------------------------------------


class TestShiftService:
    @pytest.mark.asyncio
    async def test_assign_staff(self, storage, shift_service):
        """assign_staff() returns Shift with correct staff_id."""
        event = Event(org_node_id="store-1", tenant="epson")
        await storage.save(event, tenant="epson")

        shift = await shift_service.assign_staff(event.event_id, "staff-42")
        assert shift.staff_id == "staff-42"
        assert shift.event_id == event.event_id

    @pytest.mark.asyncio
    async def test_assign_staff_persists_shift_in_event(self, storage, shift_service):
        event = Event(org_node_id="store-1", tenant="epson")
        await storage.save(event, tenant="epson")

        await shift_service.assign_staff(event.event_id, "staff-x")
        reloaded = await storage.load(event.event_id, tenant="epson")
        assert len(reloaded.shifts) == 1
        assert reloaded.shifts[0].staff_id == "staff-x"

    @pytest.mark.asyncio
    async def test_overlapping_shifts_rejected(self, storage, shift_service):
        """assign_staff() rejects overlapping active shifts of the same rep."""
        from datetime import datetime, timezone

        event1 = Event(org_node_id="store-1", tenant="epson")
        await storage.save(event1, tenant="epson")
        event2 = Event(org_node_id="store-2", tenant="epson")
        await storage.save(event2, tenant="epson")

        start = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc)

        # First assignment — should succeed
        await shift_service.assign_staff(
            event1.event_id, "staff-bob",
            scheduled_start=start, scheduled_end=end,
        )

        # Second assignment in overlapping window — should fail
        with pytest.raises(OverlappingShiftError):
            await shift_service.assign_staff(
                event2.event_id, "staff-bob",
                scheduled_start=start, scheduled_end=end,
            )

    @pytest.mark.asyncio
    async def test_non_overlapping_shifts_allowed(self, storage, shift_service):
        """Non-overlapping shifts for the same rep are allowed."""
        from datetime import datetime, timezone

        event1 = Event(org_node_id="store-1", tenant="epson")
        await storage.save(event1, tenant="epson")
        event2 = Event(org_node_id="store-2", tenant="epson")
        await storage.save(event2, tenant="epson")

        shift1 = await shift_service.assign_staff(
            event1.event_id, "staff-bob",
            scheduled_start=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
            scheduled_end=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
        )
        shift2 = await shift_service.assign_staff(
            event2.event_id, "staff-bob",
            scheduled_start=datetime(2026, 6, 15, 13, 0, tzinfo=timezone.utc),
            scheduled_end=datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc),
        )
        assert shift1.staff_id == "staff-bob"
        assert shift2.staff_id == "staff-bob"

    @pytest.mark.asyncio
    async def test_assign_staff_unknown_event_raises(self, shift_service):
        with pytest.raises(ValueError):
            await shift_service.assign_staff("no-such-event", "staff-x")


# ---------------------------------------------------------------------------
# InMemoryEventStorage round-trip
# ---------------------------------------------------------------------------


class TestInMemoryEventStorage:
    @pytest.mark.asyncio
    async def test_save_and_load(self, sample_event, storage):
        await storage.save(sample_event, tenant="epson")
        loaded = await storage.load(sample_event.event_id, tenant="epson")
        assert loaded is not None
        assert loaded.event_id == sample_event.event_id
        assert loaded.org_node_id == "store-001"

    @pytest.mark.asyncio
    async def test_save_uses_event_tenant_fallback(self, storage):
        event = Event(org_node_id="x", tenant="myco")
        await storage.save(event)
        loaded = await storage.load(event.event_id, tenant="myco")
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_delete(self, sample_event, storage):
        await storage.save(sample_event, tenant="epson")
        result = await storage.delete(sample_event.event_id, tenant="epson")
        assert result is True
        assert await storage.load(sample_event.event_id, tenant="epson") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, storage):
        assert await storage.delete("nothing", tenant="epson") is False

    @pytest.mark.asyncio
    async def test_list_events(self, storage):
        e1 = Event(org_node_id="store-1", tenant="epson")
        e2 = Event(org_node_id="store-2", tenant="epson")
        await storage.save(e1, tenant="epson")
        await storage.save(e2, tenant="epson")

        items = await storage.list_events(tenant="epson")
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_tenant_isolation(self, storage):
        """Events saved for one tenant are NOT visible to another."""
        e_a = Event(org_node_id="store-1", tenant="tenant_a")
        e_b = Event(org_node_id="store-2", tenant="tenant_b")
        await storage.save(e_a, tenant="tenant_a")
        await storage.save(e_b, tenant="tenant_b")

        items_a = await storage.list_events(tenant="tenant_a")
        items_b = await storage.list_events(tenant="tenant_b")

        assert len(items_a) == 1
        assert len(items_b) == 1
        assert items_a[0]["event_id"] == e_a.event_id
        assert items_b[0]["event_id"] == e_b.event_id


# ---------------------------------------------------------------------------
# PostgresEventStorage DDL string test (no real DB)
# ---------------------------------------------------------------------------


class TestPostgresEventStorageDDL:
    def test_create_table_sql_contains_event_id(self):
        """DDL string includes event_id and JSONB column."""
        store = PostgresEventStorage(pool=object())  # pool not used for DDL string
        sql = store._create_table_sql(None)
        assert "event_id" in sql
        assert "JSONB" in sql
        assert "navigator" in sql

    def test_create_table_sql_with_tenant(self):
        """DDL uses tenant as schema when provided."""
        store = PostgresEventStorage(pool=object())
        sql = store._create_table_sql("epson")
        assert '"epson"' in sql

    def test_invalid_schema_raises(self):
        with pytest.raises(ValueError):
            PostgresEventStorage(schema="bad-schema!")

    def test_upsert_sql_contains_on_conflict(self):
        store = PostgresEventStorage(pool=object())
        sql = store._upsert_sql(None)
        assert "ON CONFLICT" in sql
        assert "event_id" in sql
