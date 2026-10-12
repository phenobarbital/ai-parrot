"""FEAT-653 TASK-4244 — spoken lexicon tables."""

from __future__ import annotations

import pytest

from parrot_formdesigner.audio.narration import NARRATION_KEYS, Narrator
from parrot_formdesigner.audio.narration.lexicon import load_lexicon


@pytest.mark.parametrize("locale", ["en", "es"])
def test_spoken_tables_populated(locale: str) -> None:
    sp = load_lexicon(locale).spoken
    assert sp.units and sp.tens and sp.scales and sp.email_symbols and sp.months and sp.weekdays
    assert sp.relative_days and sp.am_words and sp.pm_words


def test_cardinals_unchanged() -> None:
    """AC9: option matching tables keep 1-10 only."""
    assert set(load_lexicon("en").cardinals.values()) == set(range(1, 11))
    assert set(load_lexicon("es").cardinals.values()) == set(range(1, 11))


def test_locale_specific_settings() -> None:
    assert load_lexicon("en").spoken.date_order == "MDY"
    assert load_lexicon("en").spoken.decimal_separator == "."
    es = load_lexicon("es").spoken
    assert es.date_order == "DMY" and es.decimal_separator == ","


def test_keys_are_folded() -> None:
    es = load_lexicon("es").spoken
    assert "manana" in es.relative_days and "pasado manana" in es.relative_days
    assert "guion bajo" in es.email_symbols and "guion" in es.email_symbols
    assert es.email_symbols["arroba"] == "@" and es.email_symbols["guion bajo"] == "_"
    assert "miercoles" in es.weekdays and "mediodia" in es.noon_words
    assert "mas" in es.plus_words and "dieciseis" in es.units


@pytest.mark.parametrize("locale", ["en", "es"])
def test_rejection_templates_render(locale: str) -> None:
    assert {"invalid_email", "invalid_value"} <= NARRATION_KEYS
    n = Narrator(locale)
    assert n.render("invalid_email") and n.render("invalid_value")
