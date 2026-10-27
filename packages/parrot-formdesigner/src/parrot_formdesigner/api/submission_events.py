"""Host post-submit hook for REST /data (FEAT-730)."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from pydantic import BaseModel


class SubmittedEvent(BaseModel):
    """Emitted after a successful REST /data store. Never on rejection or failure."""

    submission_id: str
    form_uid: uuid.UUID
    form_id: str
    form_version: str
    tenant: str
    is_public: bool
    created_at: datetime


SubmittedCallback = Callable[[SubmittedEvent], Awaitable[None]]

__all__ = ["SubmittedEvent", "SubmittedCallback"]
