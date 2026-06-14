"""Regression tests for the FEAT-303 code-review fixes (#1-#6)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.services.visit.shift_service import _overlaps
from parrot_formdesigner.services.visit.errors import (
    GeofenceConfigError,
)


# #1 — tz-aware sentinels: half-None bound with tz-aware datetimes must not crash
class TestOverlapTzAware:
    def test_open_ended_shift_vs_tz_aware_no_crash(self):
        t = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc)
        # A is open-ended (no end); B is bounded tz-aware — must not raise.
        assert _overlaps(t, None, t, datetime(2026, 6, 14, 17, 0, tzinfo=timezone.utc)) is True

    def test_no_false_overlap_disjoint(self):
        d = timezone.utc
        a0 = datetime(2026, 6, 14, 9, 0, tzinfo=d)
        a1 = datetime(2026, 6, 14, 12, 0, tzinfo=d)
        b0 = datetime(2026, 6, 14, 13, 0, tzinfo=d)
        b1 = datetime(2026, 6, 14, 17, 0, tzinfo=d)
        assert _overlaps(a0, a1, b0, b1) is False

    # #7 — adjacent shifts (A.end == B.start) are NOT an overlap
    def test_adjacent_shifts_not_overlap(self):
        d = timezone.utc
        a0 = datetime(2026, 6, 14, 9, 0, tzinfo=d)
        a1 = datetime(2026, 6, 14, 12, 0, tzinfo=d)
        b0 = datetime(2026, 6, 14, 12, 0, tzinfo=d)
        b1 = datetime(2026, 6, 14, 15, 0, tzinfo=d)
        assert _overlaps(a0, a1, b0, b1) is False

    def test_true_overlap_detected(self):
        d = timezone.utc
        a0 = datetime(2026, 6, 14, 9, 0, tzinfo=d)
        a1 = datetime(2026, 6, 14, 13, 0, tzinfo=d)
        b0 = datetime(2026, 6, 14, 12, 0, tzinfo=d)
        b1 = datetime(2026, 6, 14, 15, 0, tzinfo=d)
        assert _overlaps(a0, a1, b0, b1) is True


# #2/#8 — checkout with a missing/invalid geofence config must hard-block (raise)
class TestGeofenceErrorBlocks:
    async def test_checkout_raises_on_missing_geofence(self, monkeypatch):
        from parrot_formdesigner.services.visit.geofence import GeofenceResult, GeofenceStatus

        # Build a minimal VisitService with in-memory storage + a checked-in shift.
        from parrot_formdesigner.services.visit.models import (
            Event, Shift, Visit, GpsCoord, EventStatus, ShiftStatus,
        )
        from parrot_formdesigner.services.visit.storage import InMemoryEventStorage
        from parrot_formdesigner.services.visit.geofence import GeofenceValidator
        from parrot_formdesigner.services.visit.visit_service import VisitService

        coord = GpsCoord(lat=1.0, lon=1.0, recorded_at=datetime.now(timezone.utc))
        visit = Visit(visit_id="v1", shift_id="s1", check_in=datetime.now(timezone.utc),
                      check_in_coord=coord, gps_breadcrumb=[coord])
        shift = Shift(shift_id="s1", event_id="e1", staff_id="u1",
                      status=ShiftStatus.IN_PROGRESS, visit=visit)
        event = Event(event_id="e1", status=EventStatus.IN_PROGRESS, org_node_id="o1",
                      recap_ids=[], shifts=[shift], tenant="t1", meta={})  # no geofence keys
        storage = InMemoryEventStorage()
        await storage.save(event, tenant="t1")
        svc = VisitService(
            event_storage=storage,
            submission_storage=None,
            partial_save_store=None,
            geofence_validator=GeofenceValidator(),
            registry=None,
            tenant="t1",
        )

        # Force the validator to report ERROR (malformed/missing config).
        monkeypatch.setattr(
            svc._geofence_validator, "validate",
            lambda c, e: GeofenceResult(status=GeofenceStatus.ERROR, distance_m=None),
        )
        with pytest.raises(GeofenceConfigError):
            await svc.checkout("e1", "s1", coord, {}, tenant="t1")
