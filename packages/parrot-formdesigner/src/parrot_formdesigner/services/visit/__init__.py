"""Visit & Event Lifecycle services (FEAT-303).

Provides the ``Event → Shift → Visit → FormSubmission`` lifecycle layer for
multi-shift store visits. Public surface:

- Models: ``Event``, ``Shift``, ``Visit``, ``MissedReason``, ``GpsCoord``,
  ``EventStatus``, ``ShiftStatus``.
- Storage: ``EventStorage`` (ABC), ``InMemoryEventStorage``,
  ``PostgresEventStorage`` (JSONB document in ``navigator.events``).
- Services: ``EventService``, ``ShiftService``, ``VisitService``,
  ``MissedReasonService``.
- Geofence: ``GeofenceValidator``, ``GeofenceResult``, ``GeofenceStatus``.
- Errors: ``InvalidTransitionError``, ``OverlappingShiftError``,
  ``GeofenceViolationError``, ``VisitAlreadyCheckedInError``.
- Payroll hook: ``PayrollHook`` (ABC), ``NullPayrollHook``.
"""

from .errors import (
    GeofenceViolationError,
    InvalidTransitionError,
    OverlappingShiftError,
    VisitAlreadyCheckedInError,
)
from .geofence import GeofenceResult, GeofenceStatus, GeofenceValidator
from .missed_reasons import MissedReasonService
from .models import (
    Event,
    EventStatus,
    GpsCoord,
    MissedReason,
    Shift,
    ShiftStatus,
    Visit,
)
from .payroll_hook import NullPayrollHook, PayrollHook
from .storage import EventStorage, InMemoryEventStorage, PostgresEventStorage
from .event_service import EventService
from .shift_service import ShiftService
from .visit_service import VisitService

__all__ = [
    # Models
    "Event",
    "EventStatus",
    "GpsCoord",
    "MissedReason",
    "Shift",
    "ShiftStatus",
    "Visit",
    # Storage
    "EventStorage",
    "InMemoryEventStorage",
    "PostgresEventStorage",
    # Services
    "EventService",
    "MissedReasonService",
    "ShiftService",
    "VisitService",
    # Geofence
    "GeofenceResult",
    "GeofenceStatus",
    "GeofenceValidator",
    # Payroll hook
    "NullPayrollHook",
    "PayrollHook",
    # Errors
    "GeofenceViolationError",
    "InvalidTransitionError",
    "OverlappingShiftError",
    "VisitAlreadyCheckedInError",
]
