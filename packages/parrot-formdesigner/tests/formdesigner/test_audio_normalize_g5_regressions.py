"""FEAT-653 review fixes — spec G5: outside the handled grammar → confirm / no_parse, never a wrong ``accepted``."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken
from parrot_formdesigner.core.types import FieldType

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # a Monday


def ctx(locale: str = "en") -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=True)


def run(field_type: FieldType, text: str, locale: str = "en"):
    res = normalize_spoken(field_type, text, ctx=ctx(locale))
    assert res is not None
    return res


# --------------------------------------------------------------------------- #1 TIME
@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "quarter past three pm", "15:15"),
        ("en", "a quarter past three pm", "15:15"),
        ("en", "quarter past three in the afternoon", "15:15"),
        ("en", "ten past three pm", "15:10"),
        ("en", "twenty five past two pm", "14:25"),
        ("en", "ten to four pm", "15:50"),
        ("en", "quarter to four pm", "15:45"),
        ("en", "a quarter to four pm", "15:45"),
        ("en", "twenty to one pm", "12:40"),
        ("en", "half past three pm", "15:30"),
        ("en", "2 30 pm", "14:30"),
        ("en", "2:30 pm", "14:30"),
        ("en", "3 thirty pm", "15:30"),
        ("en", "14 30", "14:30"),
        ("en", "9 15 am", "09:15"),
        ("en", "it's three fifteen pm", "15:15"),
        ("en", "around 4 pm", "16:00"),
        ("es", "las cinco y cuarto de la tarde", "17:15"),
        ("es", "las cinco menos cuarto de la tarde", "16:45"),
        ("es", "las cinco menos diez de la tarde", "16:50"),
        ("es", "las cinco y diez de la tarde", "17:10"),
        ("es", "las cinco y media de la tarde", "17:30"),
        ("es", "la una y cuarto de la tarde", "13:15"),
        ("es", "las ocho y veinte de la mañana", "08:20"),
        ("es", "las 3 y cuarto de la tarde", "15:15"),
    ],
)
def test_time_review_inputs_accepted(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.TIME, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "quarter past three", "03:15"),
        ("en", "ten to four", "03:50"),
        ("es", "las cuatro y cuarto", "04:15"),
        ("es", "las cuatro menos cuarto", "03:45"),
    ],
)
def test_time_relational_without_meridiem_confirms(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.TIME, text, locale)
    assert (res.status, res.reason, res.value) == ("confirm", "ambiguous_meridiem", expected)


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "three banana pm"),
        ("en", "ten to"),
        ("en", "past three pm"),
        ("en", "quarter three pm"),
        ("es", "las cinco menos pm"),
    ],
)
def test_time_unrecognised_is_never_accepted(locale: str, text: str) -> None:
    assert run(FieldType.TIME, text, locale).status != "accepted"


def test_time_to_twelve_is_not_guessed() -> None:
    assert run(FieldType.TIME, "ten to twelve pm").status != "accepted"


# --------------------------------------------------------------------------- #2 DATE
@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "June fifth twenty twenty five", "2025-06-05"),
        ("en", "June fifth twenty twenty-five", "2025-06-05"),
        ("en", "June fifth, twenty twenty five", "2025-06-05"),
        ("en", "June fifth two thousand twenty six", "2026-06-05"),
        ("en", "fifth of June twenty twenty six", "2026-06-05"),
        ("en", "March twenty first twenty twenty seven", "2027-03-21"),
        ("en", "March twenty fifth twenty twenty", "2020-03-25"),
        ("en", "third of March two thousand five", "2005-03-03"),
        ("en", "June fifth", "2026-06-05"),
        ("en", "June 5 2025", "2025-06-05"),
        ("en", "June 5th, 2025", "2025-06-05"),
        ("en", "June twenty fifth", "2026-06-25"),
        ("es", "5 de junio de 2025", "2025-06-05"),
        ("es", "cinco de junio de dos mil veinticinco", "2025-06-05"),
        ("es", "el martes pasado por la mañana", "2026-10-06"),
        ("es", "el martes pasado por la tarde", "2026-10-06"),
        ("es", "mañana por la mañana", "2026-10-13"),
        ("es", "el martes por la mañana", "2026-10-13"),
        ("es", "el lunes por la mañana", "2026-10-19"),
        ("es", "mañana", "2026-10-13"),
    ],
)
def test_date_review_inputs_accepted(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.DATE, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


@pytest.mark.parametrize("text", ["March twenty twenty six", "March twenty twenty five", "June twenty twenty"])
def test_date_month_and_year_only_is_not_a_day(text: str) -> None:
    res = run(FieldType.DATE, text)
    assert res.status != "accepted"
    assert res.value not in ("2026-03-20", "2025-03-20", "2020-06-20")


def test_date_two_day_candidates_confirm() -> None:
    res = run(FieldType.DATE, "March 5 25")
    assert res.status == "confirm" and res.value == "2026-03-05"


# --------------------------------------------------------------------------- #4 NUMBER
@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "twelve hundred", 1200),
        ("en", "twenty five hundred", 2500),
        ("en", "nineteen hundred", 1900),
        ("en", "fifteen hundred", 1500),
        ("en", "twelve hundred and fifty", 1250),
        ("en", "two hundred fifty", 250),
        ("en", "a hundred and fifty", 150),
        ("en", "two thousand five hundred", 2500),
        ("en", "one hundred", 100),
        ("en", "point five", 0.5),
        ("en", "zero point five", 0.5),
        ("en", "point two five", 0.25),
        ("en", "one point two five", 1.25),
        ("en", "two and a half", 2.5),
        ("en", "one and a half", 1.5),
        ("en", "twelve and a half", 12.5),
        ("en", "0.250", 0.25),
        ("es", "dos y medio", 2.5),
        ("es", "dos y media", 2.5),
        ("es", "punto cinco", 0.5),
        ("es", "cero coma dos cinco", 0.25),
        ("es", "0.250", 0.25),
        ("es", "0,250", 0.25),
        ("es", "1.250", 1250),
        ("es", "1.250,5", 1250.5),
        ("es", "dos mil quinientos", 2500),
    ],
)
def test_number_review_inputs_accepted(locale: str, text: str, expected: float) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("es", "una docena", 12),
        ("es", "dos docenas", 24),
        ("es", "media docena", 6),
        ("en", "a dozen", 12),
        ("en", "two dozen", 24),
    ],
)
def test_number_dozen_confirms(locale: str, text: str, expected: int) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert res.status == "confirm" and res.value == expected


def test_integer_and_half_is_not_integral() -> None:
    res = run(FieldType.INTEGER, "two and a half")
    assert res.status == "rejected" and res.reason == "non_integral"


# --------------------------------------------------------------------------- #5 PHONE
def test_phone_extension_is_not_glued() -> None:
    for text in ("555 123 4567 extension 23", "555 123 4567 ext 23", "five five five one two three four five six seven extension two three"):
        res = run(FieldType.PHONE, text)
        assert res.status == "confirm" and res.value == "5551234567", text
    res = run(FieldType.PHONE, "555 123 4567 extensión 23", "es")
    assert res.status == "confirm" and res.value == "5551234567"
    res = run(FieldType.PHONE, "555 123 4567 x23")
    assert res.status == "confirm" and res.value == "5551234567"


def test_phone_eight_hundred_is_eight_zero_zero() -> None:
    res = run(FieldType.PHONE, "one eight hundred five five five one two one two")
    assert (res.status, res.value) == ("accepted", "18005551212")
    res = run(FieldType.PHONE, "eight hundred five five five one two one two")
    assert (res.status, res.value) == ("accepted", "8005551212")
    res = run(FieldType.PHONE, "ochocientos cinco cinco cinco uno dos uno dos", "es")
    assert (res.status, res.value) == ("accepted", "8005551212")


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "it's plus one 212 555 0100", "+12125550100"),
        ("en", "my number is plus one two one two five five five zero one zero zero", "+12125550100"),
        ("en", "call me at +1 212 555 0100", "+12125550100"),
        ("en", "plus one 555 0100", "+15550100"),
        ("es", "mi número es más uno 212 555 0100", "+12125550100"),
    ],
)
def test_phone_plus_anywhere_before_digits(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.PHONE, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


def test_phone_plus_after_digits_is_not_a_prefix() -> None:
    res = run(FieldType.PHONE, "555 0100 plus")
    assert res.value == "5550100"
