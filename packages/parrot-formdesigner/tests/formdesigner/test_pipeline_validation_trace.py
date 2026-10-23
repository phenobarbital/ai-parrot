"""Validation audit-trail persistence tests for ``SubmissionPipeline`` (FEAT-732)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.core.audit_trail import AuditTrailConfig
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.llm_validation import PlausibilityReport
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.sinks.mapper import flatten_submission, nest_submission
from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline
from parrot_formdesigner.services.submissions import FormSubmission, FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator

_UID = "22222222-2222-2222-2222-222222222222"


def _form(
    *,
    audit_trail: AuditTrailConfig | None = None,
    wide: bool = False,
) -> FormSchema:
    fields = (
        [
            FormField(
                field_id=f"field_{index:03d}",
                field_type=FieldType.TEXT,
                label=f"Field {index}",
                required=True,
                constraints=FieldConstraints(min_length=1, max_length=10, pattern="^[a-z]+$"),
            )
            for index in range(200)
        ]
        if wide
        else [FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")]
    )
    return FormSchema(
        form_uid=_UID,
        form_id="trace_form",
        version="2.3",
        title="Trace",
        sections=[FormSection(section_id="s1", fields=fields)],
        audit_trail=audit_trail,
    )


def _submit_kwargs(**over: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "tenant": None,
        "user_id": None,
        "locale": "en",
        "context": None,
        "extra_data": None,
        "auth_context": None,
        "merge_session_id": None,
    }
    kwargs.update(over)
    return kwargs


@pytest.fixture
def pipeline_factory():
    """Build a pipeline backed by an async storage double."""

    def _make(**over: object) -> tuple[SubmissionPipeline, MagicMock, MagicMock]:
        store = MagicMock(spec=FormSubmissionStorage)
        store.store = AsyncMock(return_value="x")
        partial = MagicMock()
        partial.delete = AsyncMock(return_value=True)
        params: dict[str, object] = {
            "validator": FormValidator(),
            "submission_storage": store,
            "forwarder": None,
            "partial_store": partial,
            "plausibility": None,
            "sink_factory": None,
        }
        params.update(over)
        return SubmissionPipeline(**params), store, partial

    return _make


async def test_submit_persists_validation_trace(pipeline_factory) -> None:
    pipe, store, _ = pipeline_factory()

    await pipe.submit(_form(), {"comment": "hello"}, **_submit_kwargs())

    trace = store.store.await_args.args[0].context["validation"]
    assert trace["trace_schema"] == 1
    assert trace["detail"] == "summary"
    assert trace["schema_fingerprint"].startswith("sha256:")
    assert trace["ruleset_version"]
    assert trace["form_version"] == "2.3"
    assert trace["checks_run"] > 0
    assert [field["field_id"] for field in trace["fields"]] == ["comment"]


async def test_submit_audit_off_writes_nothing(pipeline_factory) -> None:
    pipe, store, _ = pipeline_factory()
    original_context = {"source": "existing", "nested": {"unchanged": True}}

    await pipe.submit(
        _form(audit_trail=AuditTrailConfig(detail="off")),
        {"comment": "hello"},
        **_submit_kwargs(context=original_context),
    )

    stored_context = store.store.await_args.args[0].context
    assert stored_context == original_context
    assert "validation" not in stored_context


async def test_cap_applied_before_context_merge(pipeline_factory) -> None:
    pipe, store, _ = pipeline_factory()
    form = _form(audit_trail=AuditTrailConfig(max_bytes=1024), wide=True)
    answers = {field.field_id: "valid" for field in form.sections[0].fields}
    plausibility = PlausibilityReport(
        status="ok",
        threshold=0.7,
        model="requested-model",
        resolved_model="resolved-model",
        provider="test-provider",
        usage={"input_tokens": 123, "output_tokens": 45},
    )

    await pipe.submit(form, answers, plausibility=plausibility, **_submit_kwargs())

    context = store.store.await_args.args[0].context
    assert context["validation"]["truncated"] is True
    assert context["llm_validation"] == plausibility.model_dump(mode="json")


async def test_audio_shaped_context_keeps_both_keys(pipeline_factory) -> None:
    pipe, store, _ = pipeline_factory()
    llm_validation = {"status": "ok", "model": "audio-model", "items": {}}

    await pipe.submit(
        _form(),
        {"comment": "hello"},
        **_submit_kwargs(context={"llm_validation": llm_validation}),
    )

    context = store.store.await_args.args[0].context
    assert context["llm_validation"] == llm_validation
    assert context["validation"]["detail"] == "summary"


def test_trace_reaches_sink_payloads() -> None:
    trace = {"trace_schema": 1, "detail": "summary", "checks_run": 3}
    form = _form()
    submission = FormSubmission(
        submission_id="submission-1",
        form_uid=form.form_uid,
        form_id=form.form_id,
        form_version=form.version,
        data={"comment": "hello"},
        is_valid=True,
        created_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
        context={"validation": trace},
    )

    assert flatten_submission(form, submission)["context"]["validation"] == trace
    assert nest_submission(form, submission)["context"]["validation"] == trace


def test_trace_survives_storage_row_roundtrip() -> None:
    trace_context = {"validation": {"trace_schema": 1, "detail": "summary", "checks_run": 3}}
    form = _form()
    submission = FormSubmission(
        submission_id="submission-1",
        form_uid=form.form_uid,
        form_id=form.form_id,
        form_version=form.version,
        data={"comment": "hello"},
        is_valid=True,
        created_at=datetime(2026, 10, 23, tzinfo=timezone.utc),
        context=trace_context,
    )
    row = submission.model_dump()
    row["data"] = json.dumps(submission.data)
    row["context"] = json.dumps(trace_context)

    restored = FormSubmissionStorage._row_to_submission(row)

    assert restored.context == trace_context


async def test_prepare_step_builds_no_trace(pipeline_factory) -> None:
    pipe, _, _ = pipeline_factory()

    result, plausibility = await pipe.validate(
        _form(),
        {"comment": "hello"},
        locale="en",
        auth_context=None,
    )

    assert result.trace is None
    assert plausibility is None
