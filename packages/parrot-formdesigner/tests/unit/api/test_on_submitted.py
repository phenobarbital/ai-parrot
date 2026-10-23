"""FEAT-730 — on_submitted host hook."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.handlers import FormAPIHandler
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.submissions import FormSubmissionStorage

from .test_public_form_controls_http import _TENANT, _form, _json, _request


def _handler(form, on_submitted, *, with_storage: bool = True):
    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    storage = None
    if with_storage:
        storage = MagicMock(spec=FormSubmissionStorage)
        storage.store = AsyncMock(return_value="sub-1")
    return FormAPIHandler(registry=registry, submission_storage=storage, on_submitted=on_submitted)


async def test_on_submitted_called_once():
    cb = AsyncMock()
    form = _form(is_public=True)
    resp = await _handler(form, cb).submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 200
    cb.assert_awaited_once()
    event = cb.await_args.args[0]
    assert event.submission_id == _json(resp)["submission_id"]
    assert event.form_uid == form.form_uid and event.form_id == form.form_id
    assert event.form_version == form.version and event.tenant == _TENANT
    assert event.is_public is True and event.created_at.tzinfo is not None
    assert not hasattr(event, "anonymous")
    assert set(type(event).model_fields) == {
        "submission_id", "form_uid", "form_id", "form_version", "tenant", "is_public", "created_at",
    }


async def test_on_submitted_is_public_false_for_private_form():
    cb = AsyncMock()
    resp = await _handler(_form(is_public=False), cb).submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 200
    assert cb.await_args.args[0].is_public is False


async def test_on_submitted_not_called_on_409():
    cb = AsyncMock()
    closed = _form({"closes_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    resp = await _handler(closed, cb).submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 409
    cb.assert_not_called()


async def test_on_submitted_not_called_when_nothing_stored():
    cb = AsyncMock()
    resp = await _handler(_form(), cb, with_storage=False).submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 200
    cb.assert_not_called()


async def test_on_submitted_error_swallowed(caplog):
    cb = AsyncMock(side_effect=RuntimeError("boom"))
    with caplog.at_level(logging.WARNING):
        resp = await _handler(_form(), cb).submit_data(_request({"email": "a@x.com"}))
    assert resp.status == 200
    cb.assert_awaited_once()
    assert any("on_submitted hook failed" in r.getMessage() for r in caplog.records)


def test_event_importable_from_api():
    from parrot_formdesigner.api import SubmittedCallback, SubmittedEvent  # noqa: F401
