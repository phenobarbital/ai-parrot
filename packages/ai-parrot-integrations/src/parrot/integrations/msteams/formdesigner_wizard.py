"""Per-conversation wizard state for sectioned FormDesigner cards (FEAT-734 M5). Process-local."""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

_Key = tuple[str, uuid.UUID]


@dataclass
class WizardState:
    """One in-flight sectioned form for one conversation."""

    form_uid: uuid.UUID
    tenant: str
    section_index: int
    total_sections: int
    wizard_id: uuid.UUID
    owner_user_id: str
    form_version: str
    answers: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0
    consumed: bool = False  # set before the single terminal POST
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


class WizardStore:
    """Process-local wizard state, keyed by (conversation_id, form_uid)."""

    def __init__(self, ttl_seconds: float = 3600.0, max_items: int = 512) -> None:
        """Create a store.

        Args:
            ttl_seconds: Idle lifetime of a wizard state.
            max_items: Maximum number of retained states (LRU-evicted).
        """
        self._ttl = ttl_seconds
        self._max = max_items
        self._items: OrderedDict[_Key, WizardState] = OrderedDict()

    def __len__(self) -> int:
        """Number of retained states."""
        return len(self._items)

    def _now(self) -> float:
        return time.monotonic()

    def start(
        self,
        *,
        conversation_id: str,
        form_uid: uuid.UUID,
        tenant: str,
        total_sections: int,
        owner_user_id: str,
        form_version: str,
    ) -> WizardState:
        """Begin (or restart) a wizard; always a fresh wizard_id at section 0."""
        state = WizardState(
            form_uid=form_uid,
            tenant=tenant,
            section_index=0,
            total_sections=total_sections,
            wizard_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            form_version=form_version,
            updated_at=self._now(),
        )
        key = (conversation_id, form_uid)
        self._items[key] = state
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)
        return state

    def get(self, *, conversation_id: str, form_uid: uuid.UUID) -> WizardState | None:
        """None when absent or expired — the caller then restarts the form."""
        key = (conversation_id, form_uid)
        state = self._items.get(key)
        if state is None:
            return None
        if self._now() - state.updated_at > self._ttl:
            self._items.pop(key, None)
            return None
        return state

    def advance(self, state: WizardState, answers: dict[str, Any]) -> WizardState:
        """Merge this step's answers and move to the next section (caller already validated)."""
        state.answers.update(answers)
        state.section_index += 1
        state.updated_at = self._now()
        for key, value in self._items.items():
            if value is state:
                self._items.move_to_end(key)
                break
        return state

    def finish(self, *, conversation_id: str, form_uid: uuid.UUID) -> dict[str, Any]:
        """Pop the state and return the accumulated answers ({} when absent)."""
        state = self._items.pop((conversation_id, form_uid), None)
        return dict(state.answers) if state is not None else {}

    def discard(self, *, conversation_id: str, form_uid: uuid.UUID) -> None:
        """Remove state without posting (Cancel)."""
        self._items.pop((conversation_id, form_uid), None)
