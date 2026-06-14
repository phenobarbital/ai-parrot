"""ShiftService — staff assignment with no-overlap enforcement (FEAT-303).

Decision (spec §8): ``ShiftService.assign_staff()`` REJECTS a shift whose
time window overlaps an existing active shift of the same rep across any
event.  Raises ``OverlappingShiftError`` to prevent double-counting hours.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .errors import OverlappingShiftError
from .models import Event, Shift, ShiftStatus
from .storage import EventStorage


_EPOCH_MIN = datetime(1, 1, 1, tzinfo=timezone.utc)
_EPOCH_MAX = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def _overlaps(
    start_a: datetime | None,
    end_a: datetime | None,
    start_b: datetime | None,
    end_b: datetime | None,
) -> bool:
    """Return ``True`` if two half-open time intervals overlap.

    ``None`` start/end means the interval is unbounded on that side.
    Two unbounded intervals always overlap.

    Args:
        start_a: Start of interval A.
        end_a: End of interval A.
        start_b: Start of interval B.
        end_b: End of interval B.

    Returns:
        ``True`` if the intervals share at least one point in time.
    """
    # If either side has no time bounds, treat as overlapping (conservative)
    if start_a is None and end_a is None:
        return True
    if start_b is None and end_b is None:
        return True

    # Standard overlap check: A starts before B ends AND B starts before A ends
    # tz-aware sentinels — shift datetimes are tz-aware UTC; tz-naive
    # datetime.min/max would raise TypeError on mixed comparison (review #1).
    a_start = start_a if start_a is not None else _EPOCH_MIN
    a_end = end_a if end_a is not None else _EPOCH_MAX
    b_start = start_b if start_b is not None else _EPOCH_MIN
    b_end = end_b if end_b is not None else _EPOCH_MAX

    return a_start < b_end and b_start < a_end


class ShiftService:
    """Service for managing staff assignments (Shifts) within Events.

    Args:
        storage: Persistence backend for events.
        tenant: Default tenant slug for all operations.
    """

    def __init__(self, storage: EventStorage, *, tenant: str) -> None:
        self._storage = storage
        self._tenant = tenant
        self.logger = logging.getLogger(__name__)

    async def assign_staff(
        self,
        event_id: str,
        staff_id: str,
        *,
        scheduled_start: datetime | None = None,
        scheduled_end: datetime | None = None,
    ) -> Shift:
        """Assign a staff member to an event as a new Shift.

        Enforces the no-overlap rule: rejects the assignment when the
        new shift's time window overlaps an existing active shift of the
        same rep across *any* event visible to this tenant.

        Args:
            event_id: The event to assign the staff member to.
            staff_id: The staff member's user ID.
            scheduled_start: Optional planned start time (UTC).
            scheduled_end: Optional planned end time (UTC).

        Returns:
            The newly created and persisted ``Shift``.

        Raises:
            ValueError: If the event is not found.
            OverlappingShiftError: If the staff member already has an
                overlapping active shift in another event.
        """
        # Load the target event
        event = await self._storage.load(event_id, tenant=self._tenant)
        if event is None:
            raise ValueError(
                f"Event {event_id!r} not found (tenant={self._tenant!r})"
            )

        # Scan all events for overlapping active shifts by the same staff
        all_event_dicts = await self._storage.list_events(tenant=self._tenant)
        for ev_dict in all_event_dicts:
            ev = Event.model_validate(ev_dict)
            for existing_shift in ev.shifts:
                if existing_shift.staff_id != staff_id:
                    continue
                if existing_shift.status in (ShiftStatus.COMPLETED, ShiftStatus.MISSED):
                    continue  # Only check active/pending shifts
                if _overlaps(
                    scheduled_start,
                    scheduled_end,
                    existing_shift.scheduled_start,
                    existing_shift.scheduled_end,
                ):
                    raise OverlappingShiftError(
                        staff_id=staff_id,
                        existing_shift_id=existing_shift.shift_id,
                    )

        # Build and attach the new Shift
        new_shift = Shift(
            shift_id=str(uuid.uuid4()),
            event_id=event_id,
            staff_id=staff_id,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
        )

        updated_shifts = list(event.shifts) + [new_shift]
        updated_event = event.model_copy(update={"shifts": updated_shifts})
        await self._storage.save(updated_event, tenant=self._tenant)

        self.logger.info(
            "Assigned staff %r to event %s (shift %s)",
            staff_id,
            event_id,
            new_shift.shift_id,
        )
        return new_shift
