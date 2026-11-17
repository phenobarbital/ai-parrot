"""Ledger a80ba017766e: the voice engine honours ``PlausibilityReport.not_examined`` (FEAT-737 follow-up).

Sessions are real. Merge tests use crafted reports; batching tests use the real checker with a fake LLM client.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest

from parrot_formdesigner.audio.engine import AudioFormSession
from parrot_formdesigner.audio.events import (
    AnswerText,
    Outbound,
    PlausibilityDone,
    ReviewConfirm,
    ReviewEdit,
    RunPlausibility,
    Submit,
)
from parrot_formdesigner.audio.models import Phase
from parrot_formdesigner.core.llm_validation import (
    NOT_EXAMINED_MAX_FIELDS,
    NOT_EXAMINED_UNRENDERABLE,
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
)
from parrot_formdesigner.core.voice import VoiceFormConfig
from parrot_formdesigner.services.plausibility import AnswerPlausibilityChecker, PlausibilityBlocked

from .test_audio_engine_review_resume import _advance, _answer_all, _form, _make, _start

CAP = NOT_EXAMINED_MAX_FIELDS
UNR = NOT_EXAMINED_UNRENDERABLE


def _rep(items: list[str], not_examined: dict[str, str] | None = None) -> PlausibilityReport:
    return PlausibilityReport(
        status="ok",
        threshold=0.7,
        items={k: PlausibilityVerdict(plausible=True, confidence=0.9, reason="r") for k in items},
        not_examined=not_examined or {},
    )


def _block_session():
    form = _form()
    form.llm_validation = LLMValidationConfig(enabled=True, on_error="block")
    s = _make(form)
    out = _answer_all(s)
    run = next(o for o in out if isinstance(o, RunPlausibility))
    assert set(run.fields) == {"name", "color", "agree"}
    return s


def _done(s, report):
    return s.handle(PlausibilityDone(type="_plausibility_done", report=report))


def _confirm(s):
    return s.handle(ReviewConfirm(type="review_confirm", confirmed=True))


def test_capped_fields_are_resubmitted_in_a_later_batch():
    s = _block_session()
    _done(s, _rep(["name"], {"color": CAP, "agree": CAP}))
    out = _confirm(s)
    assert not any(isinstance(o, Submit) for o in out)
    run = next(o for o in out if isinstance(o, RunPlausibility))
    assert set(run.fields) == {"color", "agree"}
    _done(s, _rep(["color", "agree"]))
    assert s.state.plausibility.not_examined == {}
    assert any(isinstance(o, Submit) for o in _confirm(s))


def test_unrenderable_field_never_loops_and_is_flagged_not_verifiable():
    s = _block_session()
    _done(s, _rep(["name", "color"], {"agree": UNR}))
    assert "agree" not in s._pl_unchecked
    assert s.state.plausibility.not_examined == {"agree": UNR}
    assert "agree" not in s.state.plausibility.items
    out = _confirm(s)  # would re-run the check forever if the field stayed pending
    assert not any(isinstance(o, RunPlausibility) for o in out)
    submit = next(o for o in out if isinstance(o, Submit))
    assert submit.context["llm_validation"]["not_examined"] == {"agree": UNR}


def test_delta_merge_keeps_unrequested_and_drops_now_examined():
    s = _block_session()
    _done(s, _rep(["name"], {"color": CAP, "agree": UNR}))
    # Edit "name": the delta batch only requests "name"; the new report knows nothing about the others.
    s.handle(ReviewEdit(type="review_edit", field_id="name"))
    s.handle(AnswerText(type="answer_text", field_id="name", value="Bea"))
    out = _advance(s)
    run = next(o for o in out if isinstance(o, RunPlausibility))
    assert set(run.fields) == {"name"}
    _done(s, _rep(["name"]))
    assert s.state.plausibility.not_examined == {"color": CAP, "agree": UNR}  # kept, not discarded
    # The capped field gets examined in the next batch -> drops out; the unrenderable entry stays.
    out = _confirm(s)
    run = next(o for o in out if isinstance(o, RunPlausibility))
    assert set(run.fields) == {"color"}
    _done(s, _rep(["color"]))
    assert s.state.plausibility.not_examined == {"agree": UNR}


def test_delta_new_report_wins_for_requested_fields():
    s = _block_session()
    _done(s, _rep(["name", "color"], {"agree": CAP}))
    s.handle(ReviewEdit(type="review_edit", field_id="agree"))
    s.handle(AnswerText(type="answer_text", field_id="agree", value="no"))
    _advance(s)
    _done(s, _rep([], {"agree": UNR}))  # capped before, now unrenderable
    assert s.state.plausibility.not_examined == {"agree": UNR}
    assert "agree" not in s._pl_unchecked


def _capped_session(
    on_error: Literal["skip", "block"], review: Literal["always", "never"], protocol: int
) -> tuple[AudioFormSession, list[Outbound]]:
    """Answer a form with three eligible fields and a one-field batch cap."""
    form = _form()
    form.llm_validation = LLMValidationConfig(enabled=True, on_error=on_error, max_fields=1)
    session = _make(form, cfg=VoiceFormConfig(max_questions=None, review=review))
    _start(session, protocol=protocol)
    _advance(session)
    for field_id, value in (("name", "Ana"), ("color", "r"), ("agree", "yes"), ("pw", "x")):
        session.handle(AnswerText(type="answer_text", field_id=field_id, value=value))
        output = _advance(session)
    return session, output


def _response(field_id: str) -> SimpleNamespace:
    """An attributed, plausible LLM response for one field."""
    return SimpleNamespace(
        model="test-model",
        structured_output={"items": [{"field_id": field_id, "plausible": True, "confidence": 0.9}]},
    )


def _run_batch(session: AudioFormSession, checker: AnswerPlausibilityChecker, output: list[Outbound]) -> list[Outbound]:
    """Execute the real checker, mapping blocked errors as the WebSocket adapter does."""
    assert not any(isinstance(item, Submit) for item in output)
    request = next(item for item in output if isinstance(item, RunPlausibility))
    try:
        report = asyncio.run(
            checker.check(
                session.form,
                {fid: answer.value for fid, answer in session.state.answers.items()},
                locale="es",
                fields=request.fields,
            )
        )
    except PlausibilityBlocked as exc:
        report = PlausibilityReport(status="blocked", reason=exc.reason, threshold=checker.config.threshold)
    return session.handle(PlausibilityDone(type="_plausibility_done", report=report))


@pytest.mark.parametrize("on_error", ["skip", "block"])
@pytest.mark.parametrize("review,protocol", [("always", 2), ("never", 2), ("always", 1)])
def test_real_checker_drains_capped_batches_before_submit(
    on_error: Literal["skip", "block"], review: Literal["always", "never"], protocol: int
) -> None:
    """Every eligible answer is checked once across all review and error policies."""
    session, output = _capped_session(on_error, review, protocol)
    ask = AsyncMock(side_effect=[_response(fid) for fid in ("name", "color", "agree")])
    checker = AnswerPlausibilityChecker(SimpleNamespace(ask=ask), config=session.form.llm_validation)
    for _ in range(3):
        output = _run_batch(session, checker, output)
        if review == "always" and protocol == 2:
            assert not any(isinstance(item, Submit) for item in output)
            output = _confirm(session)
    submit = next(item for item in output if isinstance(item, Submit))
    report = submit.context["llm_validation"]
    assert set(report["items"]) == {"name", "color", "agree"}
    assert report["not_examined"] == {}
    assert [[item["field_id"] for item in json.loads(call.args[0])["items"]] for call in ask.await_args_list] == [
        ["name"],
        ["color"],
        ["agree"],
    ]


@pytest.mark.parametrize("on_error", ["skip", "block"])
@pytest.mark.parametrize("review,protocol", [("always", 2), ("never", 2), ("always", 1)])
def test_later_batch_failure_preserves_error_policy(
    on_error: Literal["skip", "block"], review: Literal["always", "never"], protocol: int
) -> None:
    """A failed follow-up permits skip-mode submission and keeps block mode retryable."""
    session, output = _capped_session(on_error, review, protocol)
    ask = AsyncMock(side_effect=[_response("name"), RuntimeError("unavailable")])
    checker = AnswerPlausibilityChecker(SimpleNamespace(ask=ask), config=session.form.llm_validation)
    output = _run_batch(session, checker, output)
    if review == "always" and protocol == 2:
        output = _confirm(session)
    output = _run_batch(session, checker, output)
    assert ask.await_count == 2
    if on_error == "skip":
        if review == "always" and protocol == 2:
            output = _confirm(session)
        submit = next(item for item in output if isinstance(item, Submit))
        assert submit.context["llm_validation"]["status"] == "skipped"
        assert not any(isinstance(item, RunPlausibility) for item in output)
    else:
        assert not any(isinstance(item, Submit) for item in output)
        assert any(getattr(item, "code", None) == "PLAUSIBILITY_UNAVAILABLE" for item in output)
        if review == "always" and protocol == 2:
            retry = next(item for item in _confirm(session) if isinstance(item, RunPlausibility))
            assert retry.fields == {"color", "agree"}
        else:
            assert session.state.phase == Phase.ASKING
