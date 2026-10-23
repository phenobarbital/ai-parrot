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
        return type(
            "Msg",
            (),
            {"structured_output": self._batch, "output": self._batch, "model": "fake-model-1", "provider": "fake"},
        )()


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
    req.get = MagicMock(
        side_effect=lambda key, default=None: (
            _TENANT if key == "tenant" else ({"id": "user-1"} if key == "session" else default)
        )
    )
    req.session = {"session": {"programs": [_TENANT]}}
    return req


def _a2ui_request(form: FormSchema, answers: dict) -> MagicMock:
    """Build an A2UI validate request carrying the supplied answers."""
    body = {
        "version": "v1.0",
        "action": {
            "name": "form.validate",
            "surfaceId": f"form-{form.form_uid}",
            "sourceComponentId": "root-submit",
            "timestamp": "2026-10-22T00:00:00Z",
            "context": {"form_uid": str(form.form_uid)},
            "dataModel": {"answers": answers},
        },
    }
    request = _request(body)
    request.content_type = "application/json"
    request.content_length = len(json.dumps(body))
    return request


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


class TestEnforcementPolicy:
    """FEAT-728 — the plausibility gate on HTTP and A2UI."""

    async def test_annotate_low_confidence_still_200(self, make_handler):
        """Regression: the default annotate policy preserves current behaviour."""
        handler, storage = make_handler(_form(LLMValidationConfig(enabled=True)), FakeLLM(_LOW))

        response = await handler.submit_data(_request({"name": "Ann"}))

        assert response.status == 200
        assert _json(response)["plausibility"]["items"]["name"]["plausible"] is False
        storage.store.assert_awaited_once()

    async def test_review_422_then_ack_200(self, make_handler):
        config = LLMValidationConfig(enabled=True, on_implausible="review")
        handler, storage = make_handler(_form(config), FakeLLM(_LOW))

        blocked = await handler.submit_data(_request({"name": "Ann"}))
        blocked_body = _json(blocked)
        assert blocked.status == 422
        assert blocked_body["code"] == "PLAUSIBILITY_REVIEW"
        assert blocked_body["errors"] == {"name": ["odd"]}
        storage.store.assert_not_awaited()

        accepted = await handler.submit_data(_request({"name": "Ann", "plausibility_ack": True}))
        assert accepted.status == 200
        stored = storage.store.call_args.args[0]
        assert stored.context["llm_validation"]["acknowledged"] is True

    async def test_reject_422_even_with_ack(self, make_handler):
        config = LLMValidationConfig(enabled=True, on_implausible="reject")
        handler, storage = make_handler(_form(config), FakeLLM(_LOW))

        for body in ({"name": "Ann"}, {"name": "Ann", "plausibility_ack": True}):
            response = await handler.submit_data(_request(body))
            assert response.status == 422
            assert _json(response)["code"] == "PLAUSIBILITY_REJECTED"
        storage.store.assert_not_awaited()

    async def test_ack_query_flag_accepted(self, make_handler):
        config = LLMValidationConfig(enabled=True, on_implausible="review")
        handler, storage = make_handler(_form(config), FakeLLM(_LOW))
        request = _request({"name": "Ann"})
        request.query.get.side_effect = lambda key, default="": "true" if key == "plausibility_ack" else default

        response = await handler.submit_data(request)

        assert response.status == 200
        storage.store.assert_awaited_once()

    async def test_ack_not_reported_as_unknown_field(self, make_handler):
        config = LLMValidationConfig(enabled=True, on_implausible="review")
        form = _form(config).model_copy(update={"unknown_fields": "reject"})
        handler, storage = make_handler(form, FakeLLM(_LOW))

        response = await handler.submit_data(_request({"name": "Ann", "plausibility_ack": True}))

        assert response.status == 200
        stored = storage.store.call_args.args[0]
        assert stored.extra_data is None
        assert stored.data == {"name": "Ann"}

    async def test_validate_dry_run_matches_submit(self, make_handler):
        config = LLMValidationConfig(enabled=True, on_implausible="review")
        handler, storage = make_handler(_form(config), FakeLLM(_LOW))

        dry_run = await handler.validate(_request({"name": "Ann", "llm_validation": True}))
        commit = await handler.submit_data(_request({"name": "Ann"}))

        dry_run_body = _json(dry_run)
        commit_body = _json(commit)
        assert dry_run.status == commit.status == 422
        assert dry_run_body["code"] == commit_body["code"] == "PLAUSIBILITY_REVIEW"
        assert dry_run_body["errors"] == commit_body["errors"] == {"name": ["odd"]}
        storage.store.assert_not_awaited()


    async def test_validate_a2ui_review_envelopes(self, make_handler):
        pytest.importorskip("parrot.outputs.a2ui")
        config = LLMValidationConfig(enabled=True, on_implausible="review")
        form = _form(config)
        handler, _ = make_handler(form, FakeLLM(_LOW))

        response = await handler.validate(_a2ui_request(form, {"name": "Ann", "llm_validation": True}))

        assert response.status == 422
        envelopes = _json(response)["messages"]
        errors = [envelope["error"] for envelope in envelopes if "error" in envelope]
        assert len(errors) == 1
        assert errors[0]["path"] == "/answers/name"
        update = next(envelope["updateDataModel"] for envelope in envelopes if "updateDataModel" in envelope)
        assert update["path"] == "/errors"


class TestAuditFieldsStayOffTheWire:
    """FEAT-732 R10 — persisted, never sent to the form client."""

    async def test_submit_200_omits_identity_but_storage_keeps_it(self, make_handler):
        handler, storage = make_handler(_form(LLMValidationConfig(enabled=True)), FakeLLM(_OK))

        response = await handler.submit_data(_request({"name": "Ann"}))

        assert response.status == 200
        assert not {"resolved_model", "provider", "usage"}.intersection(_json(response)["plausibility"])
        stored = storage.store.call_args.args[0]
        assert stored.context["llm_validation"]["resolved_model"] == "fake-model-1"

    async def test_validate_omits_identity(self, make_handler):
        handler, _ = make_handler(_form(LLMValidationConfig(enabled=True)), FakeLLM(_OK))

        response = await handler.validate(_request({"name": "Ann", "llm_validation": True}))

        assert response.status == 200
        assert not {"resolved_model", "provider", "usage"}.intersection(_json(response)["plausibility"])

    async def test_review_422_omits_identity(self, make_handler):
        config = LLMValidationConfig(enabled=True, on_implausible="review")
        handler, _ = make_handler(_form(config), FakeLLM(_LOW))

        response = await handler.submit_data(_request({"name": "Ann"}))

        assert response.status == 422
        assert not {"resolved_model", "provider", "usage"}.intersection(_json(response)["plausibility"])


class TestRoutes:
    def test_app_submission_pipeline_published(self):
        app = web.Application()
        setup_form_api(app, FormRegistry())
        assert isinstance(app["submission_pipeline"], SubmissionPipeline)
