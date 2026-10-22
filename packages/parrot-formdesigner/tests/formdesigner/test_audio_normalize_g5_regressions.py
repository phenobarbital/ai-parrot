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
    for text in (
        "555 123 4567 extension 23",
        "555 123 4567 ext 23",
        "five five five one two three four five six seven extension two three",
    ):
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


# --------------------------------------------------------------------------- second pass: TIME around noon/midnight
@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "a quarter to midnight", "23:45"),
        ("en", "quarter to midnight", "23:45"),
        ("en", "five to midnight", "23:55"),
        ("en", "ten to midnight", "23:50"),
        ("en", "quarter past midnight", "00:15"),
        ("en", "half past midnight", "00:30"),
        ("en", "twenty past midnight", "00:20"),
        ("en", "a quarter to noon", "11:45"),
        ("en", "ten to noon", "11:50"),
        ("en", "ten to midday", "11:50"),
        ("en", "twenty past noon", "12:20"),
        ("en", "half past noon", "12:30"),
        ("es", "menos cuarto para la medianoche", "23:45"),
        ("es", "cuarto para la medianoche", "23:45"),
        ("es", "diez para la medianoche", "23:50"),
        ("es", "diez para el mediodía", "11:50"),
        ("es", "medianoche y cuarto", "00:15"),
        ("es", "mediodía y media", "12:30"),
        ("es", "mediodía y diez", "12:10"),
    ],
)
def test_time_relative_to_noon_or_midnight(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.TIME, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


@pytest.mark.parametrize(
    "locale,text",
    [("en", "midnight"), ("en", "at midnight"), ("en", "noon"), ("es", "medianoche"), ("es", "al mediodía")],
)
def test_time_plain_noon_midnight_still_accepted(locale: str, text: str) -> None:
    assert run(FieldType.TIME, text, locale).status == "accepted"


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "half midnight"),
        ("en", "to midnight"),
        ("en", "banana to midnight"),
        ("en", "midnight 5"),
        ("es", "medianoche banana"),
    ],
)
def test_time_noon_midnight_with_leftovers_never_accepted(locale: str, text: str) -> None:
    assert run(FieldType.TIME, text, locale).status != "accepted"


# --------------------------------------------------------------------------- second pass: NUMBER fractions
@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "one and a quarter", 1.25),
        ("en", "two and a quarter", 2.25),
        ("en", "two and three quarters", 2.75),
        ("en", "ten and three quarters", 10.75),
        ("en", "one and one quarter", 1.25),
        ("es", "uno y cuarto", 1.25),
        ("es", "cinco y cuarto", 5.25),
        ("es", "dos y un cuarto", 2.25),
        ("es", "dos y tres cuartos", 2.75),
    ],
)
def test_number_quarters_accepted(locale: str, text: str, expected: float) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "one and a third"),
        ("en", "two and two thirds"),
        ("en", "three and two fifths"),
        ("en", "one and an eighth"),
        ("es", "dos y un tercio"),
        ("es", "tres y dos quintos"),
        ("es", "uno y un octavo"),
        ("en", "two and five quarters"),
    ],
)
def test_number_unsupported_fractions_confirm_never_dropped(locale: str, text: str) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert res.status == "confirm"
    assert res.value is not None and float(res.value) != int(float(res.value))


def test_number_third_value_is_the_fraction() -> None:
    assert run(FieldType.NUMBER, "one and a third").value == pytest.approx(1.3333, abs=1e-4)
    assert run(FieldType.NUMBER, "three and two fifths").value == pytest.approx(3.4)


@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "five or six"),
        ("en", "12 and 15"),
        ("en", "twelve, fifteen"),
        ("es", "cinco o seis"),
        ("es", "doce y quince"),
        ("es", "10 o 20"),
    ],
)
def test_number_two_numbers_not_glued(locale: str, text: str) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert (res.status, res.reason) == ("rejected", "multiple_values")


