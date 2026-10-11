"""Tests for the deterministic option matcher (FEAT-649, TASK-4215)."""

import pytest

from parrot_formdesigner.audio.models import ReviewItemData
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.option_matcher import match_option, match_review_item
from parrot_formdesigner.core.types import FieldType

OPTS = [
    {"value": "r", "label": "Rojo"},
    {"value": "g", "label": "Verde"},
    {"value": "b", "label": "Azul", "disabled": True},
    {"value": "s", "label": "Saltar"},
]


@pytest.fixture
def es():
    return load_lexicon("es")


def _m(text, es, opts=OPTS, ft=FieldType.SELECT, **kw):
    return match_option(text, opts, field_type=ft, lexicon=es, **kw)


def test_match_option_methods_and_thresholds(es):
    assert _m("rojo", es).match.value == "r"
    assert _m("rojo", es).match.method == "exact"
    assert _m("la segunda", es).match.value == "g"
    assert _m("la última", es).match.value == "s"
    assert _m("opción 3", es).match.value == "s"  # disabled skipped: enabled = r, g, s
    assert _m("opción 3", es).match.method == "ordinal"
    yn = _m("sí claro", es, opts=[], ft=FieldType.BOOLEAN)
    assert yn.match.value is True and yn.match.method == "yes_no"
    assert _m("no", es, opts=[], ft=FieldType.BOOLEAN).match.value is False
    nps = [{"value": str(i), "label": str(i)} for i in range(11)]
    assert _m("tres", es, opts=nps, ft=FieldType.NPS).match.value == "3"
    assert _m("10", es, opts=nps, ft=FieldType.NPS).match.value == "10"
    assert _m("quiero el verde oscuro", es).match.method == "contains"
    assert _m("quiero el verde oscuro", es).match.score == pytest.approx(0.9)
    fz = _m("rojjo", es)
    assert fz.match.value == "r" and fz.match.method == "fuzzy" and fz.status == "accepted"
    # confidence scaling
    assert _m("rojo", es, stt_confidence=0.7).status == "confirm"
    assert _m("rojo", es, stt_confidence=0.5).status == "no_match"
    assert _m("rojo", es, stt_confidence=None).status == "accepted"
    assert _m("zzzz qqqq", es).status == "no_match"


def test_match_multi_select_conjunctions(es):
    out = _m("rojo y la última", es, ft=FieldType.MULTI_SELECT, multi=True)
    assert [m.value for m in out.matches] == ["r", "s"] and out.status == "accepted"
    assert [m.value for m in _m("todas", es, ft=FieldType.MULTI_SELECT, multi=True).matches] == ["r", "g", "s"]
    none = _m("ninguna", es, ft=FieldType.MULTI_SELECT, multi=True)
    assert none.status == "accepted" and none.matches == []
    assert _m("blah qqq", es, ft=FieldType.MULTI_SELECT, multi=True).status == "no_match"
    letters = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}, {"value": "c", "label": "C"}]
    out = _m("a y c", es, opts=letters, ft=FieldType.MULTI_SELECT, multi=True)
    assert [m.value for m in out.matches] == ["a", "c"]


def test_match_option_skips_disabled_and_ties_confirm(es):
    out = _m("azul", es)
    assert out.match is None or out.match.value != "b"
    assert all(a.value != "b" for a in out.alternatives)
    tie = [{"value": "1", "label": "Casa norte"}, {"value": "2", "label": "Casa sur"}]
    out = _m("casa", es, opts=tie)
    assert out.status == "confirm" and {a.value for a in out.alternatives} == {"1", "2"}


def test_match_review_item(es):
    items = [
        ReviewItemData(position=i + 1, field_id=f"f{i}", label=lab, answer_text="x")
        for i, lab in enumerate(["Nombre", "Correo", "Teléfono"])
    ]
    assert match_review_item("cambiar la 2", items, es) == 2
    assert match_review_item("corregir la tercera", items, es) == 3
    assert match_review_item("cambiar la última", items, es) == 3
    assert match_review_item("cambiar correo", items, es) == 2
    assert match_review_item("cambiar la 9", items, es) is None
    assert match_review_item("sí está bien", items, es) is None
