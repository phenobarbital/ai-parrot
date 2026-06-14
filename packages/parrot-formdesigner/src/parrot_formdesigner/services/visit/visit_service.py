"""VisitService — check-in/out, geofence, missed reasons, ad-hoc stops (FEAT-303).

Orchestrates the ``Shift → Visit`` lifecycle:

- ``checkin``: creates/activates the Visit, records GPS, starts partial save.
- ``checkout``: validates geofence, persists recap, fires PayrollHook.
- ``set_missed_reason``: assigns a Missed Reason, transitions Shift/Event.
- ``create_adhoc``: creates a full Event+Shift+Visit for guerrilla stops.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .errors import (
    GeofenceConfigError,
    GeofenceViolationError,
    InvalidTransitionError,
    VisitAlreadyCheckedInError,
)
from .models import (
    Event,
    EventStatus,
    GpsCoord,
    Shift,
    ShiftStatus,
    Visit,
    SHIFT_TRANSITIONS,
    EVENT_TRANSITIONS,
)
from .geofence import GeofenceStatus, GeofenceValidator
from .storage import EventStorage

if TYPE_CHECKING:
    from ..partial_saves import PartialSaveStore
    from ..submissions import FormSubmissionStorage
    from ..registry import FormRegistry


class VisitService:
    """Service orchestrating the Visit lifecycle within Events.

    Args:
        event_storage: Persistence backend for events.
        submission_storage: Backend for persisting FormSubmission records.
        partial_save_store: Redis-backed store for in-progress recap drafts.
        geofence_validator: Validator for GPS geofence checks.
        registry: FormRegistry for loading recap FormSchema objects.
        tenant: Default tenant slug for all operations.
    """

    def __init__(
        self,
        event_storage: EventStorage,
        submission_storage: "FormSubmissionStorage | None",
        partial_save_store: "PartialSaveStore | None",
        geofence_validator: GeofenceValidator,
        registry: "FormRegistry | None",
        *,
        tenant: str,
    ) -> None:
        self._event_storage = event_storage
        self._submission_storage = submission_storage
        self._partial_save_store = partial_save_store
        self._geofence_validator = geofence_validator
        self._registry = registry
        self._tenant = tenant
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_event(self, event_id: str) -> Event:
        event = await self._event_storage.load(event_id, tenant=self._tenant)
        if event is None:
            raise ValueError(
                f"Event {event_id!r} not found (tenant={self._tenant!r})"
            )
        return event

    def _find_shift(self, event: Event, shift_id: str) -> Shift:
        for shift in event.shifts:
            if shift.shift_id == shift_id:
                return shift
        raise ValueError(
            f"Shift {shift_id!r} not found in event {event.event_id!r}"
        )

    def _replace_shift(self, event: Event, updated_shift: Shift) -> Event:
        """Return a new Event with the matching shift replaced."""
        new_shifts = [
            updated_shift if s.shift_id == updated_shift.shift_id else s
            for s in event.shifts
        ]
        return event.model_copy(update={"shifts": new_shifts})

    def _transition_shift(self, shift: Shift, new_status: ShiftStatus) -> Shift:
        allowed = SHIFT_TRANSITIONS.get(shift.status, set())
        if new_status not in allowed:
                raise InvalidTransitionError(
                from_status=shift.status.value,
                to_status=new_status.value,
                entity="Shift",
            )
        return shift.model_copy(update={"status": new_status})

    def _transition_event_if_needed(self, event: Event) -> Event:
        """Transition Event status based on its shifts' statuses."""
        if not event.shifts:
            return event

        statuses = {s.status for s in event.shifts}

        # All shifts completed → Event completed
        if statuses == {ShiftStatus.COMPLETED}:
            allowed = EVENT_TRANSITIONS.get(event.status, set())
            if EventStatus.COMPLETED in allowed:
                return event.model_copy(update={"status": EventStatus.COMPLETED})

        # All shifts missed → Event missed
        if statuses == {ShiftStatus.MISSED}:
            allowed = EVENT_TRANSITIONS.get(event.status, set())
            if EventStatus.MISSED in allowed:
                return event.model_copy(update={"status": EventStatus.MISSED})

        # At least one in-progress → Event in_progress (if not already)
        if ShiftStatus.IN_PROGRESS in statuses:
            if event.status == EventStatus.SCHEDULED:
                allowed = EVENT_TRANSITIONS.get(event.status, set())
                if EventStatus.IN_PROGRESS in allowed:
                    return event.model_copy(
                        update={"status": EventStatus.IN_PROGRESS}
                    )

        return event

    # ------------------------------------------------------------------
    # Check-in
    # ------------------------------------------------------------------

    async def checkin(
        self,
        event_id: str,
        shift_id: str,
        coord: GpsCoord,
        *,
        tenant: str | None = None,
    ) -> Visit:
        """Record a check-in for a shift.

        Creates a new ``Visit`` on the Shift (or re-uses an existing one if
        check-in has not been recorded yet). Sets ``check_in``,
        ``check_in_coord``, transitions Shift → ``IN_PROGRESS``, and
        auto-saves a partial recap stub.

        Args:
            event_id: The event containing the shift.
            shift_id: The shift being checked in.
            coord: GPS coordinate at check-in time.
            tenant: Optional per-call tenant override.

        Returns:
            The updated ``Visit`` after check-in.

        Raises:
            ValueError: If the event or shift is not found.
            VisitAlreadyCheckedInError: If the visit is already checked in.
        """
        effective_tenant = tenant or self._tenant
        event = await self._load_event(event_id)
        shift = self._find_shift(event, shift_id)

        # State-machine guard: only SCHEDULED/IN_PROGRESS events accept a
        # check-in (no REQUESTED → IN_PROGRESS edge — review #6).
        if event.status not in (EventStatus.SCHEDULED, EventStatus.IN_PROGRESS):
            raise InvalidTransitionError(
                from_status=event.status.value,
                to_status=ShiftStatus.IN_PROGRESS.value,
                entity="Event",
            )

        # Idempotency guard
        if shift.visit is not None and shift.visit.check_in is not None:
            raise VisitAlreadyCheckedInError(shift.visit.visit_id)

        now = datetime.now(timezone.utc)
        visit_id = (
            shift.visit.visit_id
            if shift.visit is not None
            else str(uuid.uuid4())
        )
        visit = Visit(
            visit_id=visit_id,
            shift_id=shift_id,
            check_in=now,
            check_in_coord=coord,
            gps_breadcrumb=[coord],
            tenant=effective_tenant,
        )

        # Transition shift to IN_PROGRESS (allow PENDING → IN_PROGRESS)
        if shift.status == ShiftStatus.PENDING:
            shift = self._transition_shift(shift, ShiftStatus.IN_PROGRESS)
        updated_shift = shift.model_copy(update={"visit": visit})
        event = self._replace_shift(event, updated_shift)
        event = self._transition_event_if_needed(event)
        await self._event_storage.save(event, tenant=effective_tenant)

        # Auto-save partial recap stub (best-effort; don't fail check-in if unavailable)
        if self._partial_save_store is not None and event.recap_ids:
            form_id = event.recap_ids[0]
            try:
                await self._partial_save_store.save(form_id, visit_id, {})
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "PartialSaveStore.save failed at checkin (non-fatal): %s", exc
                )

        self.logger.info(
            "Check-in: visit %s, shift %s, event %s",
            visit_id, shift_id, event_id,
        )
        return visit

    # ------------------------------------------------------------------
    # Check-out
    # ------------------------------------------------------------------

    async def checkout(
        self,
        event_id: str,
        shift_id: str,
        coord: GpsCoord,
        submission_data: dict[str, Any],
        *,
        tenant: str | None = None,
    ) -> Visit:
        """Record a check-out, validate geofence, and persist the recap.

        Flow:
        1. Append coord to breadcrumb, run geofence check.
        2. If outside → set ``gps_outside=True``, save Visit, raise
           ``GeofenceViolationError`` (no submission persisted).
        3. If inside → persist ``FormSubmission``, set ``submission_id``,
           clear partial draft, transition Shift → COMPLETED.

        Args:
            event_id: The event containing the shift.
            shift_id: The shift being checked out.
            coord: GPS coordinate at check-out time.
            submission_data: Recap form answers.
            tenant: Optional per-call tenant override.

        Returns:
            The updated ``Visit`` after successful check-out.

        Raises:
            ValueError: If the event, shift, or visit is not found.
            GeofenceViolationError: If the coord is outside the geofence.
        """
        effective_tenant = tenant or self._tenant
        event = await self._load_event(event_id)
        shift = self._find_shift(event, shift_id)

        if shift.visit is None:
            raise ValueError(
                f"Shift {shift_id!r} has no active Visit. Call checkin() first."
            )

        visit = shift.visit
        now = datetime.now(timezone.utc)
        new_breadcrumb = list(visit.gps_breadcrumb) + [coord]

        # Geofence validation. A malformed/missing geofence config yields
        # ERROR — treat that as a hard block, never a silent pass (review #2).
        geo_result = self._geofence_validator.validate(coord, event)
        if geo_result.status == GeofenceStatus.ERROR:
            raise GeofenceConfigError(event_id)
        gps_outside = geo_result.status == GeofenceStatus.OUTSIDE

        # Update visit with checkout coordinate
        visit = visit.model_copy(
            update={
                "check_out": now,
                "check_out_coord": coord,
                "gps_breadcrumb": new_breadcrumb,
                "gps_outside": gps_outside,
            }
        )

        if gps_outside:
            # Save the updated Visit (with gps_outside=True) then block
            updated_shift = shift.model_copy(update={"visit": visit})
            event = self._replace_shift(event, updated_shift)
            await self._event_storage.save(event, tenant=effective_tenant)
            raise GeofenceViolationError(
                distance_m=geo_result.distance_m or 0.0,
                radius_m=float((event.meta or {}).get("geofence_radius_m", 0)),
            )

        # Persist recap submission
        submission_id: str | None = None
        if self._submission_storage is not None and event.recap_ids:
            from ..submissions import FormSubmission

            form_id = event.recap_ids[0]
            form_version = "1.0"
            if self._registry is not None:
                form_schema = await self._registry.get(
                    form_id, tenant=effective_tenant
                )
                if form_schema is not None:
                    form_version = form_schema.version

            submission = FormSubmission(
                form_id=form_id,
                form_version=form_version,
                data=submission_data,
                is_valid=True,
                tenant=effective_tenant,
            )
            submission_id = await self._submission_storage.store(
                submission, tenant=effective_tenant
            )
        elif self._submission_storage is None:
            self.logger.warning(
                "checkout: no submission_storage configured — recap not persisted"
            )

        # Clear partial draft
        if self._partial_save_store is not None and event.recap_ids:
            form_id = event.recap_ids[0]
            try:
                await self._partial_save_store.delete(form_id, visit.visit_id)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "PartialSaveStore.delete failed at checkout (non-fatal): %s", exc
                )

        visit = visit.model_copy(update={"submission_id": submission_id})
        shift = self._transition_shift(shift, ShiftStatus.COMPLETED)
        updated_shift = shift.model_copy(update={"visit": visit})
        event = self._replace_shift(event, updated_shift)
        event = self._transition_event_if_needed(event)
        await self._event_storage.save(event, tenant=effective_tenant)

        # Fire PayrollHook (best-effort; never block checkout)
        await self._fire_payroll_hook(visit, effective_tenant)

        self.logger.info(
            "Check-out: visit %s, shift %s, event %s (submission=%s)",
            visit.visit_id, shift_id, event_id, submission_id,
        )
        return visit

    async def _fire_payroll_hook(self, visit: Visit, tenant: str) -> None:
        """Fire the registered PayrollHook (best-effort, never propagates errors)."""
        # Tenant-specific hook wins over global — get_form_callback already
        # implements that priority (review #4).
        from ..callback_registry import get_form_callback

        try:
            hook_fn = get_form_callback("payroll_hook", tenant=tenant)
        except KeyError:
            return
        if hook_fn is None:
            return

        # Calculate GPS-validated hours (check_in → check_out delta)
        hours = 0.0
        if visit.check_in is not None and visit.check_out is not None:
            delta = visit.check_out - visit.check_in
            hours = delta.total_seconds() / 3600.0

        try:
            await hook_fn(visit, hours=hours, tenant=tenant)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "PayrollHook.on_checkout failed (non-fatal): %s", exc
            )

    # ------------------------------------------------------------------
    # Set missed reason (implemented fully in TASK-303-3; stub here)
    # ------------------------------------------------------------------

    async def set_missed_reason(
        self,
        event_id: str,
        shift_id: str,
        reason_id: str,
        *,
        tenant: str | None = None,
    ) -> Visit:
        """Assign a Missed Reason to a Visit and transition Shift/Event.

        Transitions the Shift → ``MISSED`` and, when ALL shifts are missed,
        transitions the Event → ``MISSED``.

        Args:
            event_id: The event containing the shift.
            shift_id: The shift being marked missed.
            reason_id: The ``MissedReason.reason_id`` to assign.
            tenant: Optional per-call tenant override.

        Returns:
            The updated ``Visit`` with ``missed_reason_id`` set.

        Raises:
            ValueError: If the event or shift is not found.
        """
        effective_tenant = tenant or self._tenant
        event = await self._load_event(event_id)
        shift = self._find_shift(event, shift_id)

        # Ensure a Visit exists (create one if needed for missed tracking)
        if shift.visit is None:
            visit = Visit(
                visit_id=str(uuid.uuid4()),
                shift_id=shift_id,
                missed_reason_id=reason_id,
                tenant=effective_tenant,
            )
        else:
            visit = shift.visit.model_copy(update={"missed_reason_id": reason_id})

        # Transition shift to MISSED (PENDING or IN_PROGRESS → MISSED)
        if shift.status in (ShiftStatus.PENDING, ShiftStatus.IN_PROGRESS):
            shift = self._transition_shift(shift, ShiftStatus.MISSED)

        updated_shift = shift.model_copy(update={"visit": visit})
        event = self._replace_shift(event, updated_shift)
        event = self._transition_event_if_needed(event)
        await self._event_storage.save(event, tenant=effective_tenant)

        self.logger.info(
            "Missed reason %r assigned to visit %s (shift %s, event %s)",
            reason_id, visit.visit_id, shift_id, event_id,
        )
        return visit

    # ------------------------------------------------------------------
    # Ad-hoc / guerrilla stop
    # ------------------------------------------------------------------

    async def create_adhoc(
        self,
        org_node_id: str,
        staff_id: str,
        *,
        tenant: str | None = None,
    ) -> Event:
        """Create an ad-hoc Event + Shift + Visit in a single operation.

        Sets ``Event.is_adhoc=True`` and immediately starts the Visit
        (sets ``check_in`` to now).

        Args:
            org_node_id: FK to the store/program node.
            staff_id: The staff member creating the ad-hoc stop.
            tenant: Optional per-call tenant override.

        Returns:
            The newly created ``Event`` with one ``Shift`` and one active
            ``Visit``.
        """
        effective_tenant = tenant or self._tenant
        now = datetime.now(timezone.utc)

        shift_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())

        visit = Visit(
            visit_id=str(uuid.uuid4()),
            shift_id=shift_id,
            check_in=now,
            tenant=effective_tenant,
        )
        shift = Shift(
            shift_id=shift_id,
            event_id=event_id,
            staff_id=staff_id,
            status=ShiftStatus.IN_PROGRESS,
            visit=visit,
        )
        event = Event(
            event_id=event_id,
            org_node_id=org_node_id,
            is_adhoc=True,
            status=EventStatus.IN_PROGRESS,
            shifts=[shift],
            tenant=effective_tenant,
        )

        await self._event_storage.save(event, tenant=effective_tenant)
        self.logger.info(
            "Created adhoc event %s for staff %r (tenant=%r)",
            event_id, staff_id, effective_tenant,
        )
        return event
