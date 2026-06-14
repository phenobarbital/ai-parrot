"""Unit tests for TASK-303-2: check-in/out + geofence validation + recap submission.

Tests cover:
- GeofenceValidator haversine (inside / outside / boundary / error)
- VisitService.checkin(): sets timestamp, coord, breadcrumb, shift transition
- VisitService.checkout(): blocked when outside geofence (no submission),
  happy path: submission saved, Visit.submission_id set, draft cleared, states advanced
- Partial-save lifecycle (auto-save on checkin, clear on checkout)
- Already-checked-in idempotency guard
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.visit.errors import (
    GeofenceViolationError,
    VisitAlreadyCheckedInError,
)
from parrot_formdesigner.services.visit.geofence import (
    GeofenceStatus,
    GeofenceValidator,
    _haversine,
)
from parrot_formdesigner.services.visit.models import (
    Event,
    EventStatus,
    GpsCoord,
    Shift,
    ShiftStatus,
)
from parrot_formdesigner.services.visit.storage import InMemoryEventStorage
from parrot_formdesigner.services.visit.visit_service import VisitService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Test geofence centre: NYC Times Square (~40.7580, -73.9855)
# radius 200 m
GEOFENCE_LAT = 40.7580
GEOFENCE_LON = -73.9855
GEOFENCE_RADIUS_M = 200.0


@pytest.fixture
def storage() -> InMemoryEventStorage:
    return InMemoryEventStorage()


@pytest.fixture
def geofence_validator() -> GeofenceValidator:
    return GeofenceValidator(accuracy_buffer_m=0.0)


@pytest.fixture
def mock_submission_storage():
    storage = MagicMock()
    storage.store = AsyncMock(return_value="sub-001")
    return storage


@pytest.fixture
def mock_partial_store():
    store = MagicMock()
    store.save = AsyncMock(return_value=None)
    store.delete = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.get = AsyncMock(return_value=None)
    return reg


@pytest.fixture
def visit_service(
    storage,
    mock_submission_storage,
    mock_partial_store,
    geofence_validator,
    mock_registry,
) -> VisitService:
    return VisitService(
        event_storage=storage,
        submission_storage=mock_submission_storage,
        partial_save_store=mock_partial_store,
        geofence_validator=geofence_validator,
        registry=mock_registry,
        tenant="epson",
    )


@pytest.fixture
def base_event(storage) -> Event:
    """An event with one pending shift and geofence centred on Times Square."""
    shift = Shift(event_id="evt-1", staff_id="staff-1")
    ev = Event(
        event_id="evt-1",
        org_node_id="store-001",
        recap_ids=["recap-form-001"],
        shifts=[shift],
        status=EventStatus.SCHEDULED,
        meta={
            "geofence_lat": GEOFENCE_LAT,
            "geofence_lon": GEOFENCE_LON,
            "geofence_radius_m": GEOFENCE_RADIUS_M,
        },
        tenant="epson",
    )
    # Store synchronously via the sync workaround
    import asyncio

    asyncio.get_event_loop().run_until_complete(storage.save(ev, tenant="epson"))
    return ev


@pytest.fixture
def shift_id(base_event) -> str:
    return base_event.shifts[0].shift_id


@pytest.fixture
def inside_coord() -> GpsCoord:
    """Coord ~10 m from the Times Square geofence centre (inside 200 m radius)."""
    # Move ~10 m north
    return GpsCoord(lat=GEOFENCE_LAT + 0.00009, lon=GEOFENCE_LON)


@pytest.fixture
def outside_coord() -> GpsCoord:
    """Coord ~1 km from the geofence centre (well outside 200 m radius)."""
    return GpsCoord(lat=GEOFENCE_LAT + 0.009, lon=GEOFENCE_LON)


# ---------------------------------------------------------------------------
# Haversine unit tests
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine(0.0, 0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-9)

    def test_known_distance(self):
        # NYC to roughly 1 degree north: ~111 km
        dist = _haversine(40.0, -74.0, 41.0, -74.0)
        assert 110_000 < dist < 112_000


# ---------------------------------------------------------------------------
# GeofenceValidator tests
# ---------------------------------------------------------------------------


class TestGeofenceValidator:
    def test_inside_returns_ok(self, inside_coord):
        validator = GeofenceValidator()
        ev = Event(
            org_node_id="s",
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
        )
        result = validator.validate(inside_coord, ev)
        assert result.status == GeofenceStatus.OK
        assert result.distance_m is not None
        assert result.distance_m < GEOFENCE_RADIUS_M

    def test_outside_returns_outside(self, outside_coord):
        validator = GeofenceValidator()
        ev = Event(
            org_node_id="s",
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
        )
        result = validator.validate(outside_coord, ev)
        assert result.status == GeofenceStatus.OUTSIDE
        assert result.distance_m is not None
        assert result.distance_m > GEOFENCE_RADIUS_M

    def test_missing_meta_returns_error(self, inside_coord):
        validator = GeofenceValidator()
        ev = Event(org_node_id="s", meta=None)
        result = validator.validate(inside_coord, ev)
        assert result.status == GeofenceStatus.ERROR
        assert result.message is not None

    def test_missing_radius_returns_error(self, inside_coord):
        validator = GeofenceValidator()
        ev = Event(
            org_node_id="s",
            meta={"geofence_lat": GEOFENCE_LAT, "geofence_lon": GEOFENCE_LON},
        )
        result = validator.validate(inside_coord, ev)
        assert result.status == GeofenceStatus.ERROR

    def test_accuracy_buffer_widens_fence(self, outside_coord):
        """With a large enough buffer, an outside coord becomes inside."""
        validator = GeofenceValidator(accuracy_buffer_m=2000.0)
        ev = Event(
            org_node_id="s",
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
        )
        result = validator.validate(outside_coord, ev)
        assert result.status == GeofenceStatus.OK

    def test_device_accuracy_widens_fence(self):
        """accuracy_m on GpsCoord widens the effective radius."""
        validator = GeofenceValidator()
        # Coord exactly 300 m from centre (outside 200 m radius)
        # With accuracy_m=200 → effective radius=400 m → inside
        slightly_outside = GpsCoord(
            lat=GEOFENCE_LAT + 0.0027,  # ~300 m north
            lon=GEOFENCE_LON,
            accuracy_m=200.0,
        )
        ev = Event(
            org_node_id="s",
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
        )
        result = validator.validate(slightly_outside, ev)
        assert result.status == GeofenceStatus.OK


# ---------------------------------------------------------------------------
# VisitService.checkin() tests
# ---------------------------------------------------------------------------


class TestCheckin:
    @pytest.mark.asyncio
    async def test_checkin_sets_timestamp(
        self, visit_service, base_event, shift_id, inside_coord, storage
    ):
        """checkin() sets Visit.check_in and records coord."""
        before = datetime.now(timezone.utc)
        visit = await visit_service.checkin(
            base_event.event_id, shift_id, inside_coord
        )
        assert visit.check_in is not None
        assert visit.check_in >= before
        assert visit.check_in_coord == inside_coord

    @pytest.mark.asyncio
    async def test_checkin_starts_breadcrumb(
        self, visit_service, base_event, shift_id, inside_coord, storage
    ):
        visit = await visit_service.checkin(
            base_event.event_id, shift_id, inside_coord
        )
        assert len(visit.gps_breadcrumb) == 1
        assert visit.gps_breadcrumb[0] == inside_coord

    @pytest.mark.asyncio
    async def test_checkin_transitions_shift_to_in_progress(
        self, visit_service, base_event, shift_id, inside_coord, storage
    ):
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        reloaded = await storage.load(base_event.event_id, tenant="epson")
        shift = next(s for s in reloaded.shifts if s.shift_id == shift_id)
        assert shift.status == ShiftStatus.IN_PROGRESS

    @pytest.mark.asyncio
    async def test_checkin_auto_saves_partial(
        self,
        storage,
        mock_submission_storage,
        mock_partial_store,
        geofence_validator,
        mock_registry,
        inside_coord,
    ):
        """checkin() calls PartialSaveStore.save() for the first recap form."""
        shift = Shift(event_id="evt-ps", staff_id="staff-1")
        ev = Event(
            event_id="evt-ps",
            org_node_id="store-001",
            recap_ids=["my-recap"],
            shifts=[shift],
            status=EventStatus.SCHEDULED,
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
            tenant="epson",
        )
        await storage.save(ev, tenant="epson")

        svc = VisitService(
            event_storage=storage,
            submission_storage=mock_submission_storage,
            partial_save_store=mock_partial_store,
            geofence_validator=geofence_validator,
            registry=mock_registry,
            tenant="epson",
        )
        await svc.checkin(ev.event_id, shift.shift_id, inside_coord)
        mock_partial_store.save.assert_called_once()
        call_args = mock_partial_store.save.call_args
        assert call_args[0][0] == "my-recap"  # form_id

    @pytest.mark.asyncio
    async def test_checkin_already_checked_in_raises(
        self, visit_service, base_event, shift_id, inside_coord
    ):
        """Second checkin() on the same shift raises VisitAlreadyCheckedInError."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        with pytest.raises(VisitAlreadyCheckedInError):
            await visit_service.checkin(
                base_event.event_id, shift_id, inside_coord
            )

    @pytest.mark.asyncio
    async def test_checkin_unknown_event_raises(self, visit_service, inside_coord):
        with pytest.raises(ValueError):
            await visit_service.checkin("no-event", "no-shift", inside_coord)

    @pytest.mark.asyncio
    async def test_checkin_unknown_shift_raises(
        self, visit_service, base_event, inside_coord
    ):
        with pytest.raises(ValueError):
            await visit_service.checkin(
                base_event.event_id, "no-such-shift", inside_coord
            )


