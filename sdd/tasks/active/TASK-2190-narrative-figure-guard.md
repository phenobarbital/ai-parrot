# TASK-2190: Narrative figure guard (numeric derivability check)

**Feature**: FEAT-420 — FinanceReporter Tier-2 + Narrative Skill
**Spec**: `sdd/specs/finance-reporter-tier2-narrative.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2186
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec, and satisfies criterion **G-H**:
*no fabricated figures reach a rendered financial artifact.*

This is the mechanical half of the fence around the probabilistic layer. Prompt
discipline alone is not acceptable for a financial report — a single invented
number is the one failure mode the spec calls categorically unacceptable. So
after the LLM writes prose, every numeric literal in it is checked for
derivability from the deterministic facts. Any figure that is not derivable
discards the **entire** narrative, not just the offending sentence.

All-or-nothing is deliberate: a partially-scrubbed paragraph is a new artifact
nobody reviewed, and it collapses into the same degraded state as "no narrator",
so there is exactly one fallback path to reason about and test.

**Known limitation, accepted by the spec** (§7 Known Risks): this guard catches
invented *figures*, not a fluent mis-*characterisation* of a correct figure.
Do not over-claim in docstrings.

---

## Scope

- Create `parrot/tools/infographic_recipes/figure_guard.py` with:
  - `extract_figures(prose: str) -> list[str]` — pull every numeric literal out
    of prose, handling the formats the reference artifact emits.
  - `figures_are_derivable(prose: str, facts: dict[str, Any]) -> tuple[bool, list[str]]`
    — returns `(ok, offending_figures)`.
- Handle the reference artifact's display formats (see `fmt_money` /`fmt_pct` in
  `sdd/artifacts/executive_summary.py:74-84`):
  - `$1.23M` (millions, 2dp), `$45.6K` (thousands, 1dp with thousands separators)
  - `+12.3%` / `-12.3%` percentages
  - the **U+2212 MINUS SIGN** (`−`), not just ASCII hyphen — the reference
    uses it for every negative value
  - `+` prefixes from `force_plus`
  - bare integers such as a project count or `n_snapshots`
- Recursively collect every numeric value from the facts dict as the derivable
  set (facts are 2dp-rounded per `library.py:18-20`).
- Compare with a tolerance that accounts for **two** roundings: the facts' 2dp
  rounding and the prose's display rounding (`$1.23M` from `1234567.89`).
- Write unit tests.

**NOT in scope**:
- Calling an LLM, or any narrator logic — the guard is a pure function applied
  *by* the narrator (TASK-2192).
- Editing/scrubbing the prose. The guard **reports**; the caller discards.
- Wiring into `RecipeRunner` — the runner stays agnostic (TASK-2189).
- Judging whether a *characterisation* is correct — out of scope by design.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_recipes/figure_guard.py` | CREATE | `extract_figures` + `figures_are_derivable` |
| `packages/ai-parrot/tests/tools/infographic_recipes/test_figure_guard.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# For figure_guard.py — stdlib only. Do NOT import pandas, parrot.skills,
# or any LLM client here; this is a pure text/number utility.
from __future__ import annotations
import logging
import re
from typing import Any

# For tests:
from parrot.tools.infographic_recipes.figure_guard import (
    extract_figures, figures_are_derivable,
)
```

### Existing Signatures to Use

```python
# sdd/artifacts/executive_summary.py — THE DISPLAY FORMATS TO PARSE.
# Reference artifact, NOT importable. Ported here as parsing targets only.

def fmt_money(n: float, force_plus: bool = False) -> str:      # line 74
    sign = "−" if n < 0 else ("+" if force_plus else "")   # line 75  <-- U+2212!
    abs_n = abs(n)                                              # line 76
    if abs_n >= 1_000_000:                                      # line 77
        return f"{sign}${abs_n/1_000_000:.2f}M"                 # line 78  -> "$1.23M"
    return f"{sign}${abs_n/1000:,.1f}K"                         # line 79  -> "$45.6K", "$1,234.5K"

def fmt_pct(n: float) -> str:                                   # line 82
    sign = "−" if n < 0 else "+"                            # line 83  <-- always signed
    return f"{sign}{abs(n):.1f}%"                                # line 84  -> "+12.3%"
```

