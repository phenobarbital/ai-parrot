"""Deterministic validation trace: collector, schema fingerprint, size cap (FEAT-732).

Pure in-memory bookkeeping. ``FormValidator`` records into a collector it is
handed explicitly; ``SubmissionPipeline`` seals, caps and persists the result.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ..core.audit_trail import (
    AuditDetail,
    CheckId,
    CheckOutcome,
    CheckRecord,
    FieldTrace,
    SkipReason,
    ValidationTrace,
)
from ..core.schema import FormField, FormSchema, FormSubsection

__all__ = ["ValidationTraceCollector", "callable_identity", "cap_trace", "schema_fingerprint"]


def callable_identity(fn: Any) -> str:
    """Return a stable, process-independent name for a callable."""
    module = getattr(fn, "__module__", None) or "?"
    qualname = getattr(fn, "__qualname__", None) or type(fn).__qualname__
    return f"callable:{module}.{qualname}"


class ValidationTraceCollector:
    """Accumulate deterministic validation evidence for one ``validate`` call."""

    def __init__(
        self,
        *,
        detail: AuditDetail,
        locale: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Build a collector.

        Args:
            detail: Evidence detail level. ``OFF`` is invalid because callers
                skip collector construction for disabled auditing.
            locale: Locale used by validation messages.
            clock: Optional wall-clock provider for deterministic tests.

        Raises:
            ValueError: If ``detail`` is ``OFF``.
        """
        if detail is AuditDetail.OFF:
            raise ValueError("ValidationTraceCollector is never built for detail=off")
        self.detail = detail
        self.locale = locale
        self._started = time.monotonic()
        self._validated_at = (clock or (lambda: datetime.now(timezone.utc)))()
        self._form_checks: dict[CheckId, CheckRecord] = {}
        self._fields: dict[str, dict[str, Any]] = {}

    def _field(self, field_id: str) -> dict[str, Any]:
        """Return the mutable trace entry for ``field_id``, creating it if needed."""
        return self._fields.setdefault(field_id, {"visible": True, "required": False, "records": {}})

    def record_form(
        self,
        check: CheckId,
        outcome: CheckOutcome,
        *,
        message: str | None = None,
        skip_reason: SkipReason | None = None,
    ) -> None:
        """Record a form-level check.

        Raises:
            ValueError: If a skipped check has no reason.
        """
        if outcome is CheckOutcome.SKIP and skip_reason is None:
            raise ValueError("A skipped check requires a skip reason")
        self._form_checks[check] = CheckRecord(
            check=check,
            outcome=outcome,
            message=message if outcome is CheckOutcome.FAIL else None,
            skip_reason=skip_reason,
        )

    def record_resolution(self, field_id: str, *, visible: bool, required: bool) -> None:
        """Record the effective visibility and requirement for one field."""
        entry = self._field(field_id)
        entry["visible"], entry["required"] = visible, required
        entry["records"][CheckId.RESOLUTION_VISIBLE] = CheckRecord(
            check=CheckId.RESOLUTION_VISIBLE,
            outcome=CheckOutcome.PASS,
            bound=f"visible={visible}",
        )
        entry["records"][CheckId.RESOLUTION_REQUIRED] = CheckRecord(
            check=CheckId.RESOLUTION_REQUIRED,
            outcome=CheckOutcome.PASS,
            bound=f"required={required}",
        )

    def record(
        self,
        field_id: str,
        check: CheckId,
        outcome: CheckOutcome,
        *,
        bound: str | None = None,
        skip_reason: SkipReason | None = None,
        message: str | None = None,
    ) -> None:
        """Record one field-level check, replacing an earlier result for the same check.

        Raises:
            ValueError: If a skipped check has no reason.
        """
        if outcome is CheckOutcome.SKIP and skip_reason is None:
            raise ValueError("A skipped check requires a skip reason")
        self._field(field_id)["records"][check] = CheckRecord(
            check=check,
            outcome=outcome,
            bound=bound,
            skip_reason=skip_reason,
            message=message if outcome is CheckOutcome.FAIL else None,
        )

    def skip_remaining(
        self,
        field_id: str,
        checks: Iterable[tuple[CheckId, str | None]],
        reason: SkipReason,
    ) -> None:
        """Record skipped declared checks without overwriting checks already reached."""
        records = self._field(field_id)["records"]
        for check, bound in checks:
            if check not in records:
                self.record(
                    field_id,
                    check,
                    CheckOutcome.SKIP,
                    bound=bound,
                    skip_reason=reason,
                )

    def finish(
        self,
        form: FormSchema,
        *,
        fingerprint: str,
        ruleset_version: str,
        is_valid: bool,
    ) -> ValidationTrace:
        """Seal the collector into a trace with the configured detail projection."""
        fields: list[FieldTrace] = []
        checks_run = sum(record.outcome is not CheckOutcome.SKIP for record in self._form_checks.values())
        checks_failed = sum(record.outcome is CheckOutcome.FAIL for record in self._form_checks.values())

        for field_id, entry in self._fields.items():
            records = list(entry["records"].values())
            checks_ran = [record.check for record in records if record.outcome is not CheckOutcome.SKIP]
            failures = [record for record in records if record.outcome is CheckOutcome.FAIL]
            checks_run += len(checks_ran)
            checks_failed += len(failures)
            fields.append(
                FieldTrace(
                    field_id=field_id,
                    required_effective=entry["required"],
                    visible_effective=entry["visible"],
                    checks_ran=checks_ran,
                    records=records if self.detail is AuditDetail.FULL else [],
                    failures=failures,
                )
            )

        return ValidationTrace(
            detail=self.detail,
            form_uid=form.form_uid,
            form_id=form.form_id,
            form_version=form.version,
            schema_fingerprint=fingerprint,
            ruleset_version=ruleset_version,
            locale=self.locale,
            validated_at=self._validated_at,
            duration_ms=int((time.monotonic() - self._started) * 1000),
            checks_run=checks_run,
            checks_failed=checks_failed,
            is_valid=is_valid,
            form_checks=list(self._form_checks.values()),
            fields=fields,
        )


