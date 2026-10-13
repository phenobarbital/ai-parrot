"""HTTP plausibility wiring tests (FEAT-649, TASK-4224)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.api.routes import setup_form_api
from parrot_formdesigner.core.llm_validation import LLMValidationConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.plausibility import PlausibilityBatch
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline
from parrot_formdesigner.services.submissions import FormSubmissionStorage

_TENANT = "test-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"


class FakeLLM:
    """Records ask(); returns a PlausibilityBatch-shaped message or raises."""

    def __init__(self, items=None, exc: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self._batch = PlausibilityBatch.model_validate({"items": items or []})
        self._exc = exc

    async def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self._exc:
            raise self._exc
        return type("Msg", (), {"structured_output": self._batch, "output": self._batch})()


def _form(cfg: LLMValidationConfig | None = None) -> FormSchema:
    return FormSchema(
        form_id="plaus-form",
        title="Plaus",
        tenant=_TENANT,
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)],
            )
        ],
        llm_validation=cfg,
    )


def _request(body: dict) -> MagicMock:
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.__contains__ = lambda self, key: False
    req.json = AsyncMock(return_value=body)
    req.get = MagicMock(side_effect=lambda key, default=None: _TENANT if key == "tenant" else default)
    req.session = {"session": {"programs": [_TENANT]}}
    return req


@pytest.fixture
def make_handler():
    def _make(form: FormSchema, llm: FakeLLM | None = None):
        registry = MagicMock(spec=FormRegistry)
        registry.get = AsyncMock(return_value=form)
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock(return_value="sub-1")
        handler = FormAPIHandler(registry=registry, client=llm, submission_storage=storage)
        handler._get_llm_client = MagicMock(wraps=handler._get_llm_client)
        return handler, storage

    return _make


def _json(resp) -> dict:
    return json.loads(resp.body)


_OK = [{"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "ok"}]
_LOW = [{"field_id": "name", "plausible": False, "confidence": 0.1, "reason": "odd"}]


class TestValidateOptIn:
    async def test_no_flag_no_llm_call(self, make_handler):
        llm = FakeLLM(_OK)
        handler, _ = make_handler(_form(LLMValidationConfig(enabled=True)), llm)
        resp = await handler.validate(_request({"name": "Ann"}))
        assert resp.status == 200 and "plausibility" not in _json(resp)
        assert llm.calls == []
        handler._get_llm_client.assert_not_called()

    async def test_flag_returns_plausibility_block(self, make_handler):
        llm = FakeLLM(_OK)
        handler, _ = make_handler(_form(LLMValidationConfig(enabled=True)), llm)
        resp = await handler.validate(_request({"name": "Ann", "llm_validation": True}))
        body = _json(resp)
        assert resp.status == 200 and body["plausibility"]["status"] == "ok"
        assert "name" in body["plausibility"]["items"]
        assert len(llm.calls) == 1

    async def test_low_confidence_keeps_200(self, make_handler):
        handler, _ = make_handler(_form(LLMValidationConfig(enabled=True)), FakeLLM(_LOW))
        resp = await handler.validate(_request({"name": "Ann", "llm_validation": True}))
        assert resp.status == 200 and _json(resp)["is_valid"] is True

    async def test_flag_on_disabled_form_builds_no_client(self, make_handler):
        handler, _ = make_handler(_form(), FakeLLM(_OK))
        resp = await handler.validate(_request({"name": "Ann", "llm_validation": True}))
        assert resp.status == 200 and "plausibility" not in _json(resp)
        handler._get_llm_client.assert_not_called()


class TestSubmitPlausibility:
    async def test_response_and_context_llm_validation(self, make_handler):
        llm = FakeLLM(_OK)
        handler, storage = make_handler(_form(LLMValidationConfig(enabled=True)), llm)
        resp = await handler.submit_data(_request({"name": "Ann"}))
        body = _json(resp)
        assert resp.status == 200 and body["plausibility"]["status"] == "ok"
        stored = storage.store.call_args.args[0]
        assert stored.context["llm_validation"]["status"] == "ok"

    async def test_disabled_form_never_builds_client(self, make_handler):
        handler, _ = make_handler(_form(), FakeLLM(_OK))
        resp = await handler.submit_data(_request({"name": "Ann"}))
        body = _json(resp)
        assert resp.status == 200 and "plausibility" not in body
        assert set(body) == {"submission_id", "is_valid", "forwarded", "forward_status", "forward_error"}
        handler._get_llm_client.assert_not_called()


class TestBlockMode:
    async def test_block_unavailable_503_nothing_stored(self, make_handler):
        cfg = LLMValidationConfig(enabled=True, on_error="block")
        handler, storage = make_handler(_form(cfg), FakeLLM(exc=RuntimeError("down")))
        resp = await handler.submit_data(_request({"name": "Ann"}))
        assert resp.status == 503 and _json(resp)["code"] == "PLAUSIBILITY_UNAVAILABLE"
        storage.store.assert_not_called()

    async def test_skip_unavailable_200_skipped(self, make_handler):
        handler, storage = make_handler(_form(LLMValidationConfig(enabled=True)), FakeLLM(exc=RuntimeError("down")))
        resp = await handler.submit_data(_request({"name": "Ann"}))
        assert resp.status == 200 and _json(resp)["plausibility"]["status"] == "skipped"
        storage.store.assert_called_once()


class TestRoutes:
    def test_app_submission_pipeline_published(self):
        app = web.Application()
        setup_form_api(app, FormRegistry())
        assert isinstance(app["submission_pipeline"], SubmissionPipeline)
