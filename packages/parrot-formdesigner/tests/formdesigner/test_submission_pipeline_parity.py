"""Golden parity suite for FormAPIHandler.submit_data (FEAT-649 TASK-4221).

Pins today's observable submit behaviour so the SubmissionPipeline extraction (TASK-4222/4224)
can be proven behaviour-preserving. Must pass before AND after the extraction, unchanged.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.events import (
    EventResolution,
    FormEventAbort,
    FormEventBinding,
    FormEventsConfig,
)
from parrot_formdesigner.core.partial import PartialFormData
from parrot_formdesigner.core.persistence import FormPersistenceConfig, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.event_registry import (
    _clear_event_registry_for_tests,
    register_form_event,
)
from parrot_formdesigner.services.forwarder import ForwardResult, SubmissionForwarder
from parrot_formdesigner.services.partial_saves import PartialSaveStore
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkNotCapableError,
    SinkTargetMismatchError,
    SinkUnavailableError,
)
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"
_RESPONSE_KEYS = {"submission_id", "is_valid", "forwarded", "forward_status", "forward_error"}
_SESSION = "sess-1"


@pytest.fixture(autouse=True)
def _clear_events():
    yield
    _clear_event_registry_for_tests()


def _make_request(body: dict | None = None, *, query: dict | None = None, session_id: str | None = None) -> MagicMock:
    """Mocked aiohttp request (pattern tests/unit/test_submit_path_branch.py)."""
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.method = "POST"
    req.headers = {}
    req.query = query or {}
    req.content_length = None
    nav_session = {"id": session_id} if session_id else None

    def _contains(key):
        return key == "session" and nav_session is not None

    def _getitem(key):
        if key == "session" and nav_session is not None:
            return nav_session
        raise KeyError(key)

    req.__contains__ = MagicMock(side_effect=_contains)
    req.__getitem__ = MagicMock(side_effect=_getitem)
    req.__setitem__ = MagicMock()
    req.json = AsyncMock(return_value=body if body is not None else {"comment": "great"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TENANT]}}
    return req


def _record_events(form_id: str, sink: list[str], *, abort_before: bool = False) -> FormEventsConfig:
    """Register recording handlers for the three submit events; return the binding config."""
    for event in ("onBeforeSubmit", "onError", "onAfterSubmit"):

        @register_form_event(f"{form_id}.{event}")
        async def _h(ctx, _event=event):  # noqa: ANN001
            sink.append(ctx.event)
            if abort_before and _event == "onBeforeSubmit":
                raise FormEventAbort(status_code=403, user_message="nope", reason="blocked")
            return EventResolution()

    return FormEventsConfig(
        onBeforeSubmit=FormEventBinding(handler_ref=f"{form_id}.onBeforeSubmit"),
        onError=FormEventBinding(handler_ref=f"{form_id}.onError"),
        onAfterSubmit=FormEventBinding(handler_ref=f"{form_id}.onAfterSubmit"),
    )


def _postgres_persistence() -> FormPersistenceConfig:
    return FormPersistenceConfig.model_validate(
        {"data": {"type": "postgres_table", "connection": "survey_db", "schema_name": "surveys", "table": "nps_2026"}}
    )


def _mongo_persistence() -> FormPersistenceConfig:
    return FormPersistenceConfig.model_validate(
        {"data": {"type": "asyncdb", "connection": "mongo_alias", "driver": "mongo", "collection": "responses"}}
    )


def _make_form(**overrides) -> FormSchema:
    params = dict(
        form_uid=_FORM_UID,
        form_id="parity_form",
        title="Parity Form",
        tenant=_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment"),
                    FormField(field_id="other", field_type=FieldType.TEXT, label="Other"),
                ],
            )
        ],
    )
    params.update(overrides)
    return FormSchema(**params)


class _FakeSink(AbstractSubmissionSink):
    def __init__(self, *, family: str = "tabular", raise_on: str | None = None, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._family = family
        self._raise_on = raise_on
        self._error = error
        self.written: list[dict] = []

    @property
    def capabilities(self):
        return frozenset({SinkCapability.WRITE, SinkCapability.PROVISION})

    @property
    def family(self) -> str:
        return self._family

    async def ensure_target(self, form):
        self.calls.append("ensure_target")
        if self._raise_on == "ensure_target":
            raise self._error

    async def write(self, submission, payload):
        self.calls.append("write")
        if self._raise_on == "write":
            raise self._error
        self.written.append(payload)
        return submission.submission_id


class _FakeSinkFactory:
    def __init__(self, sink: _FakeSink) -> None:
        self._sink = sink

    async def get(self, form, *, tenant):
        return self._sink


def _storage() -> MagicMock:
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock()
    return storage


def _vr(
    *, is_valid: bool = True, errors: dict | None = None, sanitized: dict | None = None, extra: dict | None = None
) -> ValidationResult:
    return ValidationResult(
        is_valid=is_valid,
        errors=errors or {},
        sanitized_data=sanitized if sanitized is not None else {"comment": "great"},
        extra_data=extra or {},
    )


def _make_handler(
    form: FormSchema,
    *,
    storage=None,
    sink_factory=None,
    forwarder=None,
    partial_store=None,
    validation: ValidationResult | None = None,
    real_validator: bool = False,
) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    handler = FormAPIHandler(
        registry=registry,
        submission_storage=storage,
        forwarder=forwarder,
        partial_store=partial_store,
        sink_factory=sink_factory,
    )
    if not real_validator:
        handler.validator = MagicMock(spec=FormValidator)
        handler.validator.validate = AsyncMock(return_value=validation or _vr())
    return handler


def _body(resp: web.Response) -> dict:
    return json.loads(resp.body)


class TestSinkExclusive:
    async def test_tabular_flatten_and_store_never_called(self):
        form = _make_form(persistence=_postgres_persistence())
        sink = _FakeSink(family="tabular")
        storage = _storage()
        handler = _make_handler(form, storage=storage, sink_factory=_FakeSinkFactory(sink))
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        assert sink.calls == ["ensure_target", "write"]
        storage.store.assert_not_awaited()
        row = sink.written[-1]
        assert "data" not in row
        assert row["comment"] == "great"

    async def test_document_family_uses_nest(self):
        form = _make_form(persistence=_mongo_persistence())
        sink = _FakeSink(family="document")
        storage = _storage()
        handler = _make_handler(form, storage=storage, sink_factory=_FakeSinkFactory(sink))
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        storage.store.assert_not_awaited()
        assert sink.written[-1]["data"]["comment"] == "great"


class TestGenericStorage:
    async def test_store_called_once_with_submission(self):
        form = _make_form(version="2.3")
        storage = _storage()
        handler = _make_handler(form, storage=storage, validation=_vr(sanitized={"comment": "clean"}))
        resp = await handler.submit_data(_make_request({"comment": "raw"}))
        assert resp.status == 200
        storage.store.assert_awaited_once()
        args, kwargs = storage.store.call_args
        assert kwargs == {}
        sub = args[0]
        assert sub.form_uid == form.form_uid
        assert sub.form_id == form.form_id
        assert sub.form_version == form.version
        assert sub.data == {"comment": "clean"}
        assert sub.is_valid is True
        assert sub.extra_data is None
        assert sub.submission_id == _body(resp)["submission_id"]


class TestSinkErrorMapping:
    @pytest.mark.parametrize(
        ("exc", "raise_on", "status"),
        [
            (SinkUnavailableError("down"), "write", 503),
            (SinkTargetMismatchError("changed"), "ensure_target", 422),
            (SinkNotCapableError("nope"), "write", 501),
        ],
    )
    async def test_status_mapping_and_nothing_persisted(self, exc, raise_on, status):
        events: list[str] = []
        form = _make_form(persistence=_postgres_persistence(), events=_record_events("parity_form", events))
        sink = _FakeSink(raise_on=raise_on, error=exc)
        storage = _storage()
        handler = _make_handler(form, storage=storage, sink_factory=_FakeSinkFactory(sink))
        resp = await handler.submit_data(_make_request())
        assert resp.status == status
        assert _body(resp) == {"error": str(exc)}
        if status == 503:
            assert resp.headers["Retry-After"] == "30"
        storage.store.assert_not_awaited()
        assert sink.written == []
        assert events == ["onBeforeSubmit", "onError"]

    async def test_unavailable_503_retry_after(self):
        form = _make_form(persistence=_postgres_persistence())
        sink = _FakeSink(raise_on="write", error=SinkUnavailableError("down"))
        handler = _make_handler(form, sink_factory=_FakeSinkFactory(sink))
        resp = await handler.submit_data(_make_request())
        assert resp.status == 503
        assert resp.headers["Retry-After"] == "30"


class TestLifecycleOrder:
    async def test_success_sequence(self):
        events: list[str] = []
        form = _make_form(events=_record_events("parity_form", events))
        handler = _make_handler(form, storage=_storage())
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        assert events == ["onBeforeSubmit", "onAfterSubmit"]

    async def test_validation_failure_sequence(self):
        events: list[str] = []
        form = _make_form(events=_record_events("parity_form", events))
        storage = _storage()
        handler = _make_handler(
            form, storage=storage, validation=_vr(is_valid=False, errors={"comment": ["required"]}, sanitized={})
        )
        resp = await handler.submit_data(_make_request())
        assert resp.status == 422
        assert _body(resp) == {"is_valid": False, "errors": {"comment": ["required"]}}
        assert events == ["onBeforeSubmit", "onError"]
        storage.store.assert_not_awaited()

    async def test_abort_not_routed_to_onerror(self):
        events: list[str] = []
        form = _make_form(events=_record_events("parity_form", events, abort_before=True))
        storage = _storage()
        handler = _make_handler(form, storage=storage)
        resp = await handler.submit_data(_make_request())
        assert resp.status == 403
        assert _body(resp) == {"error": "nope", "reason": "blocked"}
        assert events == ["onBeforeSubmit"]
        storage.store.assert_not_awaited()


def _endpoint_form() -> FormSchema:
    return _make_form(
        submit={"action_type": "endpoint", "action_ref": "https://example.test/hook", "method": "POST"},
    )


class TestForwarder:
    async def test_forward_called_and_reported(self):
        form = _endpoint_form()
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=201))
        handler = _make_handler(
            form, storage=_storage(), forwarder=forwarder, validation=_vr(sanitized={"comment": "x"})
        )
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        forwarder.forward.assert_awaited_once_with({"comment": "x"}, form.submit)
        body = _body(resp)
        assert body["forwarded"] is True
        assert body["forward_status"] == 201
        assert body["forward_error"] is None

    async def test_forward_failure_still_200(self):
        form = _endpoint_form()
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=False, status_code=502, error="bad gateway"))
        handler = _make_handler(form, storage=_storage(), forwarder=forwarder)
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        body = _body(resp)
        assert body["forwarded"] is False
        assert body["forward_status"] == 502
        assert body["forward_error"] == "bad gateway"


def _partial_store(form: FormSchema, cached: dict[str, str]) -> MagicMock:
    uid_of = {f.field_id: str(f.field_uid) for f in form.sections[0].fields}
    now = datetime.now(timezone.utc)
    partial = PartialFormData(
        form_id=str(form.form_uid),
        session_id=_SESSION,
        data={uid_of[k]: v for k, v in cached.items()},
        saved_at=now,
        expires_at=now + timedelta(hours=1),
    )
    store = MagicMock(spec=PartialSaveStore)
    store.get = AsyncMock(return_value=partial)
    store.delete = AsyncMock(return_value=True)
    return store


class TestPartialMergeCleanup:
    async def test_merge_submitted_wins_and_delete_on_success(self):
        form = _make_form()
        store = _partial_store(form, {"comment": "cached", "other": "from-cache"})
        handler = _make_handler(form, storage=_storage(), partial_store=store)
        req = _make_request({"comment": "submitted"}, query={"merge_partials": "true"}, session_id=_SESSION)
        resp = await handler.submit_data(req)
        assert resp.status == 200
        store.get.assert_awaited_once_with(str(form.form_uid), _SESSION)
        sent = handler.validator.validate.call_args.args[1]
        assert sent == {"comment": "submitted", "other": "from-cache"}
        store.delete.assert_awaited_once_with(str(form.form_uid), _SESSION)

    async def test_no_delete_on_422(self):
        form = _make_form()
        store = _partial_store(form, {"other": "from-cache"})
        handler = _make_handler(
            form, storage=_storage(), partial_store=store, validation=_vr(is_valid=False, errors={"comment": ["x"]})
        )
        req = _make_request({"comment": ""}, query={"merge_partials": "true"}, session_id=_SESSION)
        resp = await handler.submit_data(req)
        assert resp.status == 422
        store.delete.assert_not_awaited()

    async def test_no_merge_without_flag(self):
        form = _make_form()
        store = _partial_store(form, {"other": "from-cache"})
        handler = _make_handler(form, storage=_storage(), partial_store=store)
        resp = await handler.submit_data(_make_request(session_id=_SESSION))
        assert resp.status == 200
        store.get.assert_not_awaited()
        store.delete.assert_not_awaited()


class TestUnknownFields:
    async def test_reject_422_unknown(self):
        events: list[str] = []
        form = _make_form(unknown_fields="reject", events=_record_events("parity_form", events))
        storage = _storage()
        handler = _make_handler(form, storage=storage, real_validator=True)
        resp = await handler.submit_data(_make_request({"comment": "ok", "junk": 1}))
        assert resp.status == 422
        body = _body(resp)
        assert body["is_valid"] is False
        assert body["errors"] == {"__unknown__": ["junk"]}
        assert events == ["onBeforeSubmit", "onError"]
        storage.store.assert_not_awaited()

    async def test_keep_stores_extra_data_and_flat_merges_outbound(self):
        form = _endpoint_form().model_copy(update={"unknown_fields": "keep"})
        storage = _storage()
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=200))
        handler = _make_handler(form, storage=storage, forwarder=forwarder, real_validator=True)
        resp = await handler.submit_data(_make_request({"comment": "ok", "junk": 1}))
        assert resp.status == 200
        sub = storage.store.call_args.args[0]
        assert sub.extra_data == {"junk": 1}
        assert "junk" not in sub.data
        outbound = forwarder.forward.call_args.args[0]
        assert outbound["junk"] == 1
        assert outbound["comment"] == "ok"

    async def test_drop_discards(self):
        form = _endpoint_form().model_copy(update={"unknown_fields": "drop"})
        storage = _storage()
        forwarder = MagicMock(spec=SubmissionForwarder)
        forwarder.forward = AsyncMock(return_value=ForwardResult(success=True, status_code=200))
        handler = _make_handler(form, storage=storage, forwarder=forwarder, real_validator=True)
        resp = await handler.submit_data(_make_request({"comment": "ok", "junk": 1}))
        assert resp.status == 200
        sub = storage.store.call_args.args[0]
        assert sub.extra_data is None
        assert "junk" not in sub.data
        assert "junk" not in forwarder.forward.call_args.args[0]


class TestResponseShape:
    async def test_exact_keys(self):
        handler = _make_handler(_make_form(), storage=_storage())
        resp = await handler.submit_data(_make_request())
        assert resp.status == 200
        body = _body(resp)
        assert set(body) == _RESPONSE_KEYS
        uuid.UUID(body["submission_id"])
        assert body["is_valid"] is True
        assert body["forwarded"] is False
        assert body["forward_status"] is None
        assert body["forward_error"] is None


def _a2ui_body(answers: dict) -> dict:
    return {
        "version": "v1.0",
        "action": {
            "name": "form.submit",
            "surfaceId": f"form-{_FORM_UID}",
            "sourceComponentId": "root-submit",
            "timestamp": "2026-09-10T00:00:00Z",
            "context": {"form_uid": _FORM_UID},
            "dataModel": {"answers": answers},
        },
    }


def _a2ui_request(body: dict) -> MagicMock:
    req = _make_request(body)
    req.content_type = "application/json"
    req.content_length = len(json.dumps(body))
    return req


class TestA2UIBranch:
    async def test_confirmation_envelope(self):
        pytest.importorskip("parrot.outputs.a2ui")
        storage = _storage()
        handler = _make_handler(_make_form(), storage=storage)
        resp = await handler.submit_data(_a2ui_request(_a2ui_body({"comment": "great"})))
        assert resp.status == 200
        envelopes = _body(resp)["messages"]
        model = next(e["updateDataModel"] for e in envelopes if "updateDataModel" in e)
        assert model["path"] == "/submission"
        assert model["value"]["submission_id"] == storage.store.call_args.args[0].submission_id
        comps = next(e["updateComponents"] for e in envelopes if "updateComponents" in e)
        assert comps["components"][0]["id"] == "root-status"

    async def test_validation_errors_envelope(self):
        pytest.importorskip("parrot.outputs.a2ui")
        storage = _storage()
        handler = _make_handler(
            _make_form(), storage=storage, validation=_vr(is_valid=False, errors={"comment": ["Required."]})
        )
        resp = await handler.submit_data(_a2ui_request(_a2ui_body({"comment": ""})))
        assert resp.status == 422
        errs = [e for e in _body(resp)["messages"] if "error" in e]
        assert len(errs) == 1
        assert errs[0]["error"]["code"] == "VALIDATION_FAILED"
        assert errs[0]["error"]["path"] == "/answers/comment"
        storage.store.assert_not_awaited()
