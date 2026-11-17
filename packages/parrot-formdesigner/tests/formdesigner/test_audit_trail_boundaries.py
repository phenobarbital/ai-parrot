"""FEAT-732 — boundaries: validate-only callers, audio parity, tiny cap, declared-check table."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import parrot_formdesigner
from parrot_formdesigner.audio.events import Submit, SubmitDone
from parrot_formdesigner.core.audit_trail import AuditDetail, AuditTrailConfig, CheckId
from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validation_trace import ValidationTraceCollector
from parrot_formdesigner.services.validators import FormValidator

from .test_audio_ws_adapter import _boot, _form, _handler
from .test_pipeline_validation_trace import _form as _trace_form
from .test_pipeline_validation_trace import _submit_kwargs

_ROOT = Path(parrot_formdesigner.__file__).parent
_VALIDATE_ONLY_CALLERS = ("renderers/telegram/router.py", "ui/telegram.py", "ui/handlers.py")


def _pipeline() -> tuple[SubmissionPipeline, MagicMock]:
    store = MagicMock(spec=FormSubmissionStorage)
    store.store = AsyncMock(return_value="x")
    partial = MagicMock()
    partial.delete = AsyncMock(return_value=True)
    pipe = SubmissionPipeline(
        validator=FormValidator(),
        submission_storage=store,
        forwarder=None,
        partial_store=partial,
        plausibility=None,
        sink_factory=None,
    )
    return pipe, store


def test_validate_only_callers_pass_no_trace() -> None:
    """AC20: Telegram / ui callers validate without a collector, so they persist no trace."""
    seen = 0
    for rel in _VALIDATE_ONLY_CALLERS:
        tree = ast.parse((_ROOT / rel).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "validate"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "validator"
            ):
                seen += 1
                assert "trace" not in {kw.arg for kw in node.keywords}, f"{rel} passes trace="
    assert seen >= 3


async def test_audio_submit_matches_http_trace_shape() -> None:
    """AC14: the audio handler's submit stores a trace shaped like the HTTP one, beside its own context."""
    pipe, store = _pipeline()
    handler = _handler(_form("answer"), None, None, pipeline=pipe)
    _, ctx = await _boot(handler, start={"submit_mode": "server"})

    audio_ctx = {"channel": "audio", "session_id": "s1", "locale": "en", "submission_id": None}
    result = await handler._do_submit(ctx, Submit(type="_submit", data={"answer": "value"}, context=audio_ctx))

    assert isinstance(result, SubmitDone)
    audio_context = store.store.await_args.args[0].context
    assert audio_context["channel"] == "audio"

    http_pipe, http_store = _pipeline()
    await http_pipe.submit(_trace_form(), {"comment": "hello"}, **_submit_kwargs())
    http_context = http_store.store.await_args.args[0].context

    assert set(audio_context["validation"]) == set(http_context["validation"])
    assert audio_context["validation"]["detail"] == "summary"


async def test_tiny_cap_truncates_but_submits() -> None:
    """A 1 KiB cap on a wide form still stores a truncated trace."""
    pipe, store = _pipeline()
    form = _trace_form(audit_trail=AuditTrailConfig(max_bytes=1024), wide=True)
    data = {f"field_{i:03d}": "abc" for i in range(200)}

    await pipe.submit(form, data, **_submit_kwargs())

    trace = store.store.await_args.args[0].context["validation"]
    assert trace["truncated"] is True
    assert len(json.dumps(trace, separators=(",", ":")).encode()) <= 1024


async def test_cap_failure_degrades_to_minimal_header(monkeypatch) -> None:
    """If cap_trace cannot fit the header the submission still succeeds with a minimal header."""
    pipe, store = _pipeline()

    def _boom(*args, **kwargs):
        raise ValueError("max_bytes is too small for the validation trace header")

    monkeypatch.setattr("parrot_formdesigner.services.submission_pipeline.cap_trace", _boom)

    await pipe.submit(_trace_form(), {"comment": "hello"}, **_submit_kwargs())

    trace = store.store.await_args.args[0].context["validation"]
    assert trace["truncated"] is True
    assert trace["fields"] == [] and trace["form_checks"] == []
    assert trace["omitted_fields"] == 1


async def test_declared_checks_match_recorded_checks() -> None:
    """Drift guard: _declared_checks lists exactly the checks a clean full-detail pass records."""
    field = FormField(
        field_id="code",
        field_type=FieldType.TEXT,
        label="code",
        required=True,
        constraints=FieldConstraints(min_length=1, max_length=9, pattern=r"^[A-Z]+$"),
    )
    form = FormSchema(form_id="d", title="D", sections=[FormSection(section_id="s", fields=[field])])
    validator = FormValidator()
    collector = ValidationTraceCollector(detail=AuditDetail.FULL, locale="en")

    result = await validator.validate(form, {"code": "ABC"}, trace=collector)

    recorded = {r.check for r in result.trace.fields[0].records} - {
        CheckId.RESOLUTION_VISIBLE,
        CheckId.RESOLUTION_REQUIRED,
    }
    assert recorded == {check for check, _ in validator._declared_checks(field)}
