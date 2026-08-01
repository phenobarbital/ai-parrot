"""Unit tests for `parrot.security.groundedness.normalize` (FEAT-398, TASK-2044).

Covers magnitude-suffix folding, thousand/decimal separator handling,
multi-format date normalization, and significant-digit counting — spec §4
test matrix, Module 1.
"""
import pytest

from parrot.security.groundedness.normalize import (
    count_significant_digits,
    nfkc_normalize,
    normalize_date,
    normalize_identifier,
    normalize_number,
)


class TestNfkcNormalize:
    def test_fullwidth_digits_to_ascii(self):
        assert nfkc_normalize("１２３４") == "1234"

    def test_ascii_passthrough(self):
        assert nfkc_normalize("plain text 1234") == "plain text 1234"


class TestNormalizeNumberMagnitudeSuffixes:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2.5k", 2_500.0),
            ("2.5K", 2_500.0),
            ("1.24M", 1_240_000.0),
            ("1.24m", 1_240_000.0),
            ("3B", 3_000_000_000.0),
            ("3b", 3_000_000_000.0),
        ],
    )
    def test_magnitude_suffix_case_insensitive(self, raw, expected):
        assert normalize_number(raw) == expected

    def test_money_with_currency_and_suffix(self):
        assert normalize_number("$1.24M") == 1_240_000.0


class TestNormalizeNumberSeparators:
    def test_strips_thousand_separators(self):
        assert normalize_number("1,234,500") == 1_234_500.0

    def test_strips_currency_symbol(self):
        assert normalize_number("$1,243,500") == 1_243_500.0

    def test_strips_percent_sign(self):
        assert normalize_number("15.3%") == 15.3

    def test_leading_minus_sign_preserved(self):
        assert normalize_number("-15.3%") == -15.3

    def test_leading_plus_sign_resolves_positive(self):
        assert normalize_number("+15.3") == 15.3

    def test_decimal_value(self):
        assert normalize_number("0.005") == 0.005


class TestNormalizeNumberErrors:
    def test_empty_after_stripping_raises(self):
        with pytest.raises(ValueError):
            normalize_number("$")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            normalize_number("abc")


class TestCountSignificantDigits:
    def test_rounded_money_few_sig_digits(self):
        assert count_significant_digits("$1.24M") == 3

    def test_fully_written_number_all_digits_significant(self):
        assert count_significant_digits("1,234,500") == 7

    def test_leading_zeros_not_significant(self):
        assert count_significant_digits("0.005") == 1

    def test_degenerate_all_zero_literal(self):
        assert count_significant_digits("0.00") == 3

    def test_percent_sign_not_counted(self):
        assert count_significant_digits("15.3%") == 3

    def test_sign_not_counted(self):
        assert count_significant_digits("-15.3") == 3


class TestNormalizeDate:
    def test_iso_passthrough(self):
        assert normalize_date("2026-06-30") == "2026-06-30"

    def test_slash_mm_dd_yyyy(self):
        assert normalize_date("06/28/2026") == "2026-06-28"

    def test_full_month_name(self):
        assert normalize_date("June 30, 2026") == "2026-06-30"

    def test_abbreviated_month_name(self):
        assert normalize_date("Jun 30, 2026") == "2026-06-30"

    def test_abbreviated_month_with_period(self):
        assert normalize_date("Jun. 30, 2026") == "2026-06-30"

    def test_unrecognized_format_raises(self):
        with pytest.raises(ValueError):
            normalize_date("not a date")

    def test_unrecognized_month_name_raises(self):
        with pytest.raises(ValueError):
            normalize_date("Foo 30, 2026")

    def test_invalid_calendar_date_raises(self):
        with pytest.raises(ValueError):
            normalize_date("2026-13-45")


class TestNormalizeIdentifier:
    def test_case_folds(self):
        assert normalize_identifier("INV-2210") == "inv-2210"

    def test_email_case_folds(self):
        assert normalize_identifier("Bob@Other.com") == "bob@other.com"

    def test_nfkc_applied(self):
        assert normalize_identifier("１２３") == "123"
