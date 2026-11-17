"""FEAT-730 — audio WS maps SubmissionRejected to IOFailed."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot_formdesigner.audio.events import IOFailed, Submit
from parrot_formdesigner.services.submission_pipeline import SubmissionRejected

from .test_audio_ws_adapter import _boot, _form, _handler


@pytest.mark.parametrize(
    ("reason", "field_id", "code"),
    [
        ("form_closed", None, "FORM_CLOSED"),
        ("response_limit_reached", None, "RESPONSE_LIMIT_REACHED"),
        ("duplicate_response", "answer", "DUPLICATE_RESPONSE"),
    ],
)
async def test_audio_ws_rejection_io_failed(reason, field_id, code) -> None:
    pipeline = MagicMock()
    pipeline.submit = AsyncMock(side_effect=SubmissionRejected(reason, "refused", field_id=field_id))
    handler = _handler(_form("answer"), None, None, pipeline=pipeline)
    _, ctx = await _boot(handler, start={"submit_mode": "server"})
    result = await handler._do_submit(ctx, Submit(type="_submit", data={"answer": "value"}))
    assert isinstance(result, IOFailed)
    assert result.code == code
    assert result.code != "SUBMIT_FAILED"
