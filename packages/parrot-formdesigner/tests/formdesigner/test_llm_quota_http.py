"""Auth gate and LLM quota tests for the public form HTTP paths."""

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
from parrot_formdesigner.services.llm_quota import LLMQuota, QuotaDecision
from parrot_formdesigner.services.plausibility import PlausibilityBatch
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmissionStorage

_TENANT = "public-tenant"
_FORM_UID = "11111111-1111-1111-1111-111111111111"
_OK = [{"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "ok"}]


class ExhaustedQuota:
    """Quota backend that records keys and always denies the charge."""

    def __init__(self, retry_after_s: int = 30) -> None:
        self.calls: list[str] = []
        self.retry_after_s = retry_after_s

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        self.calls.append(key)
        return QuotaDecision(allowed=False, retry_after_s=self.retry_after_s)


class AllowingQuota:
    """Quota backend that records an allowed charge."""

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        return QuotaDecision(allowed=True)


class FakeLLM:
    """Minimal client returning a deterministic plausibility batch."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.batch = PlausibilityBatch.model_validate({"items": _OK})

    async def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        message = type("Message", (), {"structured_output": self.batch, "output": self.batch})
        return message()


def _form(config: LLMValidationConfig | None = None) -> FormSchema:
    return FormSchema(
        form_id="quota-form",
        title="Quota",
        tenant=_TENANT,
        sections=[
            FormSection(
                section_id="section",
                fields=[FormField(field_id="name", field_type=FieldType.TEXT, label="Name", required=True)],
            )
        ],
        is_public=True,
        llm_validation=config,
    )


def _request(body: dict, *, authenticated: bool = False) -> MagicMock:
    request = MagicMock(spec=web.Request)
    request.match_info = {"form_uid": _FORM_UID}
    request.query.get.side_effect = lambda key, default="": default
    # Production shape: request["session"] is always present, and None for anonymous callers.
    request.__contains__.side_effect = lambda key: key == "session"
    request.__getitem__.side_effect = lambda key: {"id": "user-1"} if authenticated and key == "session" else None
    request.remote = "192.0.2.10"
    request.get.side_effect = lambda key, default=None: (
        _TENANT if key == "tenant" else ({"id": "user-1"} if authenticated and key == "session" else default)
    )
    request.json = AsyncMock(return_value=body)
    return request


def _json(response: web.Response) -> dict:
    return json.loads(response.body)


def _handler(form: FormSchema, llm: FakeLLM | None = None) -> tuple[FormAPIHandler, MagicMock]:
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    storage = MagicMock(spec=FormSubmissionStorage)
    storage.store = AsyncMock(return_value="submission-1")
    handler = FormAPIHandler(registry=registry, client=llm, submission_storage=storage)
    return handler, storage


async def test_anonymous_validate_opt_in_is_skipped_without_an_llm_call() -> None:
    llm = FakeLLM()
    handler, _ = _handler(_form(LLMValidationConfig(enabled=True)), llm)

    response = await handler.validate(_request({"name": "Ann", "llm_validation": True}))

    payload = _json(response)
    assert response.status == 200
    assert payload["plausibility"] == {"status": "skipped", "reason": "unauthenticated_opt_in"}
    assert llm.calls == []


async def test_authenticated_validate_opt_in_is_charged_and_runs_once() -> None:
    llm = FakeLLM()
    handler, _ = _handler(_form(LLMValidationConfig(enabled=True)), llm)
    quota_backend = AllowingQuota()
    handler.llm_quota = LLMQuota(backend=quota_backend)

    response = await handler.validate(_request({"name": "Ann", "llm_validation": True}, authenticated=True))

    assert response.status == 200
    assert _json(response)["plausibility"]["status"] == "ok"
    assert len(llm.calls) == 1


async def test_authenticated_validate_returns_429_when_quota_is_exhausted() -> None:
    llm = FakeLLM()
    handler, _ = _handler(_form(LLMValidationConfig(enabled=True)), llm)
    handler.llm_quota = LLMQuota(backend=ExhaustedQuota(17))

    response = await handler.validate(_request({"name": "Ann", "llm_validation": True}, authenticated=True))

    assert response.status == 429
    assert response.headers["Retry-After"] == "17"
    assert llm.calls == []


@pytest.mark.parametrize("policy", ["review", "reject"])
async def test_submit_enforcing_policy_returns_429_and_stores_nothing(policy: str) -> None:
    llm = FakeLLM()
    handler, storage = _handler(_form(LLMValidationConfig(enabled=True, on_implausible=policy)), llm)
    handler.llm_quota = LLMQuota(backend=ExhaustedQuota())

    response = await handler.submit_data(_request({"name": "Ann"}))

    assert response.status == 429
    assert response.headers["Retry-After"] == "30"
    assert llm.calls == []
    storage.store.assert_not_called()


async def test_submit_annotate_stores_skipped_rate_limited_report() -> None:
    llm = FakeLLM()
    handler, storage = _handler(_form(LLMValidationConfig(enabled=True)), llm)
    handler.llm_quota = LLMQuota(backend=ExhaustedQuota())

    response = await handler.submit_data(_request({"name": "Ann"}))

    payload = _json(response)
    assert response.status == 200
    assert payload["plausibility"]["status"] == "skipped"
    assert payload["plausibility"]["reason"] == "rate_limited"
    assert payload["plausibility"]["threshold"] == 0.7
    assert storage.store.call_args.args[0].context["llm_validation"]["reason"] == "rate_limited"
    assert llm.calls == []


async def test_submit_disabled_form_does_not_charge_quota() -> None:
    llm = FakeLLM()
    handler, storage = _handler(_form(), llm)
    backend = ExhaustedQuota()
    handler.llm_quota = LLMQuota(backend=backend)

    response = await handler.submit_data(_request({"name": "Ann"}))

    assert response.status == 200
    assert backend.calls == []
    storage.store.assert_called_once()


async def test_submit_quota_key_contains_tenant_and_form_uid() -> None:
    handler, _ = _handler(_form(LLMValidationConfig(enabled=True)), FakeLLM())
    backend = ExhaustedQuota()
    handler.llm_quota = LLMQuota(backend=backend)

    await handler.submit_data(_request({"name": "Ann"}))

    assert backend.calls[0].startswith(f"{_TENANT}:{_FORM_UID}:")


async def test_submit_invalid_payload_does_not_charge_quota() -> None:
    """issue:eadd89b2242f — a 422 never reaches the LLM, so it must not burn quota."""
    handler, storage = _handler(_form(LLMValidationConfig(enabled=True, on_implausible="reject")), FakeLLM())
    backend = ExhaustedQuota()
    handler.llm_quota = LLMQuota(backend=backend)

    response = await handler.submit_data(_request({}))

    assert response.status == 422
    assert backend.calls == []
    storage.store.assert_not_called()


async def test_validate_invalid_payload_does_not_charge_quota() -> None:
    handler, _ = _handler(_form(LLMValidationConfig(enabled=True)), FakeLLM())
    backend = ExhaustedQuota()
    handler.llm_quota = LLMQuota(backend=backend)

    response = await handler.validate(_request({"llm_validation": True}, authenticated=True))

    assert response.status == 422
    assert backend.calls == []


def test_setup_form_api_publishes_default_llm_quota() -> None:
    app = web.Application()
    setup_form_api(app, FormRegistry())

    assert isinstance(app["llm_quota"], LLMQuota)


def test_setup_form_api_preserves_explicit_llm_quota() -> None:
    app = web.Application()
    quota = LLMQuota(enabled=False)
    setup_form_api(app, FormRegistry(), llm_quota=quota)

    assert app["llm_quota"] is quota
