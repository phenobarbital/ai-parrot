"""Typed error classes for the visit lifecycle (FEAT-303).

All errors are ``ValueError`` subclasses so they are naturally raised as
4xx-type failures by the API layer.
"""

from __future__ import annotations


class InvalidTransitionError(ValueError):
    """Raised when an illegal state-machine transition is attempted.

    Args:
        from_status: The current status before the attempted transition.
        to_status: The target status that was rejected.
        entity: Optional entity name (e.g. ``"Event"`` or ``"Shift"``).
    """

    def __init__(
        self,
        from_status: str,
        to_status: str,
        entity: str = "entity",
    ) -> None:
        super().__init__(
            f"Invalid {entity} transition: {from_status!r} → {to_status!r}"
        )
        self.from_status = from_status
        self.to_status = to_status
        self.entity = entity


class OverlappingShiftError(ValueError):
    """Raised when assigning a staff member to a shift that overlaps an existing one.

    Args:
        staff_id: The staff member whose shift would overlap.
        existing_shift_id: The ID of the existing conflicting shift.
    """

    def __init__(self, staff_id: str, existing_shift_id: str) -> None:
        super().__init__(
            f"Staff {staff_id!r} already has an overlapping active shift "
            f"{existing_shift_id!r}. Assign non-overlapping time windows."
        )
        self.staff_id = staff_id
        self.existing_shift_id = existing_shift_id


class GeofenceViolationError(ValueError):
    """Raised when checkout is attempted from outside the event geofence.

    Args:
        distance_m: The measured distance from the geofence centre in metres.
        radius_m: The configured geofence radius in metres.
    """

    def __init__(self, distance_m: float, radius_m: float) -> None:
        super().__init__(
            f"GPS position is {distance_m:.1f} m from event centre "
            f"(radius: {radius_m:.1f} m). Checkout blocked."
        )
        self.distance_m = distance_m
        self.radius_m = radius_m


class VisitAlreadyCheckedInError(ValueError):
    """Raised when check-in is attempted on a visit that is already checked in.

    Args:
        visit_id: The visit that is already active.
    """

    def __init__(self, visit_id: str) -> None:
        super().__init__(
            f"Visit {visit_id!r} is already checked in. "
            "Use checkout() to complete the visit."
        )
        self.visit_id = visit_id
