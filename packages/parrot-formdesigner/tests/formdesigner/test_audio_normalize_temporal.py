"""FEAT-653 TASK-4247 — temporal post-processors (fixed clock: Monday 2026-10-12, 15:00 UTC)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken
from parrot_formdesigner.core.types import FieldType

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # a Monday


def ctx(locale: str = "en", *, tz_known: bool = True) -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=tz_known)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "today", "2026-10-12"),
        ("en", "tomorrow", "2026-10-13"),
        ("en", "yesterday", "2026-10-11"),
        ("en", "Friday", "2026-10-16"),
        ("en", "this Friday", "2026-10-16"),
        ("en", "next Friday", "2026-10-16"),
        ("en", "next Monday", "2026-10-19"),
        ("en", "Monday", "2026-10-19"),
        ("en", "last Friday", "2026-10-09"),
        ("en", "March third", "2026-03-03"),
        ("en", "third of March 2027", "2027-03-03"),
        ("en", "March twenty first", "2026-03-21"),
        ("en", "March thirtieth", "2026-03-30"),
        ("en", "March 3rd, 2027", "2027-03-03"),
        ("en", "3/13", "2026-03-13"),
        ("en", "3/13/27", "2027-03-13"),
        ("en", "2026-03-12", "2026-03-12"),
        ("es", "13/3", "2026-03-13"),
        ("es", "pasado mañana", "2026-10-14"),
        ("es", "3 de marzo de 2027", "2027-03-03"),
        ("es", "el próximo viernes", "2026-10-16"),
        ("es", "el viernes pasado", "2026-10-09"),
    ],
)
def test_date_grammar(locale: str, text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.DATE, text, ctx=ctx(locale))
    assert res.status == "accepted" and res.value == expected


def test_date_ambiguous_order_confirms() -> None:
    en = normalize_spoken(FieldType.DATE, "3/4", ctx=ctx("en"))
    assert en.status == "confirm" and en.reason == "ambiguous_order" and en.value == "2026-03-04"
    es = normalize_spoken(FieldType.DATE, "3/4", ctx=ctx("es"))
    assert es.status == "confirm" and es.value == "2026-04-03"
    assert normalize_spoken(FieldType.DATE, "4/4", ctx=ctx()).status == "accepted"


def test_relative_without_timezone_confirms() -> None:
    res = normalize_spoken(FieldType.DATE, "tomorrow", ctx=ctx(tz_known=False))
    assert res.status == "confirm" and res.reason == "needs_timezone" and res.value == "2026-10-13"
    assert normalize_spoken(FieldType.DATE, "2026-03-12", ctx=ctx(tz_known=False)).status == "accepted"


def test_date_rejects() -> None:
    assert normalize_spoken(FieldType.DATE, "February thirtieth", ctx=ctx()).status == "rejected"
    assert normalize_spoken(FieldType.DATE, "2/30", ctx=ctx()).reason == "out_of_range"
    assert normalize_spoken(FieldType.DATE, "banana", ctx=ctx()).reason == "no_parse"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("three thirty pm", "15:30"),
        ("noon", "12:00"),
        ("midnight", "00:00"),
        ("15:30", "15:30"),
        ("3 pm", "15:00"),
        ("3:30pm", "15:30"),
        ("3:30 p.m.", "15:30"),
        ("half past three pm", "15:30"),
        ("ten o'clock am", "10:00"),
        ("nine oh five am", "09:05"),
        ("12 am", "00:00"),
        ("seven in the evening", "19:00"),
    ],
)
def test_time_grammar(text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.TIME, text, ctx=ctx())
    assert res.status == "accepted" and res.value == expected


def test_time_es() -> None:
    res = normalize_spoken(FieldType.TIME, "tres y media de la tarde", ctx=ctx("es"))
    assert res.status == "accepted" and res.value == "15:30"
    assert normalize_spoken(FieldType.TIME, "mediodía", ctx=ctx("es")).value == "12:00"


def test_time_ambiguous_meridiem_and_rejects() -> None:
    res = normalize_spoken(FieldType.TIME, "three thirty", ctx=ctx())
    assert res.status == "confirm" and res.reason == "ambiguous_meridiem" and res.value == "03:30"
    assert normalize_spoken(FieldType.TIME, "25:00", ctx=ctx()).status == "rejected"
    assert normalize_spoken(FieldType.TIME, "banana", ctx=ctx()).status == "rejected"


def test_datetime_grammar() -> None:
    res = normalize_spoken(FieldType.DATETIME, "tomorrow at three pm", ctx=ctx())
    assert res.status == "accepted" and res.value == "2026-10-13T15:00"
    res = normalize_spoken(FieldType.DATETIME, "mañana a las tres de la tarde", ctx=ctx("es"))
    assert res.status == "accepted" and res.value == "2026-10-13T15:00"
    res = normalize_spoken(FieldType.DATETIME, "tomorrow at three", ctx=ctx())
    assert res.status == "confirm" and res.reason == "ambiguous_meridiem" and res.value == "2026-10-13T03:00"
    assert normalize_spoken(FieldType.DATETIME, "banana at three pm", ctx=ctx()).status == "rejected"
    res = normalize_spoken(FieldType.DATETIME, "2026-03-12 15:30", ctx=ctx())
    assert res.value == "2026-03-12T15:30" and res.status == "accepted"
    res = normalize_spoken(FieldType.DATETIME, "tomorrow at three pm", ctx=ctx(tz_known=False))
    assert res.status == "confirm" and res.reason == "needs_timezone"


@pytest.mark.parametrize("text", ["", "...", "at", "/", "13/45/99", "☃", "March", "at at at"])
def test_never_raises(text: str) -> None:
    for ft in (FieldType.DATE, FieldType.TIME, FieldType.DATETIME):
        assert normalize_spoken(ft, text, ctx=ctx()).status in ("accepted", "confirm", "rejected")