# --------------------------------------------------------------------------- second pass: PHONE two numbers
@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "555 1234 or 555 9876"),
        ("en", "555 123 4567 and 555 987 6543"),
        ("en", "555 1234, 555 9876"),
        ("en", "five five five one two three four or five five five nine eight seven six"),
        ("en", "555 1234 or maybe 555 9876"),
        ("es", "555 1234 o 555 9876"),
        ("es", "555 123 4567 y 555 987 6543"),
        ("es", "cinco cinco cinco uno dos tres cuatro o cinco cinco cinco nueve ocho siete seis"),
    ],
)
def test_phone_two_numbers_not_glued(locale: str, text: str) -> None:
    res = run(FieldType.PHONE, text, locale)
    assert res.status != "accepted"
    assert (res.status, res.reason) == ("rejected", "multiple_values")


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "555, 123, 4567", "5551234567"),
        ("en", "five five five, one two three, four five six seven", "5551234567"),
        ("en", "555 1234 and 5", "55512345"),
        ("es", "555 123 y 4567", "5551234567"),
    ],
)
def test_phone_pauses_within_one_number_still_accepted(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.PHONE, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


# --------------------------------------------------------------------------- third pass: PHONE hundreds and es pairs
@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "two hundred twelve five five five oh one nine nine", "2125550199"),
        ("en", "eight hundred five five five one two one two", "8005551212"),
        ("en", "one eight hundred five five five one two one two", "18005551212"),
        ("es", "seiscientos doce trescientos cuarenta y cinco seiscientos setenta y ocho", "612345678"),
        ("es", "novecientos doce treinta y cuatro cincuenta y seis", "9123456"),
        ("es", "doce treinta y cuatro cincuenta y seis setenta y ocho", "12345678"),
    ],
)
def test_phone_hundreds_compose_unless_digits_follow(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.PHONE, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


def test_phone_longer_than_e164_is_rejected() -> None:
    res = run(FieldType.PHONE, "one two three four five six seven eight nine one two three four five six seven")
    assert (res.status, res.reason) == ("rejected", "too_long")


# --------------------------------------------------------------------------- third pass: TIME ranges and alternatives
@pytest.mark.parametrize(
    "locale,text",
    [
        ("en", "2 to 4 pm"),
        ("en", "1 to 2 pm"),
        ("en", "3 to 4 in the afternoon"),
        ("en", "3 or 4 pm"),
        ("en", "between 2 and 4 pm"),
        ("en", "two and four pm"),
        ("es", "las tres o cuatro de la tarde"),
        ("es", "las tres o las cuatro de la tarde"),
        ("es", "entre las dos y las cuatro de la tarde"),
    ],
)
def test_time_two_candidates_rejected(locale: str, text: str) -> None:
    res = run(FieldType.TIME, text, locale)
    assert (res.status, res.reason) == ("rejected", "multiple_values")


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("es", "diez para las cinco de la tarde", "16:50"),
        ("es", "cuarto para las cinco de la tarde", "16:45"),
        ("es", "para las cinco de la tarde", "17:00"),
        ("en", "five to four pm", "15:55"),
        ("en", "ten to four pm", "15:50"),
    ],
)
def test_time_minutes_to_hour(locale: str, text: str, expected: str) -> None:
    res = run(FieldType.TIME, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


# --------------------------------------------------------------------------- third pass: NUMBER fractions and dozens
@pytest.mark.parametrize(
    "locale,text,expected",
    [("en", "three quarters", 0.75), ("es", "un cuarto", 0.25), ("es", "tres cuartos", 0.75), ("en", "half", 0.5)],
)
def test_number_bare_fraction_is_the_value(locale: str, text: str, expected: float) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


def test_number_bare_approximate_fraction_confirms_its_value() -> None:
    res = run(FieldType.NUMBER, "one fifth")
    assert (res.status, res.value) == ("confirm", 0.2)


@pytest.mark.parametrize(
    "locale,text,expected",
    [("en", "half a dozen", 6), ("en", "a half dozen", 6), ("es", "media docena", 6), ("en", "2.5 dozen", 30)],
)
def test_number_dozen_variants_confirm_the_product(locale: str, text: str, expected: int) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert (res.status, res.value) == ("confirm", expected)


@pytest.mark.parametrize(
    "text",
    ["twelve, a dozen", "I have a dozen of 5", "three dozen and a half", "five, half a dozen"],
)
def test_number_dozen_with_another_quantity_rejected(text: str) -> None:
    res = run(FieldType.NUMBER, text)
    assert (res.status, res.reason) == ("rejected", "multiple_values")


@pytest.mark.parametrize("text", ["2 and 1/2", "1/2"])
def test_number_written_fraction_never_dropped(text: str) -> None:
    assert run(FieldType.NUMBER, text).status == "rejected"


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("es", "seiscientos doce", 612),
        ("es", "dos mil doscientos", 2200),
        ("es", "mil ciento veinte", 1120),
        ("es", "novecientos noventa y nueve", 999),
        ("en", "two thousand five hundred", 2500),
    ],
)
def test_number_hundreds_still_compose(locale: str, text: str, expected: int) -> None:
    res = run(FieldType.NUMBER, text, locale)
    assert (res.status, res.value) == ("accepted", expected)


def test_number_hundreds_after_a_number_start_a_new_one() -> None:
    res = run(FieldType.NUMBER, "seiscientos doce trescientos", "es")
    assert (res.status, res.reason) == ("rejected", "multiple_values")


# --------------------------------------------------------------------------- third pass: DATE es days and years
@pytest.mark.parametrize(
    "text,expected",
    [
        ("treinta y uno de marzo", "2026-03-31"),
        ("veintiuno de marzo", "2026-03-21"),
        ("cinco de marzo del veintisiete", "2027-03-05"),
        ("cinco de marzo del dos mil veintisiete", "2027-03-05"),
    ],
)
def test_date_es_compound_day_and_del_year(text: str, expected: str) -> None:
    res = run(FieldType.DATE, text, "es")
    assert (res.status, res.value) == ("accepted", expected)
