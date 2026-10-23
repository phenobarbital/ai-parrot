"""Unit tests for deterministic validation trace collection and serialization."""

import json
from datetime import datetime, timezone

import pytest

from parrot_formdesigner.core.audit_trail import (
    AuditDetail,
    CheckId,
    CheckOutcome,
    SkipReason,
    ValidationTrace,
)
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validation_trace import (
    ValidationTraceCollector,
    callable_identity,
    cap_trace,
    schema_fingerprint,
)


def _form(**overrides: object) -> FormSchema:
    """Build a form containing representative validation rules."""
    data: dict[str, object] = {
        "form_id": "audit-form",
        "title": "Audit form",
        "sections": [
            FormSection(
                section_id="main",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label="Name",
                        required=True,
                        constraints=FieldConstraints(max_length=120, pattern="^[A-Z]+$"),
                    ),
                    FormField(
                        field_id="colour",
                        field_type=FieldType.SELECT,
                        label="Colour",
                        options=[
                            FieldOption(value="red", label="Red"),
                            FieldOption(value="blue", label="Blue"),
                        ],
                    ),
                    FormField(
                        field_id="items",
                        field_type=FieldType.ARRAY,
                        label="Items",
                        item_template=FormField(
                            field_id="item",
                            field_type=FieldType.TEXT,
                            label="Item",
                            constraints=FieldConstraints(max_length=20),
                        ),
                    ),
                ],
            )
        ],
    }
    data.update(overrides)
    return FormSchema.model_validate(data)


