"""Tests for client-safe plausibility report serialization (FEAT-732)."""

from parrot_formdesigner.core.llm_validation import (
    NOT_EXAMINED_UNRENDERABLE,
    PLAUSIBILITY_AUDIT_FIELDS,
    PlausibilityReport,
    wire_report,
)


def _report() -> PlausibilityReport:
    """Build a report containing every audit-only field."""
    return PlausibilityReport(
        status="ok",
        threshold=0.7,
        resolved_model="m",
        provider="p",
        usage={"input_tokens": 3},
        latency_ms=5,
        items={},
    )


def test_audit_fields_excluded() -> None:
    """Client dumps never include audit-only identity fields."""
    assert not PLAUSIBILITY_AUDIT_FIELDS.intersection(wire_report(_report(), mode="json"))


def test_other_fields_identical() -> None:
    """Client dumps otherwise retain the normal Pydantic serialization."""
    report = _report()
    expected = report.model_dump(mode="json", exclude=PLAUSIBILITY_AUDIT_FIELDS)
    assert wire_report(report, mode="json") == expected


def test_extra_exclude_is_widened() -> None:
    """Callers can exclude response-specific fields in addition to audit data."""
    assert "latency_ms" not in wire_report(_report(), mode="json", exclude={"latency_ms"})


def test_not_examined_reaches_the_client() -> None:
    """``not_examined`` is coverage data, not vendor data — it is NOT audit-only (FEAT-737)."""
    report = PlausibilityReport(status="ok", threshold=0.7, items={}, not_examined={"doc": NOT_EXAMINED_UNRENDERABLE})
    assert "not_examined" not in PLAUSIBILITY_AUDIT_FIELDS
    assert wire_report(report, mode="json")["not_examined"] == {"doc": "unrenderable_answer"}


def test_not_examined_defaults_empty() -> None:
    """A report built without coverage data carries an empty map, never ``None``."""
    assert PlausibilityReport(status="ok", threshold=0.7).not_examined == {}
