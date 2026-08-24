"""Unit tests for the submit-path persistence branch (FEAT-457, TASK-2428).

All dependencies (registry, validator, sink_factory, submission_storage)
are mocked/faked — no real DB or filesystem I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import parrot_formdesigner.api.handlers as handlers_module
import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.core.persistence import FormPersistenceConfig, SinkCapability
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.sinks.base import (
    AbstractSubmissionSink,
    SinkTargetMismatchError,
    SinkUnavailableError,
)
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from parrot_formdesigner.services.validators import FormValidator, ValidationResult

_TEST_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _make_form(*, persistence: FormPersistenceConfig | None = None) -> FormSchema:
    return FormSchema(
        form_id="test-form",
        title="Test Form",
        tenant=_TEST_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="comment", field_type=FieldType.TEXT, label="Comment")],
            )
        ],
        persistence=persistence,
    )


def _postgres_persistence() -> FormPersistenceConfig:
    return FormPersistenceConfig.model_validate(
        {
            "data": {
                "type": "postgres_table",
                "connection": "survey_db",
                "schema_name": "surveys",
                "table": "nps_2026",
            }
        }
    )


def _mongo_persistence() -> FormPersistenceConfig:
    return FormPersistenceConfig.model_validate(
        {
            "data": {
                "type": "asyncdb",
                "connection": "mongo_alias",
                "driver": "mongo",
                "collection": "responses",
            }
        }
    )


def _make_request(body: dict | None = None) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body or {"comment": "great"})
    req.get = MagicMock(side_effect=lambda key, default=None: _TEST_TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TEST_TENANT]}}
    return req


class _FakeSink(AbstractSubmissionSink):
    def __init__(
        self,
        *,
        family: str = "tabular",
        capabilities: frozenset[SinkCapability] | None = None,
        raise_on: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._family = family
        self._capabilities = capabilities or frozenset({SinkCapability.WRITE, SinkCapability.PROVISION})
        self._raise_on = raise_on
        self._error = error
        self.written: list[dict] = []

    @property
    def capabilities(self):
        return self._capabilities

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


def _make_validation_result(data: dict | None = None) -> ValidationResult:
    return ValidationResult(is_valid=True, errors={}, sanitized_data=data or {"comment": "great"})


def _make_handler(
    form: FormSchema,
    *,
    sink_factory=None,
    submission_storage=None,
) -> FormAPIHandler:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)

    handler = FormAPIHandler(
        registry=registry,
        submission_storage=submission_storage,
        sink_factory=sink_factory,
    )
    handler.validator = MagicMock(spec=FormValidator)
    handler.validator.validate = AsyncMock(return_value=_make_validation_result())
    return handler


@pytest.fixture
def autonomous_form():
    return _make_form(persistence=_postgres_persistence())


@pytest.fixture
def plain_form():
    return _make_form()


@pytest.fixture
def mongo_form():
    return _make_form(persistence=_mongo_persistence())


class TestExclusivity:
    async def test_generic_storage_not_called(self, autonomous_form):
        sink = _FakeSink()
        handler = _make_handler(
            autonomous_form,
            sink_factory=_FakeSinkFactory(sink),
            submission_storage=MagicMock(spec=FormSubmissionStorage),
        )
        handler._submission_storage.store = AsyncMock()
        await handler.submit_data(_make_request())
        handler._submission_storage.store.assert_not_called()

    async def test_sink_called_in_order(self, autonomous_form):
        sink = _FakeSink()
        handler = _make_handler(autonomous_form, sink_factory=_FakeSinkFactory(sink))
        await handler.submit_data(_make_request())
        assert sink.calls == ["ensure_target", "write"]

    async def test_plain_form_uses_generic_storage(self, plain_form):
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(plain_form, submission_storage=storage)
        await handler.submit_data(_make_request())
        storage.store.assert_awaited_once()


class TestStatusMapping:
    async def test_unavailable_is_503_with_retry_after(self, autonomous_form):
        sink = _FakeSink(raise_on="write", error=SinkUnavailableError("down"))
        handler = _make_handler(autonomous_form, sink_factory=_FakeSinkFactory(sink))
        resp = await handler.submit_data(_make_request())
        assert resp.status == 503
        assert "Retry-After" in resp.headers

    async def test_nothing_persisted_on_503(self, autonomous_form):
        sink = _FakeSink(raise_on="write", error=SinkUnavailableError("down"))
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock()
        handler = _make_handler(autonomous_form, sink_factory=_FakeSinkFactory(sink), submission_storage=storage)
        await handler.submit_data(_make_request())
        storage.store.assert_not_called()

    async def test_mismatch_is_422(self, autonomous_form):
        sink = _FakeSink(
            raise_on="ensure_target",
            error=SinkTargetMismatchError("coordinates changed"),
        )
        handler = _make_handler(autonomous_form, sink_factory=_FakeSinkFactory(sink))
        resp = await handler.submit_data(_make_request())
        assert resp.status == 422

    async def test_on_error_dispatched_and_raising_handler_does_not_mask(self, autonomous_form, monkeypatch):
        sink = _FakeSink(raise_on="write", error=SinkUnavailableError("down"))
        handler = _make_handler(autonomous_form, sink_factory=_FakeSinkFactory(sink))

        called = {"count": 0}

        async def raising_dispatch(event_name, **kwargs):
            if event_name == "onError":
                called["count"] += 1
                raise RuntimeError("onError handler itself blew up")
            return MagicMock(payload=None, user_message=None)

        monkeypatch.setattr(handlers_module, "dispatch", raising_dispatch)
        resp = await handler.submit_data(_make_request())
        assert resp.status == 503  # original error surfaced, not masked
        assert called["count"] == 1


class TestPayloadFamily:
    async def test_document_sink_gets_nested(self, mongo_form):
        sink = _FakeSink(family="document")
        handler = _make_handler(mongo_form, sink_factory=_FakeSinkFactory(sink))
        await handler.submit_data(_make_request())
        assert "data" in sink.written[-1]

    async def test_tabular_sink_gets_flat_row(self, autonomous_form):
        sink = _FakeSink(family="tabular")
        handler = _make_handler(autonomous_form, sink_factory=_FakeSinkFactory(sink))
        await handler.submit_data(_make_request())
        assert "data" not in sink.written[-1]
        assert "comment" in sink.written[-1]
