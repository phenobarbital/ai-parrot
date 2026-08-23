"""Unit tests for BOE identifier utilities (TASK-2369)."""
import pytest

from parrot_tools.legal.ids import article_key, is_valid_boe_id, normalize_boe_id


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
