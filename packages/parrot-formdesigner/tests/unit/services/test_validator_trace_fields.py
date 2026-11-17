"""Per-field validation-trace recording tests (FEAT-732)."""

import pytest

from parrot_formdesigner.core.audit_trail import AuditDetail, CheckId, CheckOutcome, SkipReason
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validation_trace import ValidationTraceCollector
from parrot_formdesigner.services.validators import FormValidator


def _full() -> ValidationTraceCollector:
    """Build a full-detail collector for assertions on individual records."""
    return ValidationTraceCollector(detail=AuditDetail.FULL, locale="en")


def _field(field_id: str, field_type: FieldType = FieldType.TEXT, **kwargs: object) -> FormField:
    """Build a minimal form field."""
    return FormField(field_id=field_id, field_type=field_type, label=field_id, **kwargs)


async def _trace(field: FormField, value: object, validator: FormValidator | None = None):
    """Validate one field and return its full sealed trace."""
    form = FormSchema(form_id="trace", title="Trace", sections=[FormSection(section_id="s", fields=[field])])
    result = await (validator or FormValidator()).validate(form, {field.field_id: value}, trace=_full())
    assert result.trace is not None
    return result, result.trace


def _records(trace, field_id: str):
    """Return the full records indexed by check identifier for one field."""
    entry = next(item for item in trace.fields if item.field_id == field_id)
    return {record.check: record for record in entry.records}


async def test_full_records_bound_per_check() -> None:
    """A valid declared constraint records its stable bound and pass result."""
    field = _field("code", required=True, constraints=FieldConstraints(pattern=r"^[A-Z]+$"))

    _, trace = await _trace(field, "ABC")
    records = _records(trace, "code")

    assert [record.check for record in next(item for item in trace.fields if item.field_id == "code").records] == [
        CheckId.RESOLUTION_VISIBLE,
        CheckId.RESOLUTION_REQUIRED,
        CheckId.FIELD_REQUIRED,
        CheckId.FIELD_COERCE,
        CheckId.CONSTRAINT_PATTERN,
        CheckId.FIELD_TYPE,
    ]
    assert records[CheckId.CONSTRAINT_PATTERN].outcome is CheckOutcome.PASS
    assert records[CheckId.CONSTRAINT_PATTERN].bound == "pattern=^[A-Z]+$"


async def test_failed_bound_records_message() -> None:
    """A failed declared maximum preserves the validator's error message."""
    field = _field("name", constraints=FieldConstraints(max_length=3))

    result, trace = await _trace(field, "long")
    record = _records(trace, "name")[CheckId.CONSTRAINT_MAX_LENGTH]

    assert record.outcome is CheckOutcome.FAIL
    assert record.bound == "max_length=3"
    assert record.message in result.errors["name"]


async def test_empty_optional_skips_downstream() -> None:
    """An empty optional answer declares why no subsequent checks ran."""
    field = _field("note", constraints=FieldConstraints(max_length=3, pattern=r".+"))

    _, trace = await _trace(field, "")
    records = _records(trace, "note")

    assert records[CheckId.FIELD_REQUIRED].outcome is CheckOutcome.SKIP
    assert records[CheckId.FIELD_REQUIRED].skip_reason is SkipReason.NOT_APPLICABLE
    assert records[CheckId.FIELD_COERCE].skip_reason is SkipReason.EMPTY_OPTIONAL
    assert records[CheckId.CONSTRAINT_MAX_LENGTH].skip_reason is SkipReason.EMPTY_OPTIONAL
    assert records[CheckId.CONSTRAINT_PATTERN].skip_reason is SkipReason.EMPTY_OPTIONAL


async def test_required_empty_skips_rest_as_early_return() -> None:
    """A missing required answer fails before coercion and type validation."""
    field = _field("note", required=True, constraints=FieldConstraints(max_length=3))

    _, trace = await _trace(field, "")
    records = _records(trace, "note")

    assert records[CheckId.FIELD_REQUIRED].outcome is CheckOutcome.FAIL
    assert records[CheckId.FIELD_COERCE].skip_reason is SkipReason.EARLY_RETURN
    assert records[CheckId.CONSTRAINT_MAX_LENGTH].skip_reason is SkipReason.EARLY_RETURN


