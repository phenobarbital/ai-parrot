"""Ledger a80ba017766e: the voice engine honours ``PlausibilityReport.not_examined`` (FEAT-737 follow-up).

The session is real; only the plausibility checker (an LLM boundary) is faked, by handing crafted reports in.
"""

from __future__ import annotations

from parrot_formdesigner.audio.events import (
    AnswerText,
    PlausibilityDone,
    ReviewConfirm,
    ReviewEdit,
    RunPlausibility,
    Submit,
)
from parrot_formdesigner.core.llm_validation import (
    NOT_EXAMINED_MAX_FIELDS,
    NOT_EXAMINED_UNRENDERABLE,
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
)

from .test_audio_engine_review_resume import _advance, _answer_all, _form, _make

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
