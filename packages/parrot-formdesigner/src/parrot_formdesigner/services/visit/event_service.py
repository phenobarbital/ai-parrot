"""EventService — CRUD + state-machine transitions for Events (FEAT-303).

``EventService`` wraps ``EventStorage`` and enforces the ``EventStatus``
state machine.  Every public method is async and tenant-scoped.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .errors import InvalidTransitionError
from .models import (
    Event,
    EventStatus,
    EVENT_TRANSITIONS,
)
from .storage import EventStorage

if TYPE_CHECKING:
    from ..registry import FormRegistry


class EventService:
    """CRUD service for ``Event`` objects with state-machine transition support.

    Args:
        storage: Persistence backend for events.
        registry: ``FormRegistry`` used to validate recap form IDs.
        tenant: Default tenant slug for all operations.
    """

    def __init__(
        self,
        storage: EventStorage,
        registry: "FormRegistry",
        *,
        tenant: str,
    ) -> None:
        self._storage = storage
        self._registry = registry
        self._tenant = tenant
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_event(self, payload: dict[str, Any]) -> Event:
        """Create and persist a new ``Event``.

        The ``payload`` dict is validated against the ``Event`` schema.
        ``tenant`` defaults to the service-level tenant when not present
        in the payload.

        Args:
            payload: Dict conforming to the ``Event`` model fields.

        Returns:
            The persisted ``Event`` instance.
        """
        if "tenant" not in payload or payload["tenant"] is None:
            payload = {**payload, "tenant": self._tenant}

        event = Event.model_validate(payload)
        # Ensure each Shift has the event_id set
        updated_shifts = []
        for shift in event.shifts:
            if not shift.event_id:
                shift = shift.model_copy(update={"event_id": event.event_id})
            updated_shifts.append(shift)
        if updated_shifts:
            event = event.model_copy(update={"shifts": updated_shifts})

        await self._storage.save(event, tenant=self._tenant)
        self.logger.info(
            "Created event %s (tenant=%r, shifts=%d)",
            event.event_id,
            self._tenant,
            len(event.shifts),
        )
        return event

    async def get_event(self, event_id: str) -> Event | None:
        """Load an event by ID.

        Args:
            event_id: The identifier to look up.

        Returns:
            ``Event`` if found, ``None`` otherwise.
        """
        return await self._storage.load(event_id, tenant=self._tenant)

    async def list_events(self, **filters: Any) -> list[Event]:
        """List all events for the service tenant.

        Args:
            **filters: Optional filter kwargs forwarded to the storage backend.

        Returns:
            List of ``Event`` objects.
        """
        dicts = await self._storage.list_events(tenant=self._tenant, **filters)
        return [Event.model_validate(d) for d in dicts]

    async def transition(self, event_id: str, status: EventStatus) -> Event:
        """Apply a state-machine transition to an Event.

        Args:
            event_id: The identifier of the event to transition.
            status: The target ``EventStatus``.

        Returns:
            The updated ``Event`` with the new status.

        Raises:
            ValueError: If the event is not found.
            InvalidTransitionError: If the transition is not allowed.
        """
        event = await self.get_event(event_id)
        if event is None:
            raise ValueError(f"Event {event_id!r} not found (tenant={self._tenant!r})")

        allowed = EVENT_TRANSITIONS.get(event.status, set())
        if status not in allowed:
            raise InvalidTransitionError(
                from_status=event.status.value,
                to_status=status.value,
                entity="Event",
            )

        updated = event.model_copy(update={"status": status})
        await self._storage.save(updated, tenant=self._tenant)
        self.logger.info(
            "Event %s transitioned %s → %s",
            event_id,
            event.status.value,
            status.value,
        )
        return updated

    async def save_event(self, event: Event) -> Event:
        """Persist an already-constructed ``Event`` (used by ShiftService / VisitService).

        Args:
            event: The ``Event`` instance to persist.

        Returns:
            The same ``Event`` (after saving).
        """
        await self._storage.save(event, tenant=self._tenant)
        return event
