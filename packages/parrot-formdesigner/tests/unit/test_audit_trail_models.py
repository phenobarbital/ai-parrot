"""Unit tests for deterministic validation audit-trail models (TASK-4644)."""

from parrot_formdesigner.core import (
    DEFAULT_MAX_BYTES,
    AuditDetail,
    AuditTrailConfig,
    CheckId,
    FormSchema,
    LLMValidationConfig,
)

FROZEN_CHECK_IDS = {
    "form.circular_dependencies",
    "form.rule_integrity",
    "resolution.visible",
    "resolution.required",
    "field.voice_envelope",
    "field.required",
    "field.relation_shape",
    "field.coerce",
    "field.type",
    "field.option_set",
    "field.cross_field",
    "field.async_validator",
    "field.remote_response",
    "field.rest",
    "constraint.min_length",
    "constraint.max_length",
    "constraint.min_value",
    "constraint.max_value",
    "constraint.pattern",
    "constraint.min_items",
    "constraint.max_items",
    "constraint.allowed_mime_types",
}


def _form(**kwargs: object) -> FormSchema:
    """Build the smallest valid form schema for audit configuration checks."""
    return FormSchema(form_id="audit-test", title="Audit test", sections=[], **kwargs)


def test_audit_detail_default_is_summary() -> None:
    """Absent config resolves to summary."""
    config = AuditTrailConfig()

    assert config.detail is AuditDetail.SUMMARY
    assert _form().audit_trail is None


def test_cap_default_per_detail() -> None:
    """max_bytes=None resolves by detail; explicit max_bytes always wins."""
    assert AuditTrailConfig().effective_max_bytes == DEFAULT_MAX_BYTES[AuditDetail.SUMMARY] == 65_536
    assert AuditTrailConfig(detail=AuditDetail.FULL).effective_max_bytes == DEFAULT_MAX_BYTES[AuditDetail.FULL] == 262_144
    assert AuditTrailConfig(detail=AuditDetail.SUMMARY, max_bytes=4096).effective_max_bytes == 4096
    assert AuditTrailConfig(detail=AuditDetail.FULL, max_bytes=500_000).effective_max_bytes == 500_000


def test_check_id_values_are_stable() -> None:
    """Guards the published contract against a rename."""
    assert {check_id.value for check_id in CheckId} == FROZEN_CHECK_IDS


def test_audit_trail_independent_of_llm_validation() -> None:
    """Disabling the LLM check leaves deterministic auditing at its default."""
    form = _form(llm_validation=LLMValidationConfig(enabled=False))

    assert form.llm_validation is not None
    assert form.llm_validation.enabled is False
    assert form.audit_trail is None
    assert (form.audit_trail or AuditTrailConfig()).detail is AuditDetail.SUMMARY
