"""Request-local FormDesigner context for one Teams turn (FEAT-734 normal-turn toolkit lifecycle)."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class FormDesignerTurn:
    """Identity + pending-card queue for exactly one turn. Plain values only."""

    conversation_id: str
    tenant: str | None = None
    tenant_source: str | None = None
    bearer: str | None = None
    user_id: str | None = None
    login_required: bool = False
    error: str | None = None
    pending: list[uuid.UUID] = field(default_factory=list)
    closed: bool = False

    def enqueue(self, form_uid: uuid.UUID) -> bool:
        """Queue a card; False when closed. Dedupes, first-request order."""
        if self.closed:
            return False
        if form_uid in self.pending:
            return True
        self.pending.append(form_uid)
        return True

    def drain(self) -> list[uuid.UUID]:
        """Return and clear the queue."""
        items, self.pending = self.pending, []
        return items

    def close(self) -> None:
        """Mark closed and drop credentials and queue."""
        self.closed = True
        self.bearer = None
        self.pending = []


_CURRENT: ContextVar[FormDesignerTurn | None] = ContextVar("formdesigner_turn", default=None)


def active_turn() -> FormDesignerTurn | None:
    """The bound, still-open turn, or None (unbound or closed)."""
    turn = _CURRENT.get()
    return turn if turn is not None and not turn.closed else None


@asynccontextmanager
async def bind_turn(turn: FormDesignerTurn) -> AsyncIterator[FormDesignerTurn]:
    """Bind `turn` for the block; always close it and reset the ContextVar."""
    token = _CURRENT.set(turn)
    try:
        yield turn
    finally:
        turn.close()
        _CURRENT.reset(token)
