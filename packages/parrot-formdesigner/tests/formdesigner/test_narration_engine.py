"""Tests for the deterministic Narrator (FEAT-649 TASK-4214)."""

import uuid

import pytest
from jinja2 import UndefinedError

from parrot_formdesigner.audio.models import AudioQuestion, ReviewItemData
from parrot_formdesigner.audio.narration import NARRATION_KEYS, Narrator, render_author_prompt
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig

CTX = {
    "label": "Name",
    "required": True,
    "prompt": "P",
    "hint": "H",
    "count": 2,
    "ordinal": 1,
    "n": 1,
    "answer": "A",
    "title": "T",
    "value": "V",
    "position": 1,
    "total": 3,
    "flagged": False,
}


def _q(**kw):
    base = dict(index=0, field_id="f", field_uid=uuid.uuid4(), field_type="text", label="Name")
    base.update(kw)
    return AudioQuestion(**base)


@pytest.mark.parametrize("locale", ["en", "es"])
def test_narration_conformance_all_locales(locale):
    n = Narrator(locale)
    for key in NARRATION_KEYS:
        assert key in n._templates, key
        assert n.render(key, **CTX)


def test_fallback_es_mx_to_es_to_en(tmp_path):
    for loc, body in (("en", "a: EN-A\n  b: EN-B"), ("es", "a: ES-A")):
        d = tmp_path / loc
        d.mkdir()
        lines = "templates:\n" + "\n".join("  " + x.strip() for x in body.split("\n")) + "\n"
        (d / "narration.yaml").write_text(lines, encoding="utf-8")
    n = Narrator("es-MX", templates_dir=tmp_path)
    assert n._templates["a"] == "ES-A"
    assert n._templates["b"] == "EN-B"


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        Narrator("en").render("nope")


def test_narrator_traversal_locale_falls_back_to_en():
    """A traversal-shaped locale is filtered by locale_chain and loads the ``en`` templates."""
    n = Narrator("../../x")
    assert n._templates
    assert n.render("no_match")


def test_narrator_guard_raises_on_escaping_candidate(monkeypatch):
    """Defense in depth: a candidate escaping the templates root fails closed."""
    monkeypatch.setattr("parrot_formdesigner.audio.narration.engine.locale_chain", lambda loc: ["../escape"])
    with pytest.raises(ValueError, match="outside templates"):
        Narrator("en")


def test_strict_undefined_raises(tmp_path):
    d = tmp_path / "en"
    d.mkdir()
    (d / "narration.yaml").write_text("templates:\n  skipped: '{{ missing }}'\n", encoding="utf-8")
    with pytest.raises(UndefinedError):
        Narrator("en", templates_dir=tmp_path).render("skipped")


def test_author_prompt_is_not_jinja():
    out = render_author_prompt("{{ 7*7 }} {label} {unknown}", label="Name", hint="", section="", n=1, total=4)
    assert "49" not in out and "Name" in out and "{unknown}" in out


@pytest.mark.parametrize("bad", ["{0}", "{label.x}", "oops {", "{label[0]"])
def test_author_prompt_malformed_returns_raw(bad):
    assert render_author_prompt(bad, label="L", hint="", section="", n=1, total=1) in (bad, "L")


def test_plan_question_hint_pause_and_description_fallback():
    n = Narrator("en")
    cfg = VoiceFormConfig(hint_pause_ms=700)
    q = _q(hint="a hint")
    plan = n.plan_question(q, cfg, FieldVoiceMeta())
    uid = str(q.field_uid)
    assert plan.audio_keys == [f"q:{uid}:label", "pause:700", f"q:{uid}:hint"]
    q2 = _q(description="the description")
    plan2 = n.plan_question(q2, cfg, FieldVoiceMeta(pause_ms=100))
    assert "pause:100" in plan2.audio_keys and "the description" in plan2.text


_OPTS = [
    {"value": "a", "label": "Alpha"},
    {"value": "b", "label": "Beta"},
    {"value": "c", "label": "G", "disabled": True},
]


