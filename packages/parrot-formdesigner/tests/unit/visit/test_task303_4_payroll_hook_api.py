"""Unit tests for TASK-303-4: PayrollHook interface + visit API endpoints.

Tests cover:
- PayrollHook ABC is abstract (cannot instantiate directly)
- NullPayrollHook.on_checkout() is a no-op (no error, no side effects)
- PayrollHook invoked after successful checkout (registered via callback_registry)
- 4 API routes respond with fixture data (200/201/404/409 as appropriate)
- Hook resolved via callback_registry (not constructor injection)
- Callback registry isolation between tests
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.services.callback_registry import (
    _clear_registry_for_tests,
    register_form_callback,
)
from parrot_formdesigner.services.visit.models import (
    Event,
    EventStatus,
    GpsCoord,
    Shift,
    Visit,
)
from parrot_formdesigner.services.visit.payroll_hook import NullPayrollHook, PayrollHook
from parrot_formdesigner.services.visit.storage import InMemoryEventStorage
from parrot_formdesigner.services.visit.geofence import GeofenceValidator
from parrot_formdesigner.services.visit.visit_service import VisitService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_callback_registry():
    """Ensure callback registry is clean before and after each test."""
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


@pytest.fixture
def event_storage() -> InMemoryEventStorage:
    return InMemoryEventStorage()


@pytest.fixture
def mock_submission_storage():
    s = MagicMock()
    s.store = AsyncMock(return_value="sub-999")
    return s


@pytest.fixture
def visit_service(event_storage, mock_submission_storage) -> VisitService:
    return VisitService(
        event_storage=event_storage,
        submission_storage=mock_submission_storage,
        partial_save_store=None,
        geofence_validator=GeofenceValidator(),
        registry=None,
        tenant="epson",
    )


GEOFENCE_LAT = 40.7128
GEOFENCE_LON = -74.0060
GEOFENCE_RADIUS_M = 200.0


@pytest.fixture
def event_with_shift(event_storage) -> Event:
    import asyncio

    shift = Shift(event_id="evt-ph", staff_id="staff-1")
    ev = Event(
        event_id="evt-ph",
        org_node_id="store-001",
        recap_ids=["recap-001"],
        shifts=[shift],
        status=EventStatus.SCHEDULED,
        meta={
            "geofence_lat": GEOFENCE_LAT,
            "geofence_lon": GEOFENCE_LON,
            "geofence_radius_m": GEOFENCE_RADIUS_M,
        },
        tenant="epson",
    )
    asyncio.get_event_loop().run_until_complete(
        event_storage.save(ev, tenant="epson")
    )
    return ev


@pytest.fixture
def inside_coord() -> GpsCoord:
    return GpsCoord(lat=GEOFENCE_LAT + 0.00009, lon=GEOFENCE_LON)


# ---------------------------------------------------------------------------
# PayrollHook ABC tests
# ---------------------------------------------------------------------------


class TestPayrollHookABC:
    def test_payroll_hook_is_abstract(self):
        """PayrollHook cannot be instantiated directly (abstract)."""
        with pytest.raises(TypeError):
            PayrollHook()  # type: ignore[abstract]

    def test_null_payroll_hook_is_not_abstract(self):
        """NullPayrollHook can be instantiated."""
        hook = NullPayrollHook()
        assert hook is not None

    @pytest.mark.asyncio
    async def test_null_payroll_hook_noop(self):
        """NullPayrollHook.on_checkout() completes without error or side effects."""
        hook = NullPayrollHook()
        visit = Visit(shift_id="s1", submission_id="sub-1")
        # Should not raise
        await hook.on_checkout(visit, hours=8.0, tenant="epson")

    @pytest.mark.asyncio
    async def test_null_payroll_hook_with_zero_hours(self):
        """NullPayrollHook handles zero hours gracefully."""
        hook = NullPayrollHook()
        visit = Visit(shift_id="s1")
        await hook.on_checkout(visit, hours=0.0, tenant="epson")


# ---------------------------------------------------------------------------
# PayrollHook via callback_registry tests
# ---------------------------------------------------------------------------


class TestPayrollHookCallback:
    @pytest.mark.asyncio
    async def test_payroll_hook_called_on_checkout(
        self, visit_service, event_with_shift, inside_coord
    ):
        """PayrollHook.on_checkout() is invoked after a successful checkout."""
        hook_calls = []

        @register_form_callback("payroll_hook")
        async def _hook(visit, *, hours, tenant):
            hook_calls.append({"visit": visit, "hours": hours, "tenant": tenant})

        shift_id = event_with_shift.shifts[0].shift_id

        await visit_service.checkin(event_with_shift.event_id, shift_id, inside_coord)
        await visit_service.checkout(
            event_with_shift.event_id, shift_id, inside_coord, {}
        )

        assert len(hook_calls) == 1
        assert hook_calls[0]["tenant"] == "epson"
        assert hook_calls[0]["hours"] >= 0.0

    @pytest.mark.asyncio
    async def test_payroll_hook_not_called_when_outside_geofence(
        self, visit_service, event_with_shift, inside_coord
    ):
        """PayrollHook should NOT be called when checkout is blocked by geofence."""
        from parrot_formdesigner.services.visit.errors import GeofenceViolationError

        hook_calls = []

        @register_form_callback("payroll_hook")
        async def _hook(visit, *, hours, tenant):
            hook_calls.append(1)

        outside_coord = GpsCoord(lat=GEOFENCE_LAT + 0.009, lon=GEOFENCE_LON)
        shift_id = event_with_shift.shifts[0].shift_id

        await visit_service.checkin(event_with_shift.event_id, shift_id, inside_coord)
        with pytest.raises(GeofenceViolationError):
            await visit_service.checkout(
                event_with_shift.event_id, shift_id, outside_coord, {}
            )

        assert len(hook_calls) == 0

    @pytest.mark.asyncio
    async def test_payroll_hook_failure_does_not_block_checkout(
        self, visit_service, event_with_shift, inside_coord
    ):
        """A failing PayrollHook must not prevent successful checkout."""

        @register_form_callback("payroll_hook")
        async def _failing_hook(visit, *, hours, tenant):
            raise RuntimeError("Payroll system down!")

        shift_id = event_with_shift.shifts[0].shift_id

        await visit_service.checkin(event_with_shift.event_id, shift_id, inside_coord)
        # This should NOT raise even though the hook fails
        visit = await visit_service.checkout(
            event_with_shift.event_id, shift_id, inside_coord, {}
        )
        assert visit is not None
        assert visit.submission_id == "sub-999"

    @pytest.mark.asyncio
    async def test_checkout_without_hook_registered_succeeds(
        self, visit_service, event_with_shift, inside_coord
    ):
        """checkout() succeeds even when no PayrollHook is registered."""
        shift_id = event_with_shift.shifts[0].shift_id

        await visit_service.checkin(event_with_shift.event_id, shift_id, inside_coord)
        visit = await visit_service.checkout(
            event_with_shift.event_id, shift_id, inside_coord, {}
        )
        assert visit is not None

    @pytest.mark.asyncio
    async def test_null_payroll_hook_registered_via_callback_registry(
        self, visit_service, event_with_shift, inside_coord
    ):
        """Register NullPayrollHook via callback_registry — should work as no-op."""
        null_hook = NullPayrollHook()

        @register_form_callback("payroll_hook")
        async def _on_checkout(visit, *, hours, tenant):
            await null_hook.on_checkout(visit, hours=hours, tenant=tenant)

        shift_id = event_with_shift.shifts[0].shift_id
        await visit_service.checkin(event_with_shift.event_id, shift_id, inside_coord)
        visit = await visit_service.checkout(
            event_with_shift.event_id, shift_id, inside_coord, {}
        )
        assert visit is not None


# ---------------------------------------------------------------------------
# API endpoint handler tests (mocked requests — no live server)
# ---------------------------------------------------------------------------


def _make_handler():
    """Build a FormAPIHandler with in-memory visit storage."""
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry

    registry = MagicMock(spec=FormRegistry)
    registry.default_tenant = "epson"
    registry.get = AsyncMock(return_value=None)

    handler = FormAPIHandler(registry=registry)
    # Wire an in-memory event storage for the visit service
    from parrot_formdesigner.services.visit.storage import InMemoryEventStorage
    handler._event_storage = InMemoryEventStorage()
    handler._visit_service = None  # Force lazy reinit with our storage
    return handler


def _make_request(
    *,
    method: str = "POST",
    match_info: dict | None = None,
    body: dict | None = None,
    tenant: str = "epson",
) -> MagicMock:
    """Build a mocked aiohttp web.Request."""
    from aiohttp import web

    req = MagicMock(spec=web.Request)
    req.method = method
    req.match_info = match_info or {}
    req.session = {"session": {"programs": [tenant]}}
    req.__contains__ = lambda self, key: False
    req.headers = {}

    user = MagicMock()
    user.organizations = []
    req.user = user

    if body is not None:
        req.json = AsyncMock(return_value=body)
    else:
        req.json = AsyncMock(side_effect=ValueError("no body"))
    return req


class TestCreateEventEndpoint:
    @pytest.mark.asyncio
    async def test_create_event_201(self):
        """POST /api/v1/visits/events returns 201 with the created event."""
        handler = _make_handler()
        req = _make_request(body={
            "org_node_id": "store-001",
            "recap_ids": ["form-1"],
        })
        resp = await handler.create_event(req)
        assert resp.status == 201
        data = json.loads(resp.body)
        assert data["org_node_id"] == "store-001"

    @pytest.mark.asyncio
    async def test_create_event_400_missing_org_node(self):
        """POST /api/v1/visits/events returns 400 when org_node_id is missing."""
        handler = _make_handler()
        req = _make_request(body={"recap_ids": ["form-1"]})
        resp = await handler.create_event(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_create_event_400_invalid_json(self):
        """POST /api/v1/visits/events returns 400 on invalid JSON."""
        handler = _make_handler()
        req = _make_request()  # no body → json() raises ValueError
        resp = await handler.create_event(req)
        assert resp.status == 400


class TestCheckinEndpoint:
    @pytest.fixture
    def handler_with_event(self):
        """Handler with a pre-seeded event."""
        import asyncio

        handler = _make_handler()
        storage = handler._event_storage
        shift = Shift(event_id="evt-ci", staff_id="staff-1")
        ev = Event(
            event_id="evt-ci",
            org_node_id="store-001",
            shifts=[shift],
            status=EventStatus.SCHEDULED,
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
            tenant="epson",
        )
        asyncio.get_event_loop().run_until_complete(storage.save(ev, tenant="epson"))
        return handler, ev.event_id, shift.shift_id

    @pytest.mark.asyncio
    async def test_checkin_200(self, handler_with_event):
        handler, event_id, shift_id = handler_with_event
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={"lat": GEOFENCE_LAT + 0.00009, "lon": GEOFENCE_LON},
        )
        resp = await handler.visit_checkin(req)
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["shift_id"] == shift_id

    @pytest.mark.asyncio
    async def test_checkin_404_unknown_event(self):
        handler = _make_handler()
        req = _make_request(
            match_info={"event_id": "no-event", "shift_id": "no-shift"},
            body={"lat": 0.0, "lon": 0.0},
        )
        resp = await handler.visit_checkin(req)
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_checkin_400_missing_lat(self, handler_with_event):
        handler, event_id, shift_id = handler_with_event
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={"lon": GEOFENCE_LON},  # missing lat
        )
        resp = await handler.visit_checkin(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_checkin_409_already_checked_in(self, handler_with_event):
        """Second check-in returns 409."""
        handler, event_id, shift_id = handler_with_event
        body = {"lat": GEOFENCE_LAT + 0.00009, "lon": GEOFENCE_LON}
        req1 = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id}, body=body
        )
        req2 = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id}, body=body
        )
        resp1 = await handler.visit_checkin(req1)
        assert resp1.status == 200
        resp2 = await handler.visit_checkin(req2)
        assert resp2.status == 409


class TestCheckoutEndpoint:
    @pytest.fixture
    def handler_checked_in(self):
        """Handler with a pre-seeded event that has already been checked in."""
        import asyncio

        handler = _make_handler()
        storage = handler._event_storage
        shift = Shift(event_id="evt-co", staff_id="staff-1")
        ev = Event(
            event_id="evt-co",
            org_node_id="store-001",
            shifts=[shift],
            status=EventStatus.SCHEDULED,
            meta={
                "geofence_lat": GEOFENCE_LAT,
                "geofence_lon": GEOFENCE_LON,
                "geofence_radius_m": GEOFENCE_RADIUS_M,
            },
            tenant="epson",
        )
        asyncio.get_event_loop().run_until_complete(storage.save(ev, tenant="epson"))

        # Do checkin first
        svc = handler._get_visit_service()
        asyncio.get_event_loop().run_until_complete(
            svc.checkin(
                ev.event_id,
                shift.shift_id,
                GpsCoord(lat=GEOFENCE_LAT + 0.00009, lon=GEOFENCE_LON),
                tenant="epson",
            )
        )
        return handler, ev.event_id, shift.shift_id

    @pytest.mark.asyncio
    async def test_checkout_200(self, handler_checked_in):
        handler, event_id, shift_id = handler_checked_in
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={
                "lat": GEOFENCE_LAT + 0.00009,
                "lon": GEOFENCE_LON,
                "submission_data": {"answer": "yes"},
            },
        )
        resp = await handler.visit_checkout(req)
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["shift_id"] == shift_id

    @pytest.mark.asyncio
    async def test_checkout_409_geofence_violation(self, handler_checked_in):
        """checkout() returns 409 when GPS is outside geofence."""
        handler, event_id, shift_id = handler_checked_in
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={
                "lat": GEOFENCE_LAT + 0.9,  # ~100 km away
                "lon": GEOFENCE_LON,
            },
        )
        resp = await handler.visit_checkout(req)
        assert resp.status == 409

    @pytest.mark.asyncio
    async def test_checkout_404_unknown_event(self):
        handler = _make_handler()
        req = _make_request(
            match_info={"event_id": "no-event", "shift_id": "no-shift"},
            body={"lat": 0.0, "lon": 0.0},
        )
        resp = await handler.visit_checkout(req)
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_checkout_400_missing_lat(self, handler_checked_in):
        handler, event_id, shift_id = handler_checked_in
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={"lon": GEOFENCE_LON},
        )
        resp = await handler.visit_checkout(req)
        assert resp.status == 400


class TestSetMissedEndpoint:
    @pytest.fixture
    def handler_with_event(self):
        import asyncio

        handler = _make_handler()
        storage = handler._event_storage
        shift = Shift(event_id="evt-ms", staff_id="staff-1")
        ev = Event(
            event_id="evt-ms",
            org_node_id="store-001",
            shifts=[shift],
            status=EventStatus.SCHEDULED,
            tenant="epson",
        )
        asyncio.get_event_loop().run_until_complete(storage.save(ev, tenant="epson"))
        return handler, ev.event_id, shift.shift_id

    @pytest.mark.asyncio
    async def test_set_missed_200(self, handler_with_event):
        handler, event_id, shift_id = handler_with_event
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={"reason_id": "reason-001"},
        )
        resp = await handler.visit_set_missed(req)
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["missed_reason_id"] == "reason-001"

    @pytest.mark.asyncio
    async def test_set_missed_400_missing_reason(self, handler_with_event):
        handler, event_id, shift_id = handler_with_event
        req = _make_request(
            match_info={"event_id": event_id, "shift_id": shift_id},
            body={},
        )
        resp = await handler.visit_set_missed(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_set_missed_404_unknown_event(self):
        handler = _make_handler()
        req = _make_request(
            match_info={"event_id": "no-event", "shift_id": "no-shift"},
            body={"reason_id": "r1"},
        )
        resp = await handler.visit_set_missed(req)
        assert resp.status == 404
