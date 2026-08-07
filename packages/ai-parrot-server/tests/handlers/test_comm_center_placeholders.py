"""Unit tests for the CommCenter placeholder catalog (FEAT-417, Module 3)."""
from datetime import datetime

from parrot.handlers.comm_center_placeholders import build_catalog
from parrot.outputs.a2ui.recipes.params import DATE_RESOLVERS

FROZEN = datetime(2026, 8, 6, 12, 0, 0)


class TestPlaceholderCatalog:
    """Tests pinning the three-group catalog shape and its disclosures."""

    def test_three_groups(self):
        c = build_catalog(now=FROZEN)
        assert set(c) >= {"recipient_fields", "computed_functions", "reserved"}

    def test_counts(self):
        c = build_catalog(now=FROZEN)
        assert len(c["recipient_fields"]) == 5
        assert len(c["computed_functions"]) == 7
        assert len(c["reserved"]) == 3

    def test_functions_are_resolvers_plus_two(self):
        names = {f["name"] for f in build_catalog(now=FROZEN)["computed_functions"]}
        assert names == set(DATE_RESOLVERS) | {"now", "current_year"}

    def test_deterministic_samples(self):
        a = build_catalog(now=FROZEN)
        b = build_catalog(now=FROZEN)
        assert a == b
        today = next(f for f in a["computed_functions"] if f["name"] == "today")
        assert today["sample"] == "2026-08-06"

    def test_reserved_names_flagged(self):
        reserved = {r["name"] for r in build_catalog(now=FROZEN)["reserved"]}
        assert reserved == {"recipient", "message", "subject"}

    def test_disclosures_present(self):
        c = build_catalog(now=FROZEN)
        assert c["limitation"]  # bare-placeholder restriction
        assert c["extra_columns"]  # pass-through note

    def test_every_computed_function_has_live_sample(self):
        c = build_catalog(now=FROZEN)
        for fn in c["computed_functions"]:
            assert fn.get("sample")