```python
# The facts contract this guard validates against (produced by TASK-2186,
# spec §2 Data Models). Numeric leaves are 2dp-rounded.
{
  "headline": {"rev_state": str, "rev_direction": str, "ebitda_direction": str,
               "both_improving": bool, "both_worsening": bool, "diverging": bool,
               "first_label": str, "last_label": str},
  "top_driver": {"division": str, "project": str,
                 "ebitda_variance": float,        # <-- numeric
                 "trend": float | None,           # <-- numeric
                 "urgency": str} | None,
  "division_reads": [{"division": str, "kind": str,
                      "named": [str, ...], "offsetter": str | None}],
  "watch": [{"division": str, "project": str,
             "ebitda_variance": float, "trend": float | None}],   # <-- numeric
  "bright": [ ... same ... ],
  "n_snapshots": int,                                             # <-- numeric
}
# NOTE: bools are NOT numbers for this purpose — `True` must not make "1" derivable.

# Upstream totals that may ALSO appear in prose, reachable via the facts the
# narrator is given. If the narrator is handed variance_analysis totals too,
# those numeric leaves count as derivable. Verified shape (library.py:239-250):
#   first_totals / last_totals -> _day_totals_for keys (library.py:82-102):
#     rev_actual, rev_budget, rev_variance, rev_variance_pct,
#     ebitda_actual, ebitda_budget, ebitda_variance
```

### Does NOT Exist

- ~~`parrot.tools.infographic_recipes.figure_guard`~~ — this task creates it.
- ~~`extract_figures` / `figures_are_derivable` anywhere~~ — do not exist.
- ~~an existing number-extraction or prose-validation utility in `parrot/`~~ —
  searched; there is none to reuse. Do not import from
  `parrot.tools.output_scrubber` or similar; unrelated concern.
- ~~`import sdd.artifacts.executive_summary`~~ — NOT a package module. The
  formats above are ported as parsing targets, never imported.
- ~~`InfographicToolkit._maybe_enhance` validation helpers~~
  (`parrot/tools/_enhance_html_check.validate_enhanced_html`) — that validates
  **HTML/SRI**, not numbers, and belongs to a deprecated lane (FEAT-273). Not reusable.
- ~~a tolerance constant defined elsewhere~~ — you define it here.
- ~~`facts["variance_analysis"]`~~ — the facts dict is the `narrative_facts`
  output shape above; it does not nest the upstream step under that key unless
  the narrator passes it. Handle "numeric leaves anywhere in the given dict"
  generically rather than assuming a fixed path.

---

## Implementation Notes

### Pattern to Follow

```python
# Pure, dependency-free, well-documented module.

logger = logging.getLogger(__name__)

#: Tolerance for matching a displayed figure against a fact. Accounts for the
#: facts' 2dp rounding AND the prose's display rounding ($1.23M from 1234567.89
#: loses up to 5_000 of precision at the millions scale).
_RELATIVE_TOLERANCE = 0.01   # 1% — calibrate in tests, document the reasoning

_MINUS = "−"

#: Matches $1.23M / $45.6K / $1,234.5K / +12.3% / -12.3% / bare integers,
#: with an optional leading '+', ASCII '-', or U+2212.
_FIGURE_RE = re.compile(
    rf"[+\-{_MINUS}]?\$?\d[\d,]*(?:\.\d+)?\s*[MK%]?"
)


def extract_figures(prose: str) -> list[str]:
    """Return every numeric literal appearing in ``prose``, in order."""


def _to_float(figure: str) -> float | None:
    """Normalise a displayed figure to a float ('$1.23M' -> 1_230_000.0)."""
    # strip $ and separators; map U+2212 -> '-'; apply M/K multipliers;
    # '%' keeps its face value (a percentage is compared against a *_pct fact)


def _numeric_leaves(value: Any) -> list[float]:
    """Recursively collect numeric leaves, EXCLUDING bools."""
    if isinstance(value, bool):      # bool is a subclass of int — exclude FIRST
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numeric_leaves(v)]
    if isinstance(value, list):
        return [n for v in value for n in _numeric_leaves(v)]
    return []


def figures_are_derivable(prose: str, facts: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check every figure in ``prose`` against the numeric leaves of ``facts``.

    Returns:
        ``(ok, offending)``. ``ok`` is False if ANY figure is not derivable;
        ``offending`` lists those figures. Callers MUST discard the whole
        narrative when ``ok`` is False (spec criterion G-H) — this function
        never edits the prose.
    """
```

### Key Constraints

- **`bool` is a subclass of `int` in Python.** Check `isinstance(x, bool)` FIRST
  in `_numeric_leaves`, or `both_improving=True` silently makes the figure `1`
  derivable. This is the single most likely bug in this task.
- **U+2212 handling is mandatory**, not cosmetic — every negative value the
  reference formats uses it (`executive_summary.py:75,83`). Missing it means
  every negative figure reads as un-derivable and the guard rejects all prose.
- Compare **absolute values** for money where the sign is carried separately by
  the format, but do not let that make a sign error derivable — document the
  choice you make and test it.
