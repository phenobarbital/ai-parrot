"""Unit tests for BOE identifier utilities (TASK-2369)."""

import pytest
from parrot_tools.legal.ids import (
    _sanitize_key_component,
    article_key,
    is_valid_boe_id,
    normalize_boe_id,
)


class TestBOEIds:
    def test_normalize_canonical(self):
        assert normalize_boe_id("BOE-A-2015-10566") == "BOE-A-2015-10566"

    def test_normalize_whitespace_and_case(self):
        assert normalize_boe_id("  boe-a-2015-10566 ") == "BOE-A-2015-10566"

    def test_normalize_rejects_malformed(self):
        with pytest.raises(ValueError):
            normalize_boe_id("not-an-id")

    def test_is_valid_never_raises(self):
        assert is_valid_boe_id("BOE-A-2015-10566") is True
        assert is_valid_boe_id("") is False
        assert is_valid_boe_id("BOE-A-15-10566") is False

    def test_article_key_composite(self):
        assert article_key("BOE-A-2015-10566", "5") == "BOE-A-2015-10566:5"

    def test_article_key_normalizes_whitespace(self):
        """Designators like '5 bis' must not leak a space into `_key`."""
        assert article_key("BOE-A-2015-10566", "5 bis") == "BOE-A-2015-10566:5_bis"

    def test_article_key_collapses_and_trims_whitespace(self):
        assert article_key("BOE-A-2015-10566", "  10   ter ") == "BOE-A-2015-10566:10_ter"

    def test_article_key_transliterates_accented_designators(self):
        """'único' has no whitespace but IS not a valid ArangoDB `_key` byte."""
        assert article_key("BOE-A-2015-10566", "único") == "BOE-A-2015-10566:unico"

    def test_article_key_sanitizes_multi_word_accented_designator(self):
        assert (
            article_key("BOE-A-2015-10566", "Disposición adicional primera")
            == "BOE-A-2015-10566:Disposicion_adicional_primera"
        )

    def test_article_key_strips_disallowed_punctuation(self):
        assert article_key("BOE-A-2015-10566", "5/2020") == "BOE-A-2015-10566:5_2020"


class TestSanitizeKeyComponent:
    def test_ascii_passthrough(self):
        assert _sanitize_key_component("5") == "5"

    def test_transliterates_accents(self):
        assert _sanitize_key_component("único") == "unico"
        assert _sanitize_key_component("ñoño") == "nono"

    def test_transliterates_ordinal_indicator(self):
        assert _sanitize_key_component("1º") == "1o"

    def test_collapses_disallowed_run_to_single_underscore(self):
        assert _sanitize_key_component("a   b") == "a_b"
        assert _sanitize_key_component("a///b") == "a_b"

    def test_strips_leading_and_trailing_underscores(self):
        assert _sanitize_key_component("  5  ") == "5"

    def test_empty_or_all_disallowed_falls_back_to_underscore(self):
        assert _sanitize_key_component("") == "_"
        assert _sanitize_key_component("   ") == "_"
