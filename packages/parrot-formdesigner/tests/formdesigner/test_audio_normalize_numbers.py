"""FEAT-653 TASK-4245 — normalize core + numbers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken, validate_typed
from parrot_formdesigner.audio.normalize.numbers import parse_numbers, tokenize
from parrot_formdesigner.core.types import FieldType

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def ctx(locale: str = "en") -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=True)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "twenty five", 25),
        ("en", "twenty-five", 25),
        ("en", "two hundred and five", 205),
        ("en", "one thousand two hundred five", 1205),
        ("en", "a hundred", 100),
        ("en", "1,250", 1250),
        ("en", "three point five", 3.5),
        ("en", "3.5", 3.5),
        ("en", "minus four", -4),
        ("en", "-4", -4),
        ("en", "$25", 25),
        ("en", "2 million", 2_000_000),
        ("en", "It is 42.", 42),
        ("es", "veinticinco", 25),
        ("es", "treinta y uno", 31),
        ("es", "ciento veinte", 120),
        ("es", "dos mil quinientos", 2500),
        ("es", "tres coma cinco", 3.5),
        ("es", "1,5", 1.5),
        ("es", "1.250", 1250),
    ],
)
def test_number_words_and_digits(locale: str, text: str, expected: float) -> None:
    res = normalize_spoken(FieldType.NUMBER, text, ctx=ctx(locale))
    assert res is not None and res.status == "accepted" and res.value == expected


def test_number_rejects_many_or_none() -> None:
    assert normalize_spoken(FieldType.NUMBER, "five or six", ctx=ctx()).reason == "multiple_values"
    assert normalize_spoken(FieldType.NUMBER, "0,4,12,523,573", ctx=ctx()).reason == "multiple_values"
    assert normalize_spoken(FieldType.NUMBER, "hello", ctx=ctx()).reason == "no_parse"
    res = normalize_spoken(FieldType.INTEGER, "3.5", ctx=ctx())
    assert res.status == "rejected" and res.reason == "non_integral"


def test_integer_type_is_int() -> None:
    res = normalize_spoken(FieldType.INTEGER, "forty two", ctx=ctx())
    assert res.value == 42 and isinstance(res.value, int)


def test_parse_numbers_sequence() -> None:
    sp = load_lexicon("en").spoken
    assert parse_numbers(tokenize("five five five oh one two three"), sp) == [5, 5, 5, 0, 1, 2, 3]
    assert parse_numbers(tokenize("0,4,12,523,573"), sp) == [0, 4, 12, 523, 573]


def test_unhandled_type_passthrough() -> None:
    assert normalize_spoken(FieldType.TEXT, "hello", ctx=ctx()) is None
    assert normalize_spoken(FieldType.URL, "x", ctx=ctx()) is None


def test_validate_typed_email() -> None:
    assert validate_typed(FieldType.EMAIL, "john at gmail") == "INVALID_EMAIL"
    assert validate_typed(FieldType.EMAIL, "john@gmail.com") is None
    assert validate_typed(FieldType.EMAIL, "") is None
    assert validate_typed(FieldType.PHONE, "0,4,12") is None


@pytest.mark.parametrize(
    "text", ["", "...", "point", "minus", "1,2,3,,", "ñandú ☃ 日本", "-", "+", "1.2.3.4", "hundred"]
)
@pytest.mark.parametrize("field_type", [FieldType.NUMBER, FieldType.INTEGER])
def test_never_raises_on_garbage(text: str, field_type: FieldType) -> None:
    res = normalize_spoken(field_type, text, ctx=ctx())
    assert res is not None and res.status in ("accepted", "confirm", "rejected")


def test_import_does_not_load_family_modules() -> None:
    import subprocess
    import sys

    code = (
        "import sys, parrot_formdesigner.audio.normalize;"
        "bad=[m for m in sys.modules if m.rsplit('.',1)[-1] in ('email','phone','temporal')"
        " and m.startswith('parrot_formdesigner.audio.normalize.')];"
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
