"""FEAT-653 TASK-4252 — engine LLM refine hand-off."""

from __future__ import annotations

import pytest

from parrot_formdesigner.audio.events import (
    AnswerAccepted,
    AnswerRejected,
    ConfirmAnswer,
    ConfirmRequest,
    RefineValue,
    ValueRefined,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice import VoiceFormConfig

from .test_audio_engine_postprocess import _build, _f, _tr


def _cfg(**kw) -> VoiceFormConfig:
    return VoiceFormConfig(max_questions=None, llm_refine_values=True, **kw)


def _vr(
    req: RefineValue, status: str = "ok", value: str | None = None, confidence: float | None = None
) -> ValueRefined:
    return ValueRefined(
        type="_value_refined",
        field_id=req.field_id,
        request_id=req.request_id,
        status=status,
        value=value,
        confidence=confidence,
    )


def _refine(out: list) -> RefineValue:
    return next(o for o in out if isinstance(o, RefineValue))


def test_refine_emitted_and_llm_never_upgrades_to_accept() -> None:
    """Product decision 2: rules confirm/rejected + LLM -> at most a confirm carrying the refined value."""
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    out = s.handle(_tr("email", "john at gmail"))
    req = _refine(out)
    assert req.candidate == "john@gmail" and req.field_type == "email" and req.today == "2026-10-12"
    assert sum(isinstance(o, RefineValue) for o in out) == 1 and "email" not in s.state.answers
    out = s.handle(_vr(req, value="john@gmail.com", confidence=0.99))
    assert not any(isinstance(o, AnswerAccepted) for o in out) and "email" not in s.state.answers
    cr = next(o for o in out if isinstance(o, ConfirmRequest))
    assert cr.value == "john@gmail.com" and cr.refined_by == "llm"
    s.handle(ConfirmAnswer(type="confirm_answer", field_id="email", confirmed=True))
    ans = s.state.answers["email"]
    assert ans.value == "john@gmail.com" and ans.normalized_by == "llm" and ans.llm_confidence == 0.99
    assert ans.raw_transcript == "john at gmail"


def test_rules_accepted_stays_accepted_with_high_confidence_llm() -> None:
    s = _build([_f("n", FieldType.NUMBER)], cfg=_cfg())
    req = _refine(s.handle(_tr("n", "twenty five")))
    out = s.handle(_vr(req, value="25", confidence=0.95))
    assert next(o for o in out if isinstance(o, AnswerAccepted)).value == 25


def test_low_llm_confidence_confirms() -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    req = _refine(s.handle(_tr("email", "john at gmail")))
    cr = next(o for o in s.handle(_vr(req, value="john@gmail.com", confidence=0.3)) if isinstance(o, ConfirmRequest))
    assert cr.value == "john@gmail.com" and cr.refined_by == "llm"
    s.handle(ConfirmAnswer(type="confirm_answer", field_id="email", confirmed=True))
    assert s.state.answers["email"].normalized_by == "llm" and s.state.answers["email"].llm_confidence == 0.3


def test_llm_never_overrides_low_stt() -> None:
    s = _build([_f("n", FieldType.NUMBER)], cfg=_cfg())
    req = _refine(s.handle(_tr("n", "twenty five", confidence=0.1)))
    assert any(isinstance(o, ConfirmRequest) for o in s.handle(_vr(req, value="25", confidence=0.99)))


def test_llm_never_overrides_confirm_always() -> None:
    s = _build([_f("n", FieldType.NUMBER, meta={"voice": {"confirm": "always"}})], cfg=_cfg())
    req = _refine(s.handle(_tr("n", "twenty five")))
    assert any(isinstance(o, ConfirmRequest) for o in s.handle(_vr(req, value="25", confidence=0.99)))


@pytest.mark.parametrize("status,value", [("failed", None), ("unavailable", None), ("ok", "not an email")])
def test_fallback_to_rules(status: str, value: str | None) -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    req = _refine(s.handle(_tr("email", "john at gmail")))
    out = s.handle(_vr(req, status=status, value=value, confidence=0.9))
    assert next(o for o in out if isinstance(o, AnswerRejected)).code == "INVALID_EMAIL"  # rules result was rejected


def test_fallback_keeps_accepted_rules_value() -> None:
    s = _build([_f("n", FieldType.NUMBER)], cfg=_cfg())
    req = _refine(s.handle(_tr("n", "twenty five")))
    out = s.handle(_vr(req, status="failed"))
    assert next(o for o in out if isinstance(o, AnswerAccepted)).value == 25
    assert s.state.answers["n"].normalized_by == "rules"


def test_stale_reply_ignored() -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    req = _refine(s.handle(_tr("email", "john at gmail")))
    stale = req.model_copy(update={"request_id": "other"})
    assert s.handle(_vr(stale, value="x@y.io", confidence=0.99)) == []
    # the real reply is still honoured, and a duplicate afterwards is dropped
    assert any(isinstance(o, ConfirmRequest) for o in s.handle(_vr(req, value="x@y.io", confidence=0.99)))
    assert s.handle(_vr(req, value="z@y.io", confidence=0.99)) == []


def test_reply_without_inflight_refine_ignored() -> None:
    s = _build([_f("email", FieldType.EMAIL)], cfg=_cfg())
    ghost = ValueRefined(type="_value_refined", field_id="email", request_id="x", status="ok", value="a@b.io")
    assert s.handle(ghost) == []


def test_text_never_refined() -> None:
    s = _build([_f("name", FieldType.TEXT, meta={"voice": {"llm_refine": True}})], cfg=_cfg())
    assert not any(isinstance(o, RefineValue) for o in s.handle(_tr("name", "en Manuel")))


def test_sensitive_never_refined() -> None:
    s = _build([_f("e", FieldType.EMAIL, meta={"voice": {"sensitive": True}})], cfg=_cfg())
    out = s.handle(_tr("e", "john at gmail"))
    assert not any(isinstance(o, RefineValue) for o in out)
    rej = next(o for o in out if isinstance(o, AnswerRejected))
    assert rej.value is None


def test_field_opt_out_and_opt_in() -> None:
    off = _build([_f("p", FieldType.PHONE, meta={"voice": {"llm_refine": False}})], cfg=_cfg())
    assert not any(isinstance(o, RefineValue) for o in off.handle(_tr("p", "five five five oh one two three")))
    on = _build([_f("p", FieldType.PHONE, meta={"voice": {"llm_refine": True}})])
    assert any(isinstance(o, RefineValue) for o in on.handle(_tr("p", "five five five oh one two three")))


def test_default_config_never_refines() -> None:
    s = _build([_f("p", FieldType.PHONE)])
    assert not any(isinstance(o, RefineValue) for o in s.handle(_tr("p", "five five five oh one two three")))
