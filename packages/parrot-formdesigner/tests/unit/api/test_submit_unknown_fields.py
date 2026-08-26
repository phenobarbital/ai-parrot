"""Unit tests for the unknown-fields policy branch in submit_data
(FEAT-458, TASK-2436 — spec Modules 5 and 7).

Follows the mocked-handler pattern established by
``tests/unit/test_submit_path_branch.py`` (FEAT-457): registry and
validator are mocked/faked, no real DB or network I/O. ``dispatch`` is
left to run for real where possible (forms without an ``events`` config
resolve to a no-op ``EventResolution()``), and monkeypatched only where a
test needs to observe or intercept a specific lifecycle event.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import parrot_formdesigner.api.handlers as handlers_module
import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.events import EventResolution
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    SubmitAction,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.forwarder import ForwardResult, SubmissionForwarder
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_form(
    *, policy: str = "drop", with_endpoint: bool = False, real_visit_context_field: bool = False
) -> FormSchema:
    fields = [FormField(field_id="name", field_type=FieldType.TEXT, label="Name")]
    if real_visit_context_field:
        fields.append(FormField(field_id="visit_context", field_type=FieldType.TEXT, label="Visit Context"))
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[FormSection(section_id="s1", fields=fields)],
        unknown_fields=policy,
        submit=(
            SubmitAction(action_type="endpoint", action_ref="https://example.test/hook") if with_endpoint else None
        ),
    )


def _make_request(body: dict | None = None) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body or {"name": "Ana"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    return req


def _make_validation_result(*, sanitized: dict | None = None, extras: dict | None = None) -> ValidationResult:
    return ValidationResult(
        is_valid=True,
        errors={},
        sanitized_data=sanitized or {"name": "Ana"},
        extra_data=extras or {},
    )


def _make_handler(
    form: FormSchema,
    *,
    submission_storage=None,
    forwarder=None,
    validation_result: ValidationResult | None = None,
    use_real_validator: bool = False,
) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = FormAPIHandler(
        registry=registry,
        submission_storage=submission_storage,
        forwarder=forwarder,
    )
    if not use_real_validator:
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate = AsyncMock(return_value=validation_result or _make_validation_result())
    return handler


@pytest.fixture
def drop_form():
    return _make_form(policy="drop")


@pytest.fixture
def keep_form():
    return _make_form(policy="keep")


@pytest.fixture
def reject_form():
    return _make_form(policy="reject")


class TestDropPolicy:
    async def test_extras_discarded(self, drop_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(
            drop_form,
            submission_storage=storage,
            validation_result=_make_validation_result(extras={"junk": 1}),
        )
        resp = await handler.submit_data(_make_request({"name": "Ana", "junk": 1}))
        assert resp.status == 200
        stored_submission = storage.store.call_args.args[0]
        assert stored_submission.extra_data is None
        assert "junk" not in stored_submission.data

    async def test_logs_discarded_count(self, drop_form, caplog):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(
            drop_form,
            submission_storage=storage,
            validation_result=_make_validation_result(extras={"junk": 1}),
        )
        with caplog.at_level("DEBUG", logger="parrot_formdesigner.api.handlers"):
            await handler.submit_data(_make_request({"name": "Ana", "junk": 1}))
        assert "Discarded 1 undeclared field" in caplog.text


class TestKeepPolicy:
    async def test_persists_extras_and_keeps_data_pure(self, keep_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(
            keep_form,
            submission_storage=storage,
            validation_result=_make_validation_result(extras={"legacy_id": 42}),
        )
        resp = await handler.submit_data(_make_request({"name": "Ana", "legacy_id": 42}))
        assert resp.status == 200
        stored_submission = storage.store.call_args.args[0]
        assert stored_submission.extra_data == {"legacy_id": 42}
        assert "legacy_id" not in stored_submission.data

    async def test_no_extras_is_none(self, keep_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(keep_form, submission_storage=storage)
        await handler.submit_data(_make_request({"name": "Ana"}))
        stored_submission = storage.store.call_args.args[0]
        assert stored_submission.extra_data is None

    async def test_over_cap_rejected(self, keep_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        extras = {f"k{i}": i for i in range(257)}
        handler = _make_handler(
            keep_form,
            submission_storage=storage,
            validation_result=_make_validation_result(extras=extras),
        )
        resp = await handler.submit_data(_make_request({"name": "Ana", **extras}))
        assert resp.status == 422
        body_text = str(resp.body)
        assert "keys" in body_text.lower()
        storage.store.assert_not_called()

    async def test_at_cap_accepted(self, keep_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        extras = {f"k{i}": i for i in range(256)}
        handler = _make_handler(
            keep_form,
            submission_storage=storage,
            validation_result=_make_validation_result(extras=extras),
        )
        resp = await handler.submit_data(_make_request({"name": "Ana", **extras}))
        assert resp.status == 200


class TestRejectPolicy:
    async def test_extras_rejected_with_reserved_key(self, reject_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(
            reject_form,
            submission_storage=storage,
            validation_result=_make_validation_result(extras={"junk": 1, "other": 2}),
        )
        resp = await handler.submit_data(_make_request({"name": "Ana", "junk": 1, "other": 2}))
        assert resp.status == 422
        import json

        body = json.loads(resp.body)
        assert body["errors"]["__unknown__"] == ["junk", "other"]
        storage.store.assert_not_called()

    async def test_on_error_dispatched_first(self, reject_form, monkeypatch):
        events: list[str] = []

        async def spy_dispatch(event_name, **kwargs):
            events.append(event_name)
            return EventResolution()

        monkeypatch.setattr(handlers_module, "dispatch", spy_dispatch)
        handler = _make_handler(
            reject_form,
            validation_result=_make_validation_result(extras={"junk": 1}),
        )
        await handler.submit_data(_make_request({"name": "Ana", "junk": 1}))
        assert "onError" in events

    async def test_on_error_raising_handler_does_not_mask_422(self, reject_form, monkeypatch):
        async def raising_dispatch(event_name, **kwargs):
            if event_name == "onError":
                raise RuntimeError("onError handler itself blew up")
            return EventResolution()

        monkeypatch.setattr(handlers_module, "dispatch", raising_dispatch)
        handler = _make_handler(
            reject_form,
            validation_result=_make_validation_result(extras={"junk": 1}),
        )
        resp = await handler.submit_data(_make_request({"name": "Ana", "junk": 1}))
        assert resp.status == 422  # original status surfaced, not masked

    async def test_clean_payload_succeeds(self, reject_form):
        handler = _make_handler(reject_form)
        resp = await handler.submit_data(_make_request({"name": "Ana"}))
        assert resp.status == 200


class TestForwardAndNotify:
    async def test_forward_body_flat_merges_under_keep(self, keep_form):
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=200))
        form = _make_form(policy="keep", with_endpoint=True)
        handler = _make_handler(
            form,
            forwarder=forwarder,
            validation_result=_make_validation_result(extras={"legacy_id": 42}),
        )
        await handler.submit_data(_make_request({"name": "Ana", "legacy_id": 42}))
        forwarder.forward.assert_awaited_once()
        outbound = forwarder.forward.call_args.args[0]
        assert outbound == {"name": "Ana", "legacy_id": 42}

    async def test_forward_unchanged_under_drop(self):
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=200))
        form = _make_form(policy="drop", with_endpoint=True)
        handler = _make_handler(
            form,
            forwarder=forwarder,
            validation_result=_make_validation_result(extras={"junk": 1}),
        )
        await handler.submit_data(_make_request({"name": "Ana", "junk": 1}))
        outbound = forwarder.forward.call_args.args[0]
        assert outbound == {"name": "Ana"}

    async def test_on_after_submit_sees_merged_view_under_keep(self, keep_form):
        events: dict[str, dict] = {}

        async def spy_dispatch(event_name, **kwargs):
            if event_name == "onAfterSubmit":
                events["payload"] = kwargs.get("payload")
            return EventResolution()

        import parrot_formdesigner.api.handlers as hm

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(hm, "dispatch", spy_dispatch)
            handler = _make_handler(
                keep_form,
                validation_result=_make_validation_result(extras={"legacy_id": 42}),
            )
            await handler.submit_data(_make_request({"name": "Ana", "legacy_id": 42}))

        assert events["payload"] == {"name": "Ana", "legacy_id": 42}

    async def test_on_after_submit_unchanged_under_drop(self, drop_form):
        events: dict[str, dict] = {}

        async def spy_dispatch(event_name, **kwargs):
            if event_name == "onAfterSubmit":
                events["payload"] = kwargs.get("payload")
            return EventResolution()

        import parrot_formdesigner.api.handlers as hm

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(hm, "dispatch", spy_dispatch)
            handler = _make_handler(
                drop_form,
                validation_result=_make_validation_result(extras={"junk": 1}),
            )
            await handler.submit_data(_make_request({"name": "Ana", "junk": 1}))

        assert events["payload"] == {"name": "Ana"}


class TestOrderingWithRealValidator:
    """Uses the REAL FormValidator (not mocked) — the wiring under test
    (visit_context extraction, onBeforeSubmit) lives in submit_data itself,
    not in the validator, so this proves the two are composed correctly."""

    async def test_visit_context_not_captured_as_extra(self):
        form = _make_form(policy="keep")
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(form, submission_storage=storage, use_real_validator=True)
        await handler.submit_data(_make_request({"name": "Ana", "visit_context": {"store_groups": [1]}}))
        stored_submission = storage.store.call_args.args[0]
        assert stored_submission.extra_data is None

    async def test_visit_context_declared_field_is_not_extra(self):
        form = _make_form(policy="keep", real_visit_context_field=True)
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(form, submission_storage=storage, use_real_validator=True)
        await handler.submit_data(_make_request({"name": "Ana", "visit_context": "onsite"}))
        stored_submission = storage.store.call_args.args[0]
        assert stored_submission.extra_data is None
        assert stored_submission.data["visit_context"] == "onsite"

    async def test_extras_computed_after_on_before_submit(self, monkeypatch):
        """A hook replacing the payload with declared fields yields no extras."""

        async def replacing_dispatch(event_name, **kwargs):
            if event_name == "onBeforeSubmit":
                return EventResolution(payload={"name": "Replaced"})
            return EventResolution()

        monkeypatch.setattr(handlers_module, "dispatch", replacing_dispatch)
        form = _make_form(policy="keep")
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(form, submission_storage=storage, use_real_validator=True)
        await handler.submit_data(_make_request({"junk": 1}))
        stored_submission = storage.store.call_args.args[0]
        assert stored_submission.extra_data is None
