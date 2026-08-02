"""Unit tests for `parrot.security.groundedness.extractors` (FEAT-398, TASK-2044).

Covers per-kind positive/negative extraction, span de-overlap (a money hit
must never also yield a bare-number atom), the NFKC Unicode pre-pass, and
the `min_number_digits` noise floor — spec §4 test matrix, Module 1.
"""
from parrot.security.groundedness.extractors import extract_atoms
from parrot.security.groundedness.models import AtomKind
from parrot.security.groundedness.normalize import nfkc_normalize


class TestMoneyExtraction:
    def test_extracts_money_literal(self):
        atoms = extract_atoms("Total revenue was $1,243,500 this quarter.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.MONEY
        assert atoms[0].raw == "$1,243,500"
        assert atoms[0].normalized == 1243500.0

    def test_extracts_money_with_magnitude_suffix(self):
        atoms = extract_atoms("Approximately $1.24M in sales.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.MONEY
        assert atoms[0].normalized == 1_240_000.0

    def test_extracts_negative_money(self):
        atoms = extract_atoms("Balance: -$500,000 this month.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.MONEY
        assert atoms[0].normalized == -500_000.0

    def test_no_money_literal_no_atom(self):
        atoms = extract_atoms("There was no revenue reported.")
        assert not [a for a in atoms if a.kind == AtomKind.MONEY]

    def test_multiple_currency_symbols(self):
        atoms = extract_atoms("Sold for €1,000 and £2,000.")
        money_atoms = [a for a in atoms if a.kind == AtomKind.MONEY]
        assert len(money_atoms) == 2


class TestPercentExtraction:
    def test_extracts_percent_literal(self):
        atoms = extract_atoms("Inventory was down 15% from last month.")
        percent_atoms = [a for a in atoms if a.kind == AtomKind.PERCENT]
        assert len(percent_atoms) == 1
        assert percent_atoms[0].raw == "15%"
        assert percent_atoms[0].normalized == 15.0

    def test_extracts_negative_percent(self):
        atoms = extract_atoms("Growth was -15.3% this quarter.")
        percent_atoms = [a for a in atoms if a.kind == AtomKind.PERCENT]
        assert len(percent_atoms) == 1
        assert percent_atoms[0].normalized == -15.3

    def test_no_percent_sign_no_atom(self):
        atoms = extract_atoms("Fifteen percent growth reported.")
        assert not [a for a in atoms if a.kind == AtomKind.PERCENT]


class TestDateExtraction:
    def test_extracts_iso_date(self):
        atoms = extract_atoms("Closed the quarter on 2026-06-30.")
        date_atoms = [a for a in atoms if a.kind == AtomKind.DATE]
        assert len(date_atoms) == 1
        assert date_atoms[0].raw == "2026-06-30"
        assert date_atoms[0].normalized == "2026-06-30"

    def test_extracts_slash_date(self):
        atoms = extract_atoms("As of 06/28/2026 inventory was low.")
        date_atoms = [a for a in atoms if a.kind == AtomKind.DATE]
        assert len(date_atoms) == 1
        assert date_atoms[0].normalized == "2026-06-28"

    def test_extracts_month_name_date_full(self):
        atoms = extract_atoms("Reported on June 30, 2026.")
        date_atoms = [a for a in atoms if a.kind == AtomKind.DATE]
        assert len(date_atoms) == 1
        assert date_atoms[0].normalized == "2026-06-30"

    def test_extracts_month_name_date_abbreviated(self):
        atoms = extract_atoms("Reported on Jun 30, 2026.")
        date_atoms = [a for a in atoms if a.kind == AtomKind.DATE]
        assert len(date_atoms) == 1
        assert date_atoms[0].normalized == "2026-06-30"

    def test_no_date_pattern_no_atom(self):
        atoms = extract_atoms("It happened sometime last quarter.")
        assert not [a for a in atoms if a.kind == AtomKind.DATE]


class TestIdentifierExtraction:
    def test_extracts_email(self):
        atoms = extract_atoms("Contact finance@acme.example.com for details.")
        id_atoms = [a for a in atoms if a.kind == AtomKind.IDENTIFIER]
        assert len(id_atoms) == 1
        assert id_atoms[0].raw == "finance@acme.example.com"

    def test_extracts_url(self):
        atoms = extract_atoms("See https://example.com/report for the full report.")
        id_atoms = [a for a in atoms if a.kind == AtomKind.IDENTIFIER]
        assert len(id_atoms) == 1
        assert id_atoms[0].raw == "https://example.com/report"

    def test_extracts_ticket_code(self):
        atoms = extract_atoms("Reference invoice INV-2210 for this order.")
        id_atoms = [a for a in atoms if a.kind == AtomKind.IDENTIFIER]
        assert len(id_atoms) == 1
        assert id_atoms[0].raw == "INV-2210"

    def test_ticket_code_requires_two_digits(self):
        atoms = extract_atoms("Reference code AB-1 only.")
        assert not [a for a in atoms if a.kind == AtomKind.IDENTIFIER]

    def test_no_identifier_pattern_no_atom(self):
        atoms = extract_atoms("No contact information was provided.")
        assert not [a for a in atoms if a.kind == AtomKind.IDENTIFIER]


class TestNumberExtractionAndNoiseFloor:
    def test_number_below_default_floor_skipped(self):
        atoms = extract_atoms("There were 312 items in stock.")
        assert atoms == []

    def test_number_at_default_floor_kept(self):
        atoms = extract_atoms("There were 4812 items in stock.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.NUMBER
        assert atoms[0].normalized == 4812.0

    def test_custom_min_number_digits_lowers_floor(self):
        atoms = extract_atoms("There were 312 items in stock.", min_number_digits=3)
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.NUMBER

    def test_custom_min_number_digits_raises_floor(self):
        atoms = extract_atoms("There were 4812 items in stock.", min_number_digits=5)
        assert atoms == []

    def test_magnitude_suffixed_number_exempt_from_floor(self):
        """A magnitude-suffixed bare number ("2.5M") is inherently non-noise
        and bypasses the min_number_digits floor entirely (extractors.py's
        documented exemption, mirroring money's identical suffix handling)."""
        atoms = extract_atoms("Downloads reached 2.5M this year.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.NUMBER
        assert atoms[0].normalized == 2_500_000.0


class TestDeOverlap:
    def test_money_not_double_counted_as_bare_number(self):
        atoms = extract_atoms("Total: $1,243,500 exactly.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.MONEY

    def test_percent_not_double_counted_as_bare_number(self):
        atoms = extract_atoms("Change: 15.5% exactly.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.PERCENT

    def test_iso_date_not_split_into_bare_numbers(self):
        atoms = extract_atoms("Date: 2026-06-30 exactly.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.DATE

    def test_ticket_code_not_double_counted_as_number(self):
        atoms = extract_atoms("Ref: INV-2210 exactly.")
        id_atoms = [a for a in atoms if a.kind == AtomKind.IDENTIFIER]
        number_atoms = [a for a in atoms if a.kind == AtomKind.NUMBER]
        assert len(id_atoms) == 1
        assert number_atoms == []


class TestNFKCUnicodePrePass:
    def test_fullwidth_digits_normalize_to_ascii(self):
        """Direct check on the pre-pass helper used by extract_atoms."""
        assert nfkc_normalize("１２３４") == "1234"

    def test_extracts_number_from_fullwidth_digits(self):
        atoms = extract_atoms("Total: １２３４ units sold.")
        assert len(atoms) == 1
        assert atoms[0].kind == AtomKind.NUMBER
        assert atoms[0].normalized == 1234.0


class TestClaimPriorityOrdering:
    def test_atoms_ordered_by_start_offset(self):
        atoms = extract_atoms(
            "On 2026-06-30 revenue reached $1,243,500 with 4812 orders."
        )
        starts = [a.start for a in atoms]
        assert starts == sorted(starts)