def _collector(detail: AuditDetail = AuditDetail.SUMMARY) -> ValidationTraceCollector:
    """Build a collector with a stable timestamp."""
    return ValidationTraceCollector(
        detail=detail,
        locale="en",
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _finish(collector: ValidationTraceCollector, *, valid: bool = True) -> ValidationTrace:
    """Seal a collector with stable header values."""
    return collector.finish(
        _form(),
        fingerprint="sha256:test",
        ruleset_version="1.0.0",
        is_valid=valid,
    )


def module_validator(value: object) -> None:
    """Provide a module-level callable for fingerprint stability tests."""


class TestCollector:
    """Collector recording and projection tests."""

    def test_last_write_wins(self) -> None:
        """A replacement keeps the check's original position and latest value."""
        collector = _collector(AuditDetail.FULL)
        collector.record("name", CheckId.FIELD_REQUIRED, CheckOutcome.FAIL, message="missing")
        collector.record("name", CheckId.FIELD_TYPE, CheckOutcome.PASS)
        collector.record("name", CheckId.FIELD_REQUIRED, CheckOutcome.PASS, message="discard me")

        trace = _finish(collector)

        assert [record.check for record in trace.fields[0].records] == [
            CheckId.FIELD_REQUIRED,
            CheckId.FIELD_TYPE,
        ]
        assert trace.fields[0].records[0].outcome is CheckOutcome.PASS
        assert trace.fields[0].records[0].message is None

    def test_skip_requires_reason(self) -> None:
        """Field-level and form-level skips require an explicit reason."""
        collector = _collector()
        with pytest.raises(ValueError, match="skip reason"):
            collector.record("name", CheckId.FIELD_REQUIRED, CheckOutcome.SKIP)
        with pytest.raises(ValueError, match="skip reason"):
            collector.record_form(CheckId.FORM_RULE_INTEGRITY, CheckOutcome.SKIP)

    def test_skip_remaining_never_overwrites(self) -> None:
        """Skipping a tail preserves checks that already ran."""
        collector = _collector(AuditDetail.FULL)
        collector.record("name", CheckId.FIELD_REQUIRED, CheckOutcome.FAIL, message="missing")
        collector.skip_remaining(
            "name",
            [(CheckId.FIELD_REQUIRED, "required=True"), (CheckId.FIELD_TYPE, "type=text")],
            SkipReason.EARLY_RETURN,
        )

        records = _finish(collector, valid=False).fields[0].records
        assert records[0].outcome is CheckOutcome.FAIL
        assert records[1].outcome is CheckOutcome.SKIP
        assert records[1].skip_reason is SkipReason.EARLY_RETURN

    def test_summary_projection(self) -> None:
        """Summary retains checks that ran and failures, but no full records."""
        collector = _collector()
        collector.record_form(CheckId.FORM_CIRCULAR_DEPENDENCIES, CheckOutcome.PASS)
        collector.record_resolution("name", visible=True, required=True)
        collector.record("name", CheckId.FIELD_REQUIRED, CheckOutcome.FAIL, message="missing")
        collector.record(
            "name",
            CheckId.FIELD_TYPE,
            CheckOutcome.SKIP,
            skip_reason=SkipReason.EARLY_RETURN,
        )

        trace = _finish(collector, valid=False)

        field = trace.fields[0]
        assert field.records == []
        assert field.checks_ran == [
            CheckId.RESOLUTION_VISIBLE,
            CheckId.RESOLUTION_REQUIRED,
            CheckId.FIELD_REQUIRED,
        ]
        assert [failure.check for failure in field.failures] == [CheckId.FIELD_REQUIRED]
        assert trace.checks_run == 4
        assert trace.checks_failed == 1

    def test_full_projection_keeps_skips(self) -> None:
        """Full detail retains skipped records while excluding them from counters."""
        collector = _collector(AuditDetail.FULL)
        collector.record("name", CheckId.FIELD_REQUIRED, CheckOutcome.PASS)
        collector.record(
            "name",
            CheckId.FIELD_TYPE,
            CheckOutcome.SKIP,
            skip_reason=SkipReason.EMPTY_OPTIONAL,
        )

        trace = _finish(collector)

        assert [record.outcome for record in trace.fields[0].records] == [
            CheckOutcome.PASS,
            CheckOutcome.SKIP,
        ]
        assert trace.checks_run == 1

    def test_off_detail_rejected(self) -> None:
        """Disabled auditing must avoid collector construction entirely."""
        with pytest.raises(ValueError, match="detail=off"):
            _collector(AuditDetail.OFF)


class TestFingerprint:
    """Schema fingerprint tests."""

    def test_deterministic(self) -> None:
        """Fresh equivalent forms produce the same fingerprint."""
        assert schema_fingerprint(_form()) == schema_fingerprint(_form())

    def test_changes_with_constraint(self) -> None:
        """A validation constraint change moves the fingerprint."""
        changed = _form()
        changed.sections[0].fields[0].constraints.max_length = 121
        assert schema_fingerprint(_form()) != schema_fingerprint(changed)

    def test_label_change_does_not_move_hash(self) -> None:
        """Presentation-only labels do not affect the fingerprint."""
        changed = _form()
        changed.sections[0].fields[0].label = "Display name"
        assert schema_fingerprint(_form()) == schema_fingerprint(changed)

    def test_excludes_array_item_template(self) -> None:
        """Array item-template rules are excluded because the validator does not run them."""
        changed = _form()
        changed.sections[0].fields[2].item_template.constraints.max_length = 999
        assert schema_fingerprint(_form()) == schema_fingerprint(changed)

    def test_callable_meta_is_stable(self) -> None:
        """Callable metadata uses an address-free stable identity."""
        first = _form()
        second = _form()
        first.sections[0].fields[0].meta = {"cross_field_validators": [module_validator]}
        second.sections[0].fields[0].meta = {"cross_field_validators": [module_validator]}

        assert callable_identity(module_validator).endswith(".module_validator")
        assert "0x" not in callable_identity(module_validator)
        assert schema_fingerprint(first) == schema_fingerprint(second)


class TestCap:
    """Serialized trace cap tests."""

    @staticmethod
    def _wide_trace() -> ValidationTrace:
        """Build a full trace with many passing fields and one failure."""
        collector = _collector(AuditDetail.FULL)
        for index in range(200):
            field_id = f"field-{index:03d}"
            for check in (
                CheckId.FIELD_REQUIRED,
                CheckId.FIELD_TYPE,
                CheckId.CONSTRAINT_MIN_LENGTH,
                CheckId.CONSTRAINT_MAX_LENGTH,
                CheckId.CONSTRAINT_PATTERN,
                CheckId.FIELD_OPTION_SET,
                CheckId.FIELD_CROSS_FIELD,
                CheckId.FIELD_ASYNC_VALIDATOR,
            ):
                outcome = (
                    CheckOutcome.FAIL if index == 199 and check is CheckId.CONSTRAINT_PATTERN else CheckOutcome.PASS
                )
                collector.record(
                    field_id,
                    check,
                    outcome,
                    bound="x" * 32,
                    message="failed" if outcome is CheckOutcome.FAIL else None,
                )
        return _finish(collector, valid=False)

    def test_under_cap_untouched(self) -> None:
        """A trace already under the cap is returned without truncation."""
        trace = _finish(_collector())
        assert cap_trace(trace, max_bytes=8192) == trace.model_dump(mode="json")

    def test_respects_max_bytes(self) -> None:
        """The compact JSON representation never exceeds the cap."""
        output = cap_trace(self._wide_trace(), max_bytes=8192)
        assert len(json.dumps(output, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) <= 8192

    def test_marks_truncation(self) -> None:
        """Truncation is explicit and reports omitted field and check counts."""
        output = cap_trace(self._wide_trace(), max_bytes=8192)
        assert output["truncated"] is True
        assert output["omitted_fields"] > 0
        assert output["omitted_checks"] > 0

    def test_drops_failures_last(self) -> None:
        """A failing field survives while any passing field has been retained."""
        output = cap_trace(self._wide_trace(), max_bytes=8192)
        retained = {field["field_id"]: field for field in output["fields"]}
        assert "field-199" in retained
        assert retained["field-199"]["failures"]
        assert output["omitted_fields"] > 0
