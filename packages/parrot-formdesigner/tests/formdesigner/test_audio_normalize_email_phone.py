"""FEAT-653 TASK-4246 — email and phone post-processors."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.normalize import NormalizeContext, normalize_spoken
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import EMAIL_PATTERN, PHONE_PATTERN

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def ctx(locale: str = "en") -> NormalizeContext:
    return NormalizeContext(lexicon=load_lexicon(locale), now=NOW, timezone_known=True)


@pytest.mark.parametrize(
    "locale,text,expected",
    [
        ("en", "john dot smith at gmail dot com", "john.smith@gmail.com"),
        ("en", "J O H N at gmail dot com", "john@gmail.com"),
        ("en", "anne dash marie at x dot io", "anne-marie@x.io"),
        ("en", "John@Gmail.com.", "john@gmail.com"),
        ("en", "emman 6321 at gmail dot com", "emman6321@gmail.com"),
        ("en", "sam underscore lee at corp dot co dot uk", "sam_lee@corp.co.uk"),
        ("es", "juan arroba gmail punto com", "juan@gmail.com"),
        ("es", "ana guion bajo lopez arroba correo punto mx", "ana_lopez@correo.mx"),
    ],
)
def test_email_spoken_and_written(locale: str, text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.EMAIL, text, ctx=ctx(locale))
    assert res.status == "accepted" and res.value == expected
    assert EMAIL_PATTERN.match(res.value)


def test_email_invalid_is_rejected_with_candidate() -> None:
    res = normalize_spoken(FieldType.EMAIL, "john at gmail", ctx=ctx())
    assert res.status == "rejected" and res.reason == "invalid_email" and res.value == "john@gmail"
    assert normalize_spoken(FieldType.EMAIL, "hello world", ctx=ctx()).status == "rejected"
    assert normalize_spoken(FieldType.EMAIL, "a at b at c dot com", ctx=ctx()).status == "rejected"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0,4,12,523,573", "0412523573"),
        ("five five five oh one two three", "5550123"),
        ("double five five oh one two three", "5550123"),
        ("plus one 555 0100", "+15550100"),
        ("+1 555 0100", "+15550100"),
        ("(555) 010-0123", "5550100123"),
        ("five fifty five, oh one two three", "5550123"),
    ],
)
def test_phone_variants(text: str, expected: str) -> None:
    res = normalize_spoken(FieldType.PHONE, text, ctx=ctx())
    assert res.status == "accepted" and res.value == expected
    assert PHONE_PATTERN.match(res.value)


def test_phone_too_short_and_no_digits() -> None:
    res = normalize_spoken(FieldType.PHONE, "123", ctx=ctx())
    assert res.status == "rejected" and res.reason == "too_short" and res.value == "123"
    assert normalize_spoken(FieldType.PHONE, "hello", ctx=ctx()).reason == "no_parse"


def test_phone_spanish_digits() -> None:
    res = normalize_spoken(FieldType.PHONE, "cinco cinco cinco cero uno dos tres", ctx=ctx("es"))
    assert res.status == "accepted" and res.value == "5550123"
    res = normalize_spoken(FieldType.PHONE, "más uno 555 0100", ctx=ctx("es"))
    assert res.value == "+15550100"


@pytest.mark.parametrize("text", ["", "...", "@", "+", "double", "oh", "☃"])
def test_never_raises(text: str) -> None:
    for ft in (FieldType.EMAIL, FieldType.PHONE):
        assert normalize_spoken(ft, text, ctx=ctx()).status in ("accepted", "confirm", "rejected")