_EXCLUDED_CONSTRAINT_KEYS = {"pattern_message", "anchor_labels"}
_CHECK_DEFINING_META_KEYS = ("cross_field_validators", "async_validator", "rest")


def _jsonable(value: Any) -> Any:
    """Convert a Pydantic model to a JSON-safe dictionary."""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _validation_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return only metadata that defines validation checks."""
    if not meta:
        return None

    result: dict[str, Any] = {}
    if "cross_field_validators" in meta:
        result["cross_field_validators"] = [callable_identity(fn) for fn in meta["cross_field_validators"]]
    if "async_validator" in meta:
        result["async_validator"] = callable_identity(meta["async_validator"])
    if "rest" in meta:
        result["rest"] = _jsonable(meta["rest"])
    return result or None


def _field_subset(field: FormField) -> dict[str, Any]:
    """Return the validation-relevant projection of one field."""
    return {
        "field_id": field.field_id,
        "field_type": field.field_type.value,
        "required": field.required,
        "constraints": (
            field.constraints.model_dump(mode="json", exclude=_EXCLUDED_CONSTRAINT_KEYS)
            if field.constraints is not None
            else None
        ),
        "options": sorted(str(option.value) for option in field.options) if field.options is not None else None,
        "depends_on": _jsonable(field.depends_on),
        "post_depends": [_jsonable(rule) for rule in field.post_depends] if field.post_depends is not None else None,
        "relation": _jsonable(field.relation),
        "content_type": field.content_type,
        "accept_content_types": field.accept_content_types,
        "answer_envelope": field.answer_envelope,
        "meta": _validation_meta(field.meta),
    }


def schema_fingerprint(form: FormSchema) -> str:
    """Hash the validation-relevant subset using the validator's field traversal."""
    from .validators import FormValidator

    validator = FormValidator()
    sections = [
        {
            "section_id": section.section_id,
            "depends_on": _jsonable(section.depends_on),
            "subsections": [
                {
                    "subsection_id": item.subsection_id,
                    "depends_on": _jsonable(item.depends_on),
                }
                for item in section.fields
                if isinstance(item, FormSubsection)
            ],
            "fields": [_field_subset(field) for field in validator._collect_fields(section)],
        }
        for section in form.sections
    ]
    payload = {"unknown_fields": getattr(form.unknown_fields, "value", form.unknown_fields), "sections": sections}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


_COUNTER_SLACK = 64


def _size(payload: Any) -> int:
    """Return the UTF-8 length of compact JSON for ``payload``."""
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def cap_trace(trace: ValidationTrace, *, max_bytes: int) -> dict[str, Any]:
    """Serialize a trace within ``max_bytes``, dropping successful fields first."""
    payload = trace.model_dump(mode="json")
    total_size = _size(payload)
    if total_size <= max_bytes:
        return payload

    fields = payload["fields"]
    drop_order = sorted(
        fields,
        key=lambda field: (bool(field["failures"]), field["field_id"]),
    )
    encoded_sizes = {id(field): _size(field) + 1 for field in fields}
    dropped_ids: set[int] = set()
    omitted_fields = 0
    omitted_checks = 0

    def drop(field: dict[str, Any]) -> None:
        nonlocal total_size, omitted_fields, omitted_checks
        dropped_ids.add(id(field))
        total_size -= encoded_sizes[id(field)]
        omitted_fields += 1
        omitted_checks += len(field["checks_ran"])

    remaining_drop_order = iter(drop_order)
    while total_size + _COUNTER_SLACK > max_bytes:
        try:
            drop(next(remaining_drop_order))
        except StopIteration:
            break

    payload["fields"] = [field for field in fields if id(field) not in dropped_ids]
    payload["truncated"] = True
    payload["omitted_fields"] = omitted_fields
    payload["omitted_checks"] = omitted_checks

    while _size(payload) > max_bytes:
        try:
            field = next(remaining_drop_order)
        except StopIteration:
            break
        drop(field)
        payload["fields"] = [item for item in payload["fields"] if id(item) != id(field)]
        payload["omitted_fields"] = omitted_fields
        payload["omitted_checks"] = omitted_checks

    if _size(payload) > max_bytes:
        for record in payload["form_checks"]:
            record["message"] = None

    if _size(payload) > max_bytes:
        raise ValueError("max_bytes is too small for the validation trace header")
    return payload
