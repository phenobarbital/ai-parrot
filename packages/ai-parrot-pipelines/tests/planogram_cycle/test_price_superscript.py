"""Superscript-cents prices on fact tags (FEAT-685, TASK-4366)."""

import pytest

from parrot_pipelines.planogram.comparison.tags import tag_price
from parrot_pipelines.planogram.identification.detector import DETECT_PROMPT_VERSION, GENERIC_DETECTION_PROMPT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("149999", 1499.99),
        ("SAVE $200 64999", 649.99),
        ("99999", 999.99),
        ("SAVE $150 34999", 349.99),
        ("SAVE $ 200 34999", 349.99),
        ("Epson EX3280 Projector SAVE $150 34999", 349.99),
    ],
)
def test_tag_price_superscript_cents(text, expected):
    assert tag_price(text) == expected


def test_tag_price_decimal_wins():
    assert tag_price("$12.99 149999") == 12.99
    assert tag_price("12,99 EUR") == 12.99


@pytest.mark.parametrize("text", ["SAVE $200", "SAVE $ 200", "20%", "12", "no price", None])
def test_tag_price_ignores_dollar_and_percent_only(text):
    assert tag_price(text) is None


def test_detect_prompt_mentions_decimal_point():
    assert "decimal point" in GENERIC_DETECTION_PROMPT
    assert "1499.99" in GENERIC_DETECTION_PROMPT
    assert DETECT_PROMPT_VERSION == "detect-v3"
