"""Ephemeral partial form answer cache model.

Represents work-in-progress form answers stored in Redis under the key
``parrot:partial:{form_id}:{session_id}``.  This model is the data contract
between the ``PartialSaveStore`` service and the REST handlers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PartialFormData(BaseModel):
    """Ephemeral partial form answer cache entry.

    Stored in Redis under key ``parrot:partial:{form_id}:{session_id}``.
    All datetime fields are expected to be UTC timezone-aware.

    Attributes:
        form_id: The form whose answers are being cached.
        session_id: The user session that owns this cache entry.
        data: Sparse mapping of field_id to the cached value.  New values
            always override existing cached values (last-write-wins).
        field_errors: Per-field validation errors collected during the last
            ``save_partial`` call.  Mapping of field_id to a list of error
            message strings.
        saved_at: UTC timestamp of the most recent write.
        expires_at: UTC timestamp when this entry will expire in Redis.
    """

    form_id: str
    session_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    saved_at: datetime
    expires_at: datetime