# ---------------------------------------------------------------------------
# VisitService.checkout() tests
# ---------------------------------------------------------------------------


class TestCheckout:
    @pytest.mark.asyncio
    async def test_checkout_blocked_outside_geofence(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        outside_coord,
        storage,
    ):
        """checkout() raises GeofenceViolationError when gps_outside=True."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        with pytest.raises(GeofenceViolationError):
            await visit_service.checkout(
                base_event.event_id,
                shift_id,
                outside_coord,
                {"answer": "yes"},
            )

    @pytest.mark.asyncio
    async def test_checkout_no_submission_when_outside(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        outside_coord,
        mock_submission_storage,
    ):
        """No submission is persisted when checkout is blocked by geofence."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        with pytest.raises(GeofenceViolationError):
            await visit_service.checkout(
                base_event.event_id,
                shift_id,
                outside_coord,
                {},
            )
        mock_submission_storage.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_checkout_creates_submission(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        mock_submission_storage,
    ):
        """Successful checkout calls FormSubmissionStorage.store() and sets submission_id."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        visit = await visit_service.checkout(
            base_event.event_id,
            shift_id,
            inside_coord,
            {"answer": "42"},
        )
        mock_submission_storage.store.assert_called_once()
        assert visit.submission_id == "sub-001"

    @pytest.mark.asyncio
    async def test_checkout_sets_timestamps(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
    ):
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        before = datetime.now(timezone.utc)
        visit = await visit_service.checkout(
            base_event.event_id,
            shift_id,
            inside_coord,
            {},
        )
        assert visit.check_out is not None
        assert visit.check_out >= before
        assert visit.check_out_coord == inside_coord

    @pytest.mark.asyncio
    async def test_checkout_accumulates_breadcrumb(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
    ):
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        visit = await visit_service.checkout(
            base_event.event_id,
            shift_id,
            inside_coord,
            {},
        )
        assert len(visit.gps_breadcrumb) == 2  # check-in + check-out coords

    @pytest.mark.asyncio
    async def test_checkout_clears_partial_save(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        mock_partial_store,
    ):
        """Successful checkout calls PartialSaveStore.delete()."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        await visit_service.checkout(
            base_event.event_id,
            shift_id,
            inside_coord,
            {},
        )
        mock_partial_store.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_checkout_transitions_shift_to_completed(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        storage,
    ):
        """Shift transitions to COMPLETED after successful checkout."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        await visit_service.checkout(
            base_event.event_id,
            shift_id,
            inside_coord,
            {},
        )
        reloaded = await storage.load(base_event.event_id, tenant="epson")
        shift = next(s for s in reloaded.shifts if s.shift_id == shift_id)
        assert shift.status == ShiftStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_checkout_transitions_event_to_completed_when_all_done(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        storage,
    ):
        """Event transitions to COMPLETED when all shifts are completed."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        await visit_service.checkout(
            base_event.event_id,
            shift_id,
            inside_coord,
            {},
        )
        reloaded = await storage.load(base_event.event_id, tenant="epson")
        assert reloaded.status == EventStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_checkout_without_checkin_raises(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
    ):
        """checkout() without a prior checkin() raises ValueError."""
        with pytest.raises(ValueError):
            await visit_service.checkout(
                base_event.event_id,
                shift_id,
                inside_coord,
                {},
            )

    @pytest.mark.asyncio
    async def test_checkout_gps_outside_flag_saved(
        self,
        visit_service,
        base_event,
        shift_id,
        inside_coord,
        outside_coord,
        storage,
    ):
        """When checkout is blocked, Visit.gps_outside=True is persisted."""
        await visit_service.checkin(base_event.event_id, shift_id, inside_coord)
        with pytest.raises(GeofenceViolationError):
            await visit_service.checkout(
                base_event.event_id,
                shift_id,
                outside_coord,
                {},
            )
        reloaded = await storage.load(base_event.event_id, tenant="epson")
        shift = next(s for s in reloaded.shifts if s.shift_id == shift_id)
        assert shift.visit is not None
        assert shift.visit.gps_outside is True
