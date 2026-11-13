"""Typed storage errors (FEAT-886).

Retry classification (used by ``ChatStorage.handle_turn_completed``):
retryable — :class:`StorageUnavailableError`, :class:`StorageWriteError`;
terminal — :class:`ConversationDeletedError`, :class:`InvalidTurnPayloadError`;
state — :class:`IndexNotReadyError` (the chronological index is not backfilled yet).
"""
from __future__ import annotations

from parrot.exceptions import ParrotError


class StorageError(ParrotError):
    """Base class for every failure raised by the conversation storage layer."""


class StorageUnavailableError(StorageError):
    """The backend is disconnected or the transport failed — retryable."""


class StorageWriteError(StorageError):
    """The durable write failed — retryable."""


class ConversationDeletedError(StorageError):
    """The session (or turn) identity is tombstoned — terminal."""


class IndexNotReadyError(StorageError):
    """The chronological index of the session is not backfilled (`pending` / `invalid`)."""


class InvalidTurnPayloadError(StorageError):
    """A permanent payload defect (missing identity or unparseable timestamp) — terminal."""
