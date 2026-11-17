"""Audio channel enforcement policy parity (FEAT-728, TASK-4628)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from parrot_formdesigner.api.audio_ws import AudioFormWSHandler
from parrot_formdesigner.audio.events import IOFailed, Submit, SubmitDone
from parrot_formdesigner.core.llm_validation import LLMValidationConfig, PlausibilityReport, PlausibilityVerdict
from parrot_formdesigner.services.plausibility import PlausibilityBlocked
from parrot_formdesigner.services.submission_pipeline import ImplausibleSubmission

from .test_audio_ws_adapter import _boot, _form, _handler


def _report() -> PlausibilityReport:
    return PlausibilityReport(
        status="ok",
        threshold=0.7,
        items={"answer": PlausibilityVerdict(plausible=False, confidence=0.1, reason="odd")},
    )


async def _submit(handler: AudioFormWSHandler, ctx):
    return await handler._do_submit(ctx, Submit(type="_submit", data={"answer": "value"}))


class TestAudioReviewPolicy:
    async def test_review_confirm_still_submits(self) -> None:
        """A flagged answer confirmed in REVIEW is stored with the plausibility acknowledgement."""
        stored: list[dict] = []

        async def submit(*args, **kwargs):
            stored.append(kwargs)
            return SimpleNamespace(submission_id="sub-review", stored_in="sink", forwarded=False)

        pipeline = MagicMock()
        pipeline.submit = AsyncMock(side_effect=submit)
        form = _form("answer", llm_validation=LLMValidationConfig(enabled=True, on_implausible="review"))
        handler = _handler(form, None, None, pipeline=pipeline)
        _, ctx = await _boot(handler, start={"submit_mode": "server"})
        result = await _submit(handler, ctx)
        assert isinstance(result, SubmitDone)
        assert stored and stored[0]["plausibility_ack"] is True

    async def test_annotate_unchanged(self) -> None:
        """The default annotate policy continues to store a flagged answer."""
        stored: list[dict] = []

        async def submit(*args, **kwargs):
            stored.append(kwargs)
            return SimpleNamespace(submission_id="sub-annotate", stored_in="sink", forwarded=False)

        pipeline = MagicMock()
        pipeline.submit = AsyncMock(side_effect=submit)
        handler = _handler(_form("answer"), None, None, pipeline=pipeline)
        _, ctx = await _boot(handler, start={"submit_mode": "server"})
        result = await _submit(handler, ctx)
        assert isinstance(result, SubmitDone)
        assert len(stored) == 1


class TestAudioRejectPolicy:
    async def test_reject_surfaces_io_failed_with_code(self) -> None:
        """Reject reaches the user as PLAUSIBILITY_REJECTED, not SUBMIT_FAILED."""
        pipeline = MagicMock()
        pipeline.submit = AsyncMock(
            side_effect=ImplausibleSubmission(policy="reject", fields=["answer"], report=_report())
        )
        handler = _handler(
            _form("answer", llm_validation=LLMValidationConfig(enabled=True, on_implausible="reject")),
            None,
            None,
            pipeline=pipeline,
        )
        _, ctx = await _boot(handler, start={"submit_mode": "server"})
        result = await _submit(handler, ctx)
        assert isinstance(result, IOFailed)
        assert result.code == "PLAUSIBILITY_REJECTED"

    async def test_reject_stores_nothing(self) -> None:
        """A reject refusal does not reach the submission sink."""
        stored: list[dict] = []

        async def submit(*args, **kwargs):
            raise ImplausibleSubmission(policy="reject", fields=["answer"], report=_report())

        pipeline = MagicMock()
        pipeline.submit = AsyncMock(side_effect=submit)
        handler = _handler(
            _form("answer", llm_validation=LLMValidationConfig(enabled=True, on_implausible="reject")),
            None,
            None,
            pipeline=pipeline,
        )
        _, ctx = await _boot(handler, start={"submit_mode": "server"})
        result = await _submit(handler, ctx)
        assert isinstance(result, IOFailed)
        assert result.code == "PLAUSIBILITY_REJECTED"
        assert stored == []

    async def test_plausibility_unavailable_path_unchanged(self) -> None:
        """LLM unavailability remains PLAUSIBILITY_UNAVAILABLE and is not caught as reject."""
        pipeline = MagicMock()
        pipeline.submit = AsyncMock(side_effect=PlausibilityBlocked("llm down"))
        handler = _handler(
            _form("answer", llm_validation=LLMValidationConfig(enabled=True, on_error="block")),
            None,
            None,
            pipeline=pipeline,
        )
        _, ctx = await _boot(handler, start={"submit_mode": "server"})
        result = await _submit(handler, ctx)
        assert isinstance(result, IOFailed)
        assert result.code == "PLAUSIBILITY_UNAVAILABLE"
