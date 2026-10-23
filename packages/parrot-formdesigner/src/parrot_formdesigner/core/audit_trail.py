"""Deterministic validation audit-trail models (FEAT-732).

Declares the per-form ``FormSchema.audit_trail`` block, the stable check
vocabulary, and the sealed ``ValidationTrace`` persisted into
``FormSubmission.context["validation"]``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AuditDetail(str, Enum):
    """How much deterministic validation evidence to retain."""

    OFF = "off"
    SUMMARY = "summary"
    FULL = "full"


class CheckId(str, Enum):
    """Stable identifier for one deterministic validation check.

    Values are a published contract: they are persisted into submission rows
    and read back by auditors, so they are NEVER derived from a helper name or
    a localised error message, and an existing value is never renamed.
    """

    FORM_CIRCULAR_DEPENDENCIES = "form.circular_dependencies"
    FORM_RULE_INTEGRITY = "form.rule_integrity"
    RESOLUTION_VISIBLE = "resolution.visible"
    RESOLUTION_REQUIRED = "resolution.required"
    FIELD_VOICE_ENVELOPE = "field.voice_envelope"
    FIELD_REQUIRED = "field.required"
    FIELD_RELATION_SHAPE = "field.relation_shape"
    FIELD_COERCE = "field.coerce"
    FIELD_TYPE = "field.type"
    FIELD_OPTION_SET = "field.option_set"
    FIELD_CROSS_FIELD = "field.cross_field"
    FIELD_ASYNC_VALIDATOR = "field.async_validator"
    FIELD_REMOTE_RESPONSE = "field.remote_response"
    FIELD_REST = "field.rest"
    CONSTRAINT_MIN_LENGTH = "constraint.min_length"
    CONSTRAINT_MAX_LENGTH = "constraint.max_length"
    CONSTRAINT_MIN_VALUE = "constraint.min_value"
    CONSTRAINT_MAX_VALUE = "constraint.max_value"
    CONSTRAINT_PATTERN = "constraint.pattern"
    CONSTRAINT_MIN_ITEMS = "constraint.min_items"
    CONSTRAINT_MAX_ITEMS = "constraint.max_items"
    CONSTRAINT_ALLOWED_MIME_TYPES = "constraint.allowed_mime_types"


class CheckOutcome(str, Enum):
    """Result of one recorded check."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class SkipReason(str, Enum):
    """Why a declared check did not run. A skip is evidence, not an absence of evidence.

    Undeclared checks are never recorded at all — their absence is provable
    from ``ValidationTrace.schema_fingerprint``.
    """

    NOT_APPLICABLE = "not_applicable"  # declared, but does not apply to this field (e.g. not required)
    EMPTY_OPTIONAL = "empty_optional"  # optional field arrived empty — validation short-circuits
    EARLY_RETURN = "early_return"  # an earlier check returned before this one
    NOT_DISPLAYED = "not_displayed"  # rule resolution hid the field, so required was relaxed
    NO_MIME_SIDECHANNEL = "no_mime_sidechannel"  # allowed_mime_types with no resolvable MIME
    WRONG_VALUE_SHAPE = "wrong_value_shape"  # bound declared but the coerced value cannot carry it


class CheckRecord(BaseModel):
    """One check, as retained under ``full`` detail (and every failure, at any detail)."""

    check: CheckId
    outcome: CheckOutcome
    bound: str | None = None
    skip_reason: SkipReason | None = None
    message: str | None = None


class FieldTrace(BaseModel):
    """Per-field evidence."""

    field_id: str
    required_effective: bool
    visible_effective: bool
    checks_ran: list[CheckId] = Field(default_factory=list)
    records: list[CheckRecord] = Field(default_factory=list)
    failures: list[CheckRecord] = Field(default_factory=list)


# Per-detail cap defaults (spec §2 E, §7 R6). `full` gets four times the room
# because it is the opt-in level that exists for disputes.
DEFAULT_MAX_BYTES: dict[AuditDetail, int] = {
    AuditDetail.OFF: 0,
    AuditDetail.SUMMARY: 65_536,
    AuditDetail.FULL: 262_144,
}


class AuditTrailConfig(BaseModel):
    """Per-form deterministic-audit settings (``FormSchema.audit_trail``)."""

    detail: AuditDetail = AuditDetail.SUMMARY
    max_bytes: int | None = Field(default=None, ge=1024, le=1_048_576)
    """Hard cap on the serialized trace. ``None`` resolves per `detail` via
    ``DEFAULT_MAX_BYTES``; an explicit value always wins, in either direction."""

    @property
    def effective_max_bytes(self) -> int:
        """Return `max_bytes`, or the `DEFAULT_MAX_BYTES` entry for `detail`."""
        return self.max_bytes if self.max_bytes is not None else DEFAULT_MAX_BYTES[self.detail]


class ValidationTrace(BaseModel):
    """Deterministic validation evidence for one submission.

    ``checks_run`` / ``FieldTrace.checks_ran`` count every non-skipped record, including the
    two always-passing ``resolution.*`` records written for each field, so a field with no
    declared constraints still reports a handful of checks.
    """

    trace_schema: int = 1
    detail: AuditDetail
    form_uid: uuid.UUID
    form_id: str
    form_version: str
    schema_fingerprint: str
    ruleset_version: str
    locale: str
    validated_at: datetime
    duration_ms: int
    checks_run: int
    checks_failed: int
    is_valid: bool
    form_checks: list[CheckRecord] = Field(default_factory=list)
    fields: list[FieldTrace] = Field(default_factory=list)
    truncated: bool = False
    omitted_fields: int = 0
    omitted_checks: int = 0