async def test_coercion_failure_skips_rest() -> None:
    """A coercion failure records its error and skips unreached checks."""
    field = _field("count", FieldType.NUMBER, constraints=FieldConstraints(min_value=1))

    _, trace = await _trace(field, "not-a-number")
    records = _records(trace, "count")

    assert records[CheckId.FIELD_COERCE].outcome is CheckOutcome.FAIL
    assert records[CheckId.CONSTRAINT_MIN_VALUE].skip_reason is SkipReason.EARLY_RETURN
    assert records[CheckId.FIELD_TYPE].skip_reason is SkipReason.EARLY_RETURN


async def test_remote_response_records_one_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """REMOTE_RESPONSE fields bypass all standard field checks."""
    validator = FormValidator()
    field = _field("remote", FieldType.REMOTE_RESPONSE)

    async def _resolve(*args: object, **kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr(validator, "_validate_remote_response", _resolve)
    _, trace = await _trace(field, {"request": "value"}, validator)
    records = _records(trace, "remote")

    assert list(records) == [CheckId.RESOLUTION_VISIBLE, CheckId.RESOLUTION_REQUIRED, CheckId.FIELD_REMOTE_RESPONSE]
    assert records[CheckId.FIELD_REMOTE_RESPONSE].outcome is CheckOutcome.PASS


async def test_rest_records_one_check() -> None:
    """REST fields record their dedicated early-return check only."""
    field = _field(
        "rest",
        FieldType.REST,
        meta={"rest": {"mode": "callback", "callback_ref": "callback"}},
    )

    _, trace = await _trace(field, {"answer": "ok", "blob_ref": None})
    records = _records(trace, "rest")

    assert list(records) == [CheckId.RESOLUTION_VISIBLE, CheckId.RESOLUTION_REQUIRED, CheckId.FIELD_REST]
    assert records[CheckId.FIELD_REST].outcome is CheckOutcome.PASS


async def test_voice_envelope_recursion_keeps_trace() -> None:
    """A valid spoken envelope is recorded once before scalar validation."""
    field = _field("spoken", required=True)
    voice = {"answer": "hello", "blob_ref": "voice-1", "source": "speech", "confidence": 0.9}

    _, trace = await _trace(field, voice)
    entry = next(item for item in trace.fields if item.field_id == "spoken")

    assert entry.records[2].check is CheckId.FIELD_VOICE_ENVELOPE
    assert entry.records[2].outcome is CheckOutcome.PASS
    assert sum(record.check is CheckId.FIELD_VOICE_ENVELOPE for record in entry.records) == 1
    assert CheckId.FIELD_TYPE in {record.check for record in entry.records}


async def test_mime_without_sidechannel_is_explicit() -> None:
    """Legacy file strings disclose that MIME could not be checked."""
    field = _field(
        "file",
        FieldType.FILE,
        constraints=FieldConstraints(allowed_mime_types=["image/*"]),
    )

    _, trace = await _trace(field, "legacy-file")
    record = _records(trace, "file")[CheckId.CONSTRAINT_ALLOWED_MIME_TYPES]

    assert record.outcome is CheckOutcome.SKIP
    assert record.skip_reason is SkipReason.NO_MIME_SIDECHANNEL
    assert record.bound == "allowed_mime_types=image/*"


async def test_undeclared_bound_not_recorded() -> None:
    """Absent constraints are absent from full records and checks-ran."""
    field = _field("plain")

    _, trace = await _trace(field, "value")
    entry = next(item for item in trace.fields if item.field_id == "plain")

    assert CheckId.CONSTRAINT_MAX_LENGTH not in {record.check for record in entry.records}
    assert CheckId.CONSTRAINT_MAX_LENGTH not in entry.checks_ran


async def test_no_value_leaks_into_bounds() -> None:
    """Submitted content never appears in the audit's rule evidence."""
    secret = "VALUE-THAT-MUST-NOT-LEAK"
    field = _field("safe", constraints=FieldConstraints(max_length=2, pattern=r"^[a-z]+$"))

    _, trace = await _trace(field, secret)
    entry = next(item for item in trace.fields if item.field_id == "safe")
    evidence = " ".join(
        part
        for record in entry.records
        for part in (record.bound, record.skip_reason.value if record.skip_reason else None)
        if part
    )

    assert secret not in evidence
