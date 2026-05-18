"""Pydantic I/O models for submission metadata callbacks.

A *metadata callback* is an async coroutine registered with
``register_form_callback`` (in :mod:`.callback_registry`) and referenced
from a ``FormMetadataField`` with ``source='callback'``. The submit
handler invokes the callback in the enrichment step (after validation,
before storage) and merges its output into the persisted submission.

These models intentionally live in their own module — separate from
``rest_field_resolver`` — because the input payload is shaped around
form *answers* rather than uploaded file content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..core.schema import FormMetadataField


class MetadataCallbackInput(BaseModel):
    """Payload delivered to a registered metadata-callback coroutine.

    Attributes:
        form_id: ID of the form being submitted.
        submission_id: UUID of the in-flight submission (not yet stored).
        user_id: Authenticated user ID (may be ``None``).
        username: Authenticated username (may be ``None``).
        org_id: Authenticated organization ID (may be ``None``).
        tenant: Tenant slug (may be ``None``).
        programs: Tenant programs list (may be empty).
        submitted_at: UTC timestamp of the submission.
        answers: Sanitized form answers as produced by the validator.
            The callback MUST treat this dict as read-only.
        field: The ``FormMetadataField`` declaration that triggered this
            invocation. Carries ``options`` / ``default`` for the
            callback to honour.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    form_id: str
    submission_id: str
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    tenant: str | None = None
    programs: list[str] = Field(default_factory=list)
    submitted_at: datetime
    answers: dict[str, Any]
    field: FormMetadataField


class MetadataCallbackOutput(BaseModel):
    """Return value from a registered metadata-callback coroutine.

    A callback MAY return either a single value (stored under the
    declaring field's ``key``) OR a fan-out dict of additional keys
    merged into the submission. When ``values`` is set it takes
    precedence over ``value``.

    Attributes:
        success: Whether the callback completed successfully. ``False``
            triggers either the ``default`` substitution (when the
            field is not required) or a 422 (when it is).
        value: Single computed value, stored under the field's ``key``.
            Used only when ``values`` is ``None``.
        values: Optional fan-out dict merged flat into the submission.
            Every key must be a valid identifier — keys are checked at
            merge time by the enricher.
        error: Human-readable error message on failure (logged).
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    value: Any | None = None
    values: dict[str, Any] | None = None
    error: str | None = None