def test_plan_question_single_segment_cases_unchanged():
    n = Narrator("en")
    q = _q(field_type="select", options=_OPTS)
    key = f"q:{q.field_uid}:options"
    assert (
        "2 options on screen"
        in n.plan_question(q, VoiceFormConfig(), FieldVoiceMeta(enumerate="count_only")).segments[key]
    )
    assert key not in n.plan_question(q, VoiceFormConfig(), FieldVoiceMeta(enumerate="never")).segments
    assert "on screen" in n.plan_question(q, VoiceFormConfig(enumerate_options=False), FieldVoiceMeta()).segments[key]
    qb = _q(field_type="boolean")
    assert f"q:{qb.field_uid}:options" in n.plan_question(qb, VoiceFormConfig(), FieldVoiceMeta()).segments


def test_plan_question_enumerated_per_option_keys():
    n = Narrator("en")
    q = _q(field_type="select", options=_OPTS)
    u = q.field_uid
    plan = n.plan_question(q, VoiceFormConfig(), FieldVoiceMeta())
    assert plan.audio_keys == [f"q:{u}:label", f"q:{u}:options_intro", f"q:{u}:opt:1", "pause:500", f"q:{u}:opt:2"]
    assert f"q:{u}:options" not in plan.segments
    assert plan.segments[f"q:{u}:opt:1"] == n.render("option_item", ordinal=1, n=1, label="Alpha")
    assert plan.segments[f"q:{u}:opt:2"] == n.render("option_item", ordinal=2, n=2, label="Beta")
    assert "Alpha" in plan.segments[f"q:{u}:opt:1"] and "G" not in plan.segments[f"q:{u}:opt:2"]
    old_options = " ".join(
        [n.render("options_intro", count=2)]
        + [n.render("option_item", ordinal=i, n=i, label=lb) for i, lb in enumerate(["Alpha", "Beta"], start=1)]
    )
    assert plan.text == f"{plan.segments[f'q:{u}:label']} {old_options}"
    non_pause = [k for k in plan.audio_keys if not k.startswith("pause:")]
    assert list(plan.segments) == non_pause


def test_plan_question_option_pause_precedence():
    n = Narrator("en")
    q = _q(field_type="select", options=_OPTS)

    def pauses(cfg, meta):
        return [k for k in n.plan_question(q, cfg, meta).audio_keys if k.startswith("pause:")]

    assert pauses(VoiceFormConfig(option_pause_ms=300), FieldVoiceMeta()) == ["pause:300"]
    assert pauses(VoiceFormConfig(option_pause_ms=300), FieldVoiceMeta(option_pause_ms=50)) == ["pause:50"]
    plan0 = n.plan_question(q, VoiceFormConfig(option_pause_ms=0), FieldVoiceMeta())
    assert not [k for k in plan0.audio_keys if k.startswith("pause:")]
    assert f"q:{q.field_uid}:opt:1" in plan0.audio_keys and f"q:{q.field_uid}:opt:2" in plan0.audio_keys
    plan_override0 = n.plan_question(q, VoiceFormConfig(option_pause_ms=300), FieldVoiceMeta(option_pause_ms=0))
    assert not [k for k in plan_override0.audio_keys if k.startswith("pause:")]


def test_plan_question_hint_then_options_order():
    n = Narrator("en")
    q = _q(field_type="select", options=_OPTS, hint="pick one")
    u = q.field_uid
    plan = n.plan_question(q, VoiceFormConfig(), FieldVoiceMeta())
    assert plan.audio_keys == [
        f"q:{u}:label",
        "pause:600",
        f"q:{u}:hint",
        f"q:{u}:options_intro",
        f"q:{u}:opt:1",
        "pause:500",
        f"q:{u}:opt:2",
    ]


def test_plan_review_hides_sensitive():
    n = Narrator("en")
    items = [
        ReviewItemData(position=1, field_id="a", label="Name", answer_text="Bob"),
        ReviewItemData(position=2, field_id="b", label="Pass", answer_text="secret", sensitive=True),
        ReviewItemData(position=3, field_id="c", label="Note", answer_text="", skipped=True),
    ]
    plan = n.plan_review(items, VoiceFormConfig())
    assert "secret" not in plan.text and "[hidden]" in plan.segments["review:2"]
    assert "Bob" in plan.segments["review:1"] and "skipped" in plan.segments["review:3"]
    assert plan.audio_keys == ["review:intro", "review:1", "review:2", "review:3"]