- A percentage in prose should match a `*_pct`-style fact, not a dollar fact.
  Keep the comparison honest rather than "matches any number within tolerance".
- Tolerance must be justified in a comment and pinned by a test; do not leave a
  magic float unexplained.
- Pure function: no I/O, no logging of the prose content itself at INFO+ (it may
  be reproduced in logs; log the *offending figures* only, not whole paragraphs).
- Keep the module import-light so it can be used from a mixin without dragging
  in pandas.

### References in Codebase

- `sdd/artifacts/executive_summary.py:74-84` — the exact display formats
- `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/library.py:18-20` — the
  2dp money-rounding convention that sets the tolerance floor
- `packages/ai-parrot/tests/tools/infographic_recipes/` — test package layout

---

## Acceptance Criteria

- [ ] `from parrot.tools.infographic_recipes.figure_guard import extract_figures, figures_are_derivable` works
- [ ] Prose quoting only derivable figures returns `(True, [])`
- [ ] Prose containing an invented figure returns `(False, [<that figure>])`
- [ ] `$1.23M`, `$45.6K`, `$1,234.5K`, `+12.3%`, `−12.3%` are all extracted correctly
- [ ] A U+2212-negative figure matching a negative fact is derivable
- [ ] Display rounding of a 2dp fact is **not** a false positive
- [ ] `both_improving=True` in the facts does **not** make the figure `1` derivable (bool exclusion)
- [ ] Prose with no figures at all returns `(True, [])`
- [ ] The functions are pure — no mutation of `prose` or `facts`
- [ ] The tolerance constant carries a comment justifying its value, and a test pins it
- [ ] Module imports only stdlib (no pandas, no parrot imports) — verified by inspection/test
- [ ] Docstrings do **not** claim the guard validates characterisations, only figures
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/infographic_recipes/test_figure_guard.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/infographic_recipes/figure_guard.py`
- [ ] `mypy` clean on the new file

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/infographic_recipes/test_figure_guard.py  (create)
import pytest

from parrot.tools.infographic_recipes.figure_guard import (
    extract_figures, figures_are_derivable,
)

MINUS = "−"


@pytest.fixture
def facts():
    return {
        "headline": {"rev_state": "behind", "rev_direction": "narrowing",
                     "both_improving": True, "diverging": False},
        "top_driver": {"division": "Retail", "project": "Alpha",
                       "ebitda_variance": -42000.0, "trend": -8000.0,
                       "urgency": "immediate"},
        "watch": [{"division": "Retail", "project": "Alpha",
                   "ebitda_variance": -42000.0, "trend": -8000.0}],
        "n_snapshots": 3,
    }


class TestExtractFigures:
    @pytest.mark.parametrize("prose,expected_count", [
        ("EBITDA is $1.23M behind.", 1),
        ("Down $45.6K on the month.", 1),
        ("Revenue of $1,234.5K.", 1),
        ("The gap narrowed +12.3%.", 1),
        (f"Variance of {MINUS}12.3%.", 1),
        ("Across 3 snapshots we saw $42.0K slip.", 2),
        ("No numbers here at all.", 0),
    ])
    def test_extracts_reference_formats(self, prose, expected_count):
        assert len(extract_figures(prose)) == expected_count


class TestDerivability:
    def test_derivable_prose_passes(self, facts):
        ok, offending = figures_are_derivable(
            f"Alpha is {MINUS}$42.0K on EBITDA, worsening by {MINUS}$8.0K.", facts,
        )
        assert ok and offending == []

    def test_invented_figure_rejected(self, facts):
        ok, offending = figures_are_derivable("Alpha is $99.9K behind.", facts)
        assert not ok and offending

    def test_no_figures_passes(self, facts):
        assert figures_are_derivable("Revenue is behind, the gap is narrowing.", facts) == (True, [])

    def test_bool_does_not_make_one_derivable(self, facts):
        """CRITICAL: bool is a subclass of int — True must not authorise '1'."""
        ok, offending = figures_are_derivable("Exactly $1.00M was lost.", facts)
        assert not ok

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
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§7 Known Risks states the accepted
   limitation — do not try to solve characterisation correctness here)
2. **Check dependencies** — TASK-2186 must be in `sdd/tasks/completed/` so the
   facts contract is settled
3. **Verify the Codebase Contract** — re-read
   `sdd/artifacts/executive_summary.py:74-84` for the display formats, and the
   actual `narrative_facts` output TASK-2186 produced (it is the authority now)
4. **Update status** in `sdd/tasks/index/finance-reporter-tier2-narrative.json`
   → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above.
   **Write the bool-exclusion test first** — it is the trap in this task.
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2190-narrative-figure-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
