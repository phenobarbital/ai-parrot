"""FEAT-730 — pipeline enforcement of public_access."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_formdesigner.core.events import EventResolution
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.submission_pipeline import SubmissionPipeline, SubmissionRejected
from parrot_formdesigner.services.submissions import DuplicateResponse, ResponseLimitReached
from parrot_formdesigner.services.validators import ValidationResult


def _form(public_access=None) -> FormSchema:
    return FormSchema(
        form_id="pub",
        title="Pub",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="email", field_type=FieldType.EMAIL, label="Email")],
            )
        ],
        public_access=public_access,
    )


def _pipeline(*, tenant_scoped: bool = False, with_storage: bool = True):
    validator = MagicMock()
    validator.validate = AsyncMock(
        return_value=ValidationResult(is_valid=True, errors={}, sanitized_data={"email": " A@x.com "})
    )
    storage = MagicMock()
    storage.store = AsyncMock(return_value="sid")
    storage.store_guarded = AsyncMock(return_value="sid")
    plausibility = MagicMock()
    plausibility.check = AsyncMock()
    dispatch = AsyncMock(return_value=EventResolution())
    pipe = SubmissionPipeline(
        validator=validator,
        submission_storage=storage if with_storage else None,
        forwarder=None,
        partial_store=None,
        plausibility=plausibility,
        dispatch_fn=dispatch,
        tenant_scoped_submissions=tenant_scoped,
    )
    return pipe, validator, storage, dispatch


async def _submit(pipe, form, tenant="acme"):
    return await pipe.submit(
        form,
        {"email": " A@x.com "},
        tenant=tenant,
        user_id=None,
        locale="en",
        context=None,
        extra_data=None,
        auth_context=None,
        merge_session_id=None,
    )


async def test_submit_closed_before_validation():
    pipe, validator, storage, dispatch = _pipeline()
    form = _form({"closes_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    with pytest.raises(SubmissionRejected) as ei:
        await _submit(pipe, form)
    assert ei.value.reason == "form_closed"
    validator.validate.assert_not_called()
    pipe.plausibility.check.assert_not_called()
    dispatch.assert_not_called()  # neither onBeforeSubmit nor onError
    storage.store.assert_not_called()
    storage.store_guarded.assert_not_called()


async def test_generic_store_receives_tenant():
    pipe, _, storage, _ = _pipeline(tenant_scoped=True)
    await _submit(pipe, _form())
    storage.store.assert_awaited_once()
    assert storage.store.await_args.kwargs == {"tenant": "acme"}
    assert storage.store.await_args.args[0].tenant == "acme"

    pipe, _, storage, _ = _pipeline(tenant_scoped=True)
    await _submit(pipe, _form({"max_responses": 3}))
    assert storage.store_guarded.await_args.kwargs["tenant"] == "acme"
    assert storage.store_guarded.await_args.kwargs["max_responses"] == 3


async def test_generic_store_flag_off_unchanged():
    pipe, _, storage, _ = _pipeline()
    await _submit(pipe, _form())
    storage.store.assert_awaited_once()
    assert storage.store.await_args.kwargs == {}
    assert storage.store.await_args.args[0].tenant is None

    pipe, _, storage, _ = _pipeline()
    await _submit(pipe, _form({"max_responses": 3}))
    assert storage.store_guarded.await_args.kwargs["tenant"] is None


async def test_guarded_receives_normalized_key():
    pipe, _, storage, _ = _pipeline()
    await _submit(pipe, _form({"unique_key_field": "email"}))
    kw = storage.store_guarded.await_args.kwargs
    assert kw["unique_key_field"] == "email"
    assert kw["unique_value"] == "A@x.com"
    storage.store.assert_not_called()


async def test_limit_maps_to_rejection():
    pipe, _, storage, dispatch = _pipeline()
    storage.store_guarded.side_effect = ResponseLimitReached()
    with pytest.raises(SubmissionRejected) as ei:
        await _submit(pipe, _form({"max_responses": 1}))
    assert ei.value.reason == "response_limit_reached"
    assert all(c.args[0] != "onError" for c in dispatch.await_args_list)


async def test_duplicate_maps_to_rejection():
    pipe, _, storage, dispatch = _pipeline()
    storage.store_guarded.side_effect = DuplicateResponse("email")
    with pytest.raises(SubmissionRejected) as ei:
        await _submit(pipe, _form({"unique_key_field": "email"}))
    assert ei.value.reason == "duplicate_response"
    assert ei.value.field_id == "email"
    assert all(c.args[0] != "onError" for c in dispatch.await_args_list)


async def test_counting_policy_without_storage_is_501():
    from parrot_formdesigner.services.submission_pipeline import SubmitSinkError

    pipe, *_ = _pipeline(with_storage=False)
    with pytest.raises(SubmitSinkError) as ei:
        await _submit(pipe, _form({"max_responses": 2}))
    assert ei.value.status == 501


async def test_outcome_carries_created_at():
    pipe, _, storage, _ = _pipeline()
    out = await _submit(pipe, _form())
    stored = storage.store.await_args.args[0]
    assert out.created_at == stored.created_at
    assert out.created_at.tzinfo is not None
