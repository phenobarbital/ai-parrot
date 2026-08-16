"""Unit tests for the narrative figure guard (FEAT-420 Module 4)."""

import pytest

from parrot.tools.infographic_recipes.figure_guard import (
    extract_figures,
    figures_are_derivable,
)

MINUS = "−"


@pytest.fixture
def facts():
    return {
        "headline": {
            "rev_state": "behind",
            "rev_direction": "narrowing",
            "both_improving": True,
            "diverging": False,
        },
        "top_driver": {
            "division": "Retail",
            "project": "Alpha",
            "ebitda_variance": -42000.0,
            "trend": -8000.0,
            "urgency": "immediate",
        },
        "watch": [
            {
                "division": "Retail",
                "project": "Alpha",
                "ebitda_variance": -42000.0,
                "trend": -8000.0,
            }
        ],
        "n_snapshots": 3,
    }


class TestExtractFigures:
    @pytest.mark.parametrize(
        "prose,expected_count",
        [
            ("EBITDA is $1.23M behind.", 1),
            ("Down $45.6K on the month.", 1),
            ("Revenue of $1,234.5K.", 1),
            ("The gap narrowed +12.3%.", 1),
            (f"Variance of {MINUS}12.3%.", 1),
            ("Across 3 snapshots we saw $42.0K slip.", 2),
            ("No numbers here at all.", 0),
        ],
    )
    def test_extracts_reference_formats(self, prose, expected_count):
        assert len(extract_figures(prose)) == expected_count

    def test_does_not_mutate_prose(self):
        prose = "EBITDA is $1.23M behind."
        extract_figures(prose)
        assert prose == "EBITDA is $1.23M behind."


class TestDerivability:
    def test_derivable_prose_passes(self, facts):
        ok, offending = figures_are_derivable(
            f"Alpha is {MINUS}$42.0K on EBITDA, worsening by {MINUS}$8.0K.", facts
        )
        assert ok and offending == []

    def test_invented_figure_rejected(self, facts):
        ok, offending = figures_are_derivable("Alpha is $99.9K behind.", facts)
        assert not ok and offending

    def test_no_figures_passes(self, facts):
        assert figures_are_derivable(
            "Revenue is behind, the gap is narrowing.", facts
        ) == (True, [])

    def test_bool_does_not_make_one_derivable(self, facts):
        """CRITICAL: bool is a subclass of int — True must not authorise '1'."""
        ok, offending = figures_are_derivable("Exactly $1.00M was lost.", facts)
        assert not ok

    def test_sign_flip_is_not_derivable(self, facts):
        """A positive figure must not match a negative fact of the same magnitude."""
        ok, offending = figures_are_derivable("Alpha is +$42.0K on EBITDA.", facts)
        assert not ok
        assert offending == ["+$42.0K"]

    def test_display_rounding_not_a_false_positive(self):
        ok, _ = figures_are_derivable("$1.23M", {"v": 1_234_567.89})
        assert ok

    def test_tolerance_constant_is_pinned(self):
        """Guards against silently loosening the check."""
        from parrot.tools.infographic_recipes import figure_guard

        assert figure_guard._RELATIVE_TOLERANCE <= 0.01

    def test_inputs_not_mutated(self, facts):
        import copy

        before = copy.deepcopy(facts)
        figures_are_derivable("Alpha is $42.0K behind.", facts)
        assert facts == before

    def test_module_is_stdlib_only(self):
        import inspect

        from parrot.tools.infographic_recipes import figure_guard

        src = inspect.getsource(figure_guard)
        assert "pandas" not in src and "from parrot" not in src

    def test_bare_integer_derivable(self, facts):
        ok, offending = figures_are_derivable("Across 3 snapshots.", facts)
        assert ok and offending == []

    def test_percent_figure_matches_percent_fact(self):
        ok, offending = figures_are_derivable("+12.3%", {"rev_pct_change": 12.3})
        assert ok and offending == []
