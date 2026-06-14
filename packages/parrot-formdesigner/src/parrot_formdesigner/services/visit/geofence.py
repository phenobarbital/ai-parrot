"""Geofence validation for Visit check-in / check-out (FEAT-303).

Provides ``GeofenceValidator`` — a pure-Python haversine distance check
against the event's configured geofence radius stored in ``Event.meta``.

No external geodesy library is required; haversine gives sufficient accuracy
for store-visit geofences (typically 50–500 m radius).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from .models import Event, GpsCoord


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class GeofenceStatus(str, Enum):
    """Outcome of a geofence validation check."""

    OK = "ok"
    OUTSIDE = "outside"
    ERROR = "error"


class GeofenceResult(BaseModel):
    """Result of a geofence validation check.

    Attributes:
        status: ``OK``, ``OUTSIDE``, or ``ERROR``.
        distance_m: Haversine distance from the geofence centre in metres.
            ``None`` when ``status`` is ``ERROR``.
        message: Optional human-readable message (error description or
            advisory note).
    """

    model_config = ConfigDict(extra="forbid")

    status: GeofenceStatus
    distance_m: float | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0  # WGS-84 mean radius in metres


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in metres.

    Uses the haversine formula for spherical Earth.  Sufficient accuracy
    for store-visit geofences (error < 0.5 % for distances < 500 km).

    Args:
        lat1: Latitude of point 1 in decimal degrees.
        lon1: Longitude of point 1 in decimal degrees.
        lat2: Latitude of point 2 in decimal degrees.
        lon2: Longitude of point 2 in decimal degrees.

    Returns:
        Great-circle distance in metres.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class GeofenceValidator:
    """Validates a GPS coordinate against an event's configured geofence.

    Reads ``geofence_lat``, ``geofence_lon``, and ``geofence_radius_m``
    from ``Event.meta``.  If any key is missing, returns ``GeofenceStatus.ERROR``.

    Args:
        accuracy_buffer_m: Extra metres added to the effective geofence
            radius to compensate for GPS inaccuracy.  Default 0.  Useful for
            very tight geofences (< 50 m) where device accuracy_m is large.
    """

    def __init__(self, accuracy_buffer_m: float = 0.0) -> None:
        self._buffer = accuracy_buffer_m

    def validate(self, coord: "GpsCoord", event: "Event") -> GeofenceResult:
        """Check whether ``coord`` is inside the event's geofence.

        Reads geofence parameters from ``event.meta``.

        Args:
            coord: The GPS coordinate to validate.
            event: The event carrying geofence parameters in ``meta``.

        Returns:
            ``GeofenceResult`` with ``OK``, ``OUTSIDE``, or ``ERROR``.
        """
        meta = event.meta or {}
        try:
            centre_lat = float(meta["geofence_lat"])
            centre_lon = float(meta["geofence_lon"])
            radius_m = float(meta["geofence_radius_m"])
        except (KeyError, TypeError, ValueError) as exc:
            return GeofenceResult(
                status=GeofenceStatus.ERROR,
                message=f"Missing or invalid geofence parameters in event.meta: {exc}",
            )

        distance_m = _haversine(coord.lat, coord.lon, centre_lat, centre_lon)
        effective_radius = radius_m + self._buffer

        # Optionally widen by reported device accuracy
        if coord.accuracy_m is not None and coord.accuracy_m > 0:
            effective_radius += coord.accuracy_m

        if distance_m <= effective_radius:
            return GeofenceResult(
                status=GeofenceStatus.OK,
                distance_m=distance_m,
            )
        else:
            return GeofenceResult(
                status=GeofenceStatus.OUTSIDE,
                distance_m=distance_m,
                message=(
                    f"Position is {distance_m:.1f} m from centre "
                    f"(effective radius: {effective_radius:.1f} m)"
                ),
            )
