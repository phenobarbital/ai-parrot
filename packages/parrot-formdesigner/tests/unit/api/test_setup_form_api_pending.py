"""FEAT-731 — setup_form_api wiring + sink-path clear."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot_formdesigner.api import setup_form_api
from parrot_formdesigner.api.render import _RENDERERS
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.services.sinks.base import SinkUnavailableError
from parrot_formdesigner.services.submissions import FormSubmissionStorage
from tests.unit.test_submit_path_branch import (
    _FakeSink,
    _FakeSinkFactory,
    _make_form,
    _make_handler,
    _make_request,
    _make_validation_result,
    _postgres_persistence,
)


@pytest.fixture(autouse=True)
def _reset_renderers():
    snapshot = dict(_RENDERERS)
    _RENDERERS.clear()
    yield
    _RENDERERS.clear()
    _RENDERERS.update(snapshot)


def test_setup_form_api_wires_pending():
    pending = MagicMock()
    storage = MagicMock(spec=FormSubmissionStorage)
    app = web.Application()
    setup_form_api(app, FormRegistry(), submission_storage=storage, pending_uploads=pending)
    assert app["form_pending_uploads"] is pending
    storage.attach_pending_uploads.assert_called_once_with(pending)

    # absent -> key published as None, nothing attached
    storage2 = MagicMock(spec=FormSubmissionStorage)
    app2 = web.Application()
    setup_form_api(app2, FormRegistry(), submission_storage=storage2)
    assert app2["form_pending_uploads"] is None
    storage2.attach_pending_uploads.assert_not_called()


def _sink_handler(sink: _FakeSink, pending):
    form = _make_form(persistence=_postgres_persistence())
    storage = MagicMock(spec=FormSubmissionStorage)
    storage._pending = pending
    handler = _make_handler(form, sink_factory=_FakeSinkFactory(sink), submission_storage=storage)
    ref = f"s3://b/{uuid.uuid4()}"
    handler.validator.validate = AsyncMock(
        return_value=_make_validation_result({"comment": {"blob_ref": ref}})
    )
    return handler, ref


async def test_sink_path_clears_after_write():
    pending = MagicMock()
    pending.clear = AsyncMock(return_value=1)
    sink = _FakeSink()
    handler, ref = _sink_handler(sink, pending)
    resp = await handler.submit_data(_make_request())
    assert resp.status < 300
    assert sink.calls == ["ensure_target", "write"]
    pending.clear.assert_awaited_once()
    assert set(pending.clear.await_args.args[0]) == {ref}

    # sink error -> no clear
    pending2 = MagicMock()
    pending2.clear = AsyncMock()
    handler2, _ = _sink_handler(_FakeSink(raise_on="write", error=SinkUnavailableError("down")), pending2)
    resp2 = await handler2.submit_data(_make_request())
    assert resp2.status == 503
    pending2.clear.assert_not_awaited()

    # clear failure is best-effort: submission still succeeds
    pending3 = MagicMock()
    pending3.clear = AsyncMock(side_effect=RuntimeError("db down"))
    handler3, _ = _sink_handler(_FakeSink(), pending3)
    assert (await handler3.submit_data(_make_request())).status < 300


def test_services_exports():
    import parrot_formdesigner.services as svc

    for name in (
        "PendingUploadStore",
        "PendingUploadReaper",
        "PendingUpload",
        "ReapResult",
        "iter_blob_refs",
        "DEFAULT_PUBLIC_FORM_TTL",
        "DEFAULT_TTL",
    ):
        assert name in svc.__all__
        assert hasattr(svc, name)
