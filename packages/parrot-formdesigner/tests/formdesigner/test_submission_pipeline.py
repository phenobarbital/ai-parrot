"""Unit tests for SubmissionPipeline (FEAT-649 TASK-4222) — pipeline called directly with fakes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot_formdesigner.core.llm_validation import LLMValidationConfig, PlausibilityReport, PlausibilityVerdict
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.forwarder import ForwardResult
from parrot_formdesigner.services.plausibility import PlausibilityBlocked
from parrot_formdesigner.services.sinks.base import SinkUnavailableError
from parrot_formdesigner.services.submission_pipeline import (
    SubmissionPipeline,
    SubmitSinkError,
    ValidationFailed,
)
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator

_UID = "22222222-2222-2222-2222-222222222222"


def _form(*, llm: bool = False, required: bool = False, persistence: bool = False) -> FormSchema:
    kwargs: dict = {}
    if llm:
        kwargs["llm_validation"] = LLMValidationConfig(enabled=True)
    if persistence:
        kwargs["persistence"] = FormPersistenceConfig.model_validate(
            {"data": {"type": "postgres_table", "connection": "db", "schema_name": "s", "table": "t"}}
        )
    return FormSchema(
        form_uid=_UID,
        form_id="pipe_form",
        title="Pipe",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment", required=required)],
            )
        ],
        **kwargs,
    )


class _Checker:
    def __init__(self, report: PlausibilityReport | None = None, exc: Exception | None = None) -> None:
        self.calls = 0
        self.report = report or PlausibilityReport(
            status="ok",
            threshold=0.7,
            items={"comment": PlausibilityVerdict(plausible=False, confidence=0.1, reason="odd")},
        )
        self.exc = exc

    async def check(self, form, scalars, *, locale, fields=None):  # noqa: ANN001
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.report


def _submit_kwargs(**over) -> dict:
    kw = dict(
        tenant=None,
        user_id=None,
        locale="en",
        context=None,
        extra_data=None,
        auth_context=None,
        merge_session_id=None,
    )
    kw.update(over)
    return kw


@pytest.fixture
def pipeline_factory():
    def _make(**over):
        store = MagicMock(spec=FormSubmissionStorage)
        store.store = AsyncMock(return_value="x")
        partial = MagicMock()
        partial.delete = AsyncMock(return_value=True)
        params = dict(
            validator=FormValidator(),
            submission_storage=store,
            forwarder=None,
            partial_store=partial,
            plausibility=None,
            sink_factory=None,
        )
        params.update(over)
        return SubmissionPipeline(**params), store, partial

    return _make


class TestCommit:
    async def test_generic_store_called_once(self, pipeline_factory):
        pipe, store, _ = pipeline_factory()
        out = await pipe.submit(_form(), {"comment": "hi"}, **_submit_kwargs())
        assert out.stored_in == "generic"
        store.store.assert_awaited_once()

    async def test_sink_exclusive_never_generic(self, pipeline_factory):
        sink = MagicMock()
        sink.family = "tabular"
        sink.ensure_target = AsyncMock()
        sink.write = AsyncMock()
        factory = MagicMock()
        factory.get = AsyncMock(return_value=sink)
        pipe, store, _ = pipeline_factory(sink_factory=factory)
        out = await pipe.submit(_form(persistence=True), {"comment": "hi"}, **_submit_kwargs())
        assert out.stored_in == "sink"
        sink.write.assert_awaited_once()
        store.store.assert_not_called()

    async def test_sink_unavailable_maps_503(self, pipeline_factory):
        factory = MagicMock()
        factory.get = AsyncMock(side_effect=SinkUnavailableError("down"))
        pipe, store, _ = pipeline_factory(sink_factory=factory)
        with pytest.raises(SubmitSinkError) as ei:
            await pipe.submit(_form(persistence=True), {"comment": "hi"}, **_submit_kwargs())
        assert ei.value.status == 503
        assert ei.value.headers == {"Retry-After": "30"}
        store.store.assert_not_called()

    async def test_validation_failed_raises_and_stores_nothing(self, pipeline_factory):
        pipe, store, _ = pipeline_factory()
        with pytest.raises(ValidationFailed) as ei:
            await pipe.submit(_form(required=True), {}, **_submit_kwargs())
        assert "comment" in ei.value.errors
        store.store.assert_not_called()

    async def test_partial_cleanup_on_merge_session(self, pipeline_factory):
        pipe, _, partial = pipeline_factory()
        await pipe.submit(_form(), {"comment": "hi"}, **_submit_kwargs(merge_session_id="sess"))
        partial.delete.assert_awaited_once_with(_UID, "sess")

    async def test_forwarder_result_reported(self, pipeline_factory):
        from parrot_formdesigner.core.schema import SubmitAction

        form = _form()
        form.submit = SubmitAction(action_type="endpoint", action_ref="http://x")
        fwd = MagicMock()
        fwd.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=200, error=None))
        pipe, _, _ = pipeline_factory(forwarder=fwd)
        out = await pipe.submit(form, {"comment": "hi"}, **_submit_kwargs())
        assert out.forwarded is True and out.forward_status == 200


class TestPlausibility:
    async def test_disabled_form_no_check(self, pipeline_factory):
        checker = _Checker()
        pipe, _, _ = pipeline_factory(plausibility=checker)
        out = await pipe.submit(_form(llm=False), {"comment": "hi"}, **_submit_kwargs())
        assert checker.calls == 0 and out.plausibility is None

    async def test_report_in_context_and_envelope(self, pipeline_factory):
        checker = _Checker()
        pipe, store, _ = pipeline_factory(plausibility=checker)
        out = await pipe.submit(_form(llm=True), {"comment": "hi"}, **_submit_kwargs())
        assert checker.calls == 1 and out.plausibility is not None
        sub = store.store.await_args.args[0]
        assert sub.context["llm_validation"]["status"] == "ok"
        # Envelope rebuild (the validator keeps envelopes only from TASK-4223, so exercise it directly).
        env = {"answer": "hi", "source": "speech", "confidence": 0.9}
        data = pipe.attach_verdicts({"comment": env, "other": 1}, checker.report)
        assert data["comment"]["plausibility"]["plausible"] is False
        assert data["other"] == 1

    async def test_passed_report_not_rechecked(self, pipeline_factory):
        checker = _Checker()
        pipe, store, _ = pipeline_factory(plausibility=checker)
        report = PlausibilityReport(status="ok", threshold=0.7, items={})
        await pipe.submit(_form(llm=True), {"comment": "hi"}, plausibility=report, **_submit_kwargs())
        assert checker.calls == 0
        assert store.store.await_args.args[0].context["llm_validation"]["status"] == "ok"

    async def test_block_raises_nothing_stored(self, pipeline_factory):
        pipe, store, _ = pipeline_factory(plausibility=_Checker(exc=PlausibilityBlocked("llm down")))
        with pytest.raises(PlausibilityBlocked):
            await pipe.submit(_form(llm=True), {"comment": "hi"}, **_submit_kwargs())
        store.store.assert_not_called()

    async def test_low_confidence_still_commits(self, pipeline_factory):
        pipe, store, _ = pipeline_factory(plausibility=_Checker())
        out = await pipe.submit(_form(llm=True), {"comment": "hi"}, **_submit_kwargs())
        assert out.stored_in == "generic"
        store.store.assert_awaited_once()

    async def test_invalid_submission_costs_no_llm_call(self, pipeline_factory):
        checker = _Checker()
        pipe, _, _ = pipeline_factory(plausibility=checker)
        with pytest.raises(ValidationFailed):
            await pipe.submit(_form(llm=True, required=True), {}, **_submit_kwargs())
        assert checker.calls == 0


class TestPrepare:
    async def test_validate_without_flag_no_llm(self, pipeline_factory):
        checker = _Checker()
        pipe, _, _ = pipeline_factory(plausibility=checker)
        result, report = await pipe.validate(_form(llm=True), {"comment": "hi"}, locale="en", auth_context=None)
        assert result.is_valid and report is None and checker.calls == 0

    async def test_validate_with_flag_returns_report(self, pipeline_factory):
        checker = _Checker()
        pipe, _, _ = pipeline_factory(plausibility=checker)
        _, report = await pipe.validate(
            _form(llm=True), {"comment": "hi"}, locale="en", auth_context=None, llm_validation=True
        )
        assert report is not None and checker.calls == 1
