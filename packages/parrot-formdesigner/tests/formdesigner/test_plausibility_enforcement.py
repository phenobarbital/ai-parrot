"""Pipeline enforcement-gate tests (FEAT-728, TASK-4624)."""

from __future__ import annotations

from typing import Any

import pytest
from parrot_formdesigner.core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.submission_pipeline import (
    ImplausibleSubmission,
    SubmissionPipeline,
    ValidationFailed,
)
from parrot_formdesigner.services.validators import ValidationResult


def _form(policy: str = "annotate", *, enabled: bool = True, **overrides: Any) -> FormSchema:
    """Build a one-field form carrying the requested plausibility policy."""
    params: dict[str, Any] = {
        "form_id": "plaus-form",
        "title": "Plaus",
        "tenant": "test-tenant",
        "sections": [
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)],
            )
        ],
        "llm_validation": LLMValidationConfig(enabled=enabled, on_implausible=policy),
    }
    params.update(overrides)
    return FormSchema(**params)


def _report(
    *, plausible: bool = False, confidence: float = 0.1, threshold: float = 0.7, reason: str = "odd"
) -> PlausibilityReport:
    """Build an ``ok`` report for the form's one eligible field."""
    return PlausibilityReport(
        status="ok",
        threshold=threshold,
        items={"name": PlausibilityVerdict(plausible=plausible, confidence=confidence, reason=reason)},
    )


class _Validator:
    """Minimal validator double returning one configured result."""

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        self.calls = 0

    async def validate(self, *args: Any, **kwargs: Any) -> ValidationResult:
        self.calls += 1
        return self.result


class _Checker:
    """Minimal plausibility-checker double that records calls."""

    def __init__(self, report: PlausibilityReport) -> None:
        self.report = report
        self.calls = 0

    async def check(self, *args: Any, **kwargs: Any) -> PlausibilityReport:
        self.calls += 1
        return self.report


class _Storage:
    """In-memory storage double used to inspect committed submissions."""

    def __init__(self) -> None:
        self.submissions: list[Any] = []

    async def store(self, submission: Any) -> None:
        self.submissions.append(submission)


class _SinkFactory:
    """Sink factory double that records whether the gate reached persistence."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def get(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


class _Forwarder:
    """Forwarder double that records whether the gate reached outbound I/O."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def forward(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


class _Resolution:
    """No-op lifecycle response carrying no payload replacement."""

    payload = None
    user_message = None


def _valid_result() -> ValidationResult:
    """Return the deterministic validation success used by submit tests."""
    return ValidationResult(is_valid=True, errors={}, sanitized_data={"name": "Ann"}, extra_data={})


def _pipeline(
    *,
    result: ValidationResult | None = None,
    storage: _Storage | None = None,
    checker: _Checker | None = None,
    events: list[str] | None = None,
    forwarder: _Forwarder | None = None,
    sink_factory: _SinkFactory | None = None,
) -> SubmissionPipeline:
    """Build a pipeline whose lifecycle dispatcher records event names."""
    recorded_events = events if events is not None else []

    async def _dispatch(event: str, **kwargs: Any) -> _Resolution:
        recorded_events.append(event)
        return _Resolution()

    return SubmissionPipeline(
        validator=_Validator(result or _valid_result()),
        submission_storage=storage,
        forwarder=forwarder,
        partial_store=None,
        plausibility=checker,
        sink_factory=sink_factory,
        dispatch_fn=_dispatch,
    )


async def _submit(
    pipeline: SubmissionPipeline,
    form: FormSchema,
    *,
    report: PlausibilityReport | None = None,
    ack: bool = False,
) -> Any:
    """Submit one valid payload through the shared pipeline."""
    return await pipeline.submit(
        form,
        {"name": "Ann"},
        tenant="test-tenant",
        user_id=None,
        locale="en",
        context=None,
        extra_data=None,
        auth_context=None,
        merge_session_id=None,
        plausibility_ack=ack,
        plausibility=report,
    )


class TestGateFor:
    """gate_for() is pure: these need no storage and no LLM."""

    def test_annotate_always_passes(self) -> None:
        assert _pipeline().gate_for(_form("annotate"), _report()) is None

    def test_review_without_ack_returns_review_code(self) -> None:
        gate = _pipeline().gate_for(_form("review"), _report())
        assert gate is not None
        assert gate.code == "PLAUSIBILITY_REVIEW"
        assert gate.errors == {"name": ["odd"]}

    def test_review_with_ack_passes(self) -> None:
        assert _pipeline().gate_for(_form("review"), _report(), ack=True) is None

    def test_reject_ignores_ack(self) -> None:
        gate = _pipeline().gate_for(_form("reject"), _report(), ack=True)
        assert gate is not None
        assert gate.code == "PLAUSIBILITY_REJECTED"

    def test_none_report_passes(self) -> None:
        assert _pipeline().gate_for(_form("reject"), None) is None

    def test_unflagged_report_passes(self) -> None:
        assert _pipeline().gate_for(_form("reject"), _report(plausible=True, confidence=1.0)) is None

    def test_missing_llm_validation_block_is_annotate(self) -> None:
        form = _form()
        form.llm_validation = None
        assert _pipeline().gate_for(form, _report()) is None

    def test_errors_fall_back_to_default_message(self) -> None:
        gate = _pipeline().gate_for(_form("review"), _report(reason=""))
        assert gate is not None
        assert gate.errors == {"name": ["This answer does not appear to answer the question."]}

    def test_not_a_validation_failed_subclass(self) -> None:
        assert not issubclass(ImplausibleSubmission, ValidationFailed)


class TestSubmitGate:
    """The raise site: nothing may be written."""

    async def test_reject_stores_nothing(self) -> None:
        storage = _Storage()
        sink_factory = _SinkFactory()
        forwarder = _Forwarder()
        events: list[str] = []
        form = _form(
            "reject",
            persistence={
                "data": {
                    "type": "postgres_table",
                    "connection": "survey_db",
                    "schema_name": "surveys",
                    "table": "responses",
                }
            },
            submit={"action_type": "endpoint", "action_ref": "https://example.test/hook", "method": "POST"},
        )
        pipeline = _pipeline(storage=storage, events=events, forwarder=forwarder, sink_factory=sink_factory)
        with pytest.raises(ImplausibleSubmission):
            await _submit(pipeline, form, report=_report())
        assert storage.submissions == []
        assert sink_factory.calls == []
        assert forwarder.calls == []
        assert events == ["onBeforeSubmit", "onError"]

    async def test_reject_dispatches_on_error(self) -> None:
        events: list[str] = []
        with pytest.raises(ImplausibleSubmission):
            await _submit(_pipeline(events=events), _form("reject"), report=_report())
        assert events == ["onBeforeSubmit", "onError"]

    async def test_review_does_not_dispatch_on_error(self) -> None:
        events: list[str] = []
        with pytest.raises(ImplausibleSubmission):
            await _submit(_pipeline(events=events), _form("review"), report=_report())
        assert events == ["onBeforeSubmit"]

    async def test_ack_records_acknowledged_in_context(self) -> None:
        storage = _Storage()
        await _submit(_pipeline(storage=storage), _form("review"), report=_report(), ack=True)
        assert storage.submissions[0].context["llm_validation"]["acknowledged"] is True

    async def test_annotate_still_stores_with_verdicts(self) -> None:
        storage = _Storage()
        await _submit(_pipeline(storage=storage), _form("annotate"), report=_report())
        assert storage.submissions[0].context["llm_validation"]["items"]["name"]["plausible"] is False

    async def test_gate_runs_after_deterministic_422(self) -> None:
        invalid = ValidationResult(is_valid=False, errors={"name": ["required"]}, sanitized_data={}, extra_data={})
        checker = _Checker(_report())
        with pytest.raises(ValidationFailed):
            await _submit(_pipeline(result=invalid, checker=checker), _form("reject"))
        assert checker.calls == 0
