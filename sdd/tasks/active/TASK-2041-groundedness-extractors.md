# TASK-2041: Groundedness Atom Extractors and Normalization

**Feature**: FEAT-398 — Deterministic Groundedness Scoring
**Spec**: `sdd/specs/deterministic-groundedness-scoring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of the groundedness scoring pipeline (spec §3 Module 1). Creates the
`parrot/security/groundedness/` subpackage with the five atom extractors
(money, percent, number, date, identifier), span de-overlap logic, NFKC
pre-pass, and normalization (magnitude suffixes, thousand/decimal separators,
multi-format dates → ISO, identifier case-folding, significant-digit counting).
Stdlib only — `re`, `datetime`, `unicodedata`.

---

## Scope

- Create `parrot/security/groundedness/__init__.py` (package init, public exports).
- Create `parrot/security/groundedness/models.py` — `AtomKind` enum and `Atom` Pydantic model.
- Create `parrot/security/groundedness/normalize.py` — normalization functions:
  - Number normalization: magnitude suffixes (`k`/`M`/`B`), thousand separators,
    decimal separators → canonical float. Sig-digit counting (for precision-aware
    tolerance in TASK-2042).
  - Date normalization: common en-US formats (`MM/DD/YYYY`, `Month DD, YYYY`,
    `YYYY-MM-DD`) → ISO-8601 string.
  - Identifier normalization: NFKC + case-fold.
  - NFKC Unicode pre-pass for all text before extraction.
- Create `parrot/security/groundedness/extractors.py` — `extract_atoms()`:
  - Five regex-based extractors: money, percent, number, date, identifier.
  - Span de-overlap: money/percent/date/identifier claim spans before bare numbers
    (a `$1,243,500` hit is not re-counted as a bare number).
  - `min_number_digits` floor (skip bare integers shorter than threshold).
  - Returns `list[Atom]` with `kind`, `raw`, `normalized`, `start`, `end`.

**NOT in scope**: `EvidenceIndex`, scorer, policy model, bot wiring, tests (separate tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/groundedness/__init__.py` | CREATE | Package init, public exports |
| `packages/ai-parrot/src/parrot/security/groundedness/models.py` | CREATE | `AtomKind`, `Atom` models |
| `packages/ai-parrot/src/parrot/security/groundedness/normalize.py` | CREATE | Normalization functions |
| `packages/ai-parrot/src/parrot/security/groundedness/extractors.py` | CREATE | `extract_atoms()` with de-overlap |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field        # standard Pydantic
from enum import Enum                        # stdlib
import re                                    # stdlib
import datetime                              # stdlib
import unicodedata                           # stdlib
```

### Existing Signatures to Use

```python
# No existing groundedness code — this task creates the package from scratch.
# The Atom/AtomKind models are new, designed in spec §2 Data Models.
```

### Does NOT Exist

- ~~`parrot.security.groundedness`~~ — created by THIS task.
- ~~`parrot.security.pii`~~ — FEAT-324, not implemented. Do NOT import.
- ~~Any existing atom/extraction/normalization code in parrot~~ — all new.
- ~~`parrot.utils.normalize`~~ — does not exist; normalization is local to this package.

---

## Implementation Notes

### Pattern to Follow

```python
# models.py — Pydantic model pattern (spec §2 Data Models)
class AtomKind(str, Enum):
    MONEY = "money"
    PERCENT = "percent"
    NUMBER = "number"
    DATE = "date"
    IDENTIFIER = "identifier"

class Atom(BaseModel):
    kind: AtomKind
    raw: str                  # as stated in the text
    normalized: str | float   # comparison key
    start: int                # char offset in the source text
    end: int
```

### Key Constraints

- Stdlib only: `re`, `datetime`, `unicodedata`, `hashlib`. No external deps.
- All functions are **sync** (pure CPU, single-digit-ms budget).
- NFKC pre-pass on all input text before running extractors.
- Span de-overlap must ensure a `$1,243,500` yields exactly one `money` atom,
  not a money + a bare number.
- `min_number_digits` default 4 — configurable, passed via a minimal policy
  interface (accept `int` for now; full `GroundednessPolicy` model is TASK-2042).
- Significant-digit counting: `$1.24M` (3 sig digits) vs `$1,234,500` (7 sig digits)
  — expose via a helper function, consumed by the scorer in TASK-2042.
- Google-style docstrings, strict type hints, `logging.getLogger(__name__)`.

### References in Codebase

- `packages/ai-parrot/src/parrot/security/` — sibling security modules (redaction.py, prompt_injection.py).
- `packages/ai-parrot/src/parrot/models/basic.py:23` — `ToolCall` model (context, not imported here).

---

## Acceptance Criteria

- [ ] `extract_atoms("Revenue was $1.24M for Q2 2026")` returns atoms for money + date.
- [ ] `extract_atoms("$1,243,500")` returns exactly one `money` atom, not money + number.
- [ ] NFKC fullwidth digits (`＄１,２４３`) are extracted correctly.
- [ ] Number normalization: `$1.24M` ≡ `1240000.0`; `$1,234,500` ≡ `1234500.0`.
- [ ] Date normalization: `06/28/2026`, `June 28, 2026`, `2026-06-28` → same ISO key.
- [ ] Identifier normalization: case-folded, NFKC-normalized.
- [ ] `min_number_digits` floor works: bare `42` skipped at default 4, `4200` extracted.
- [ ] Sig-digit counting: `1.24M` → 3 sig digits; `1,234,500` → 7 sig digits.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/security/groundedness/`
- [ ] Imports work: `from parrot.security.groundedness.extractors import extract_atoms`
- [ ] Imports work: `from parrot.security.groundedness.models import Atom, AtomKind`

---

## Test Specification

```python
# tests/unit/security/test_groundedness_extractors.py
import pytest
from parrot.security.groundedness.models import Atom, AtomKind
from parrot.security.groundedness.extractors import extract_atoms
from parrot.security.groundedness.normalize import (
    normalize_number, normalize_date, count_significant_digits,
)


class TestExtractorsPerKind:
    def test_money_extraction(self):
        atoms = extract_atoms("Revenue was $1.24M")
        assert any(a.kind == AtomKind.MONEY for a in atoms)

    def test_percent_extraction(self):
        atoms = extract_atoms("Growth of 15.3%")
        assert any(a.kind == AtomKind.PERCENT for a in atoms)

    def test_date_extraction(self):
        atoms = extract_atoms("Due date: 06/28/2026")
        assert any(a.kind == AtomKind.DATE for a in atoms)

    def test_identifier_extraction(self):
        atoms = extract_atoms("Ticket INV-9999 from user@example.com")
        ids = [a for a in atoms if a.kind == AtomKind.IDENTIFIER]
        assert len(ids) >= 2

    def test_number_extraction(self):
        atoms = extract_atoms("There are 1234 items")
        assert any(a.kind == AtomKind.NUMBER for a in atoms)

    def test_min_number_digits_floor(self):
        atoms = extract_atoms("There are 42 items", min_number_digits=4)
        assert not any(a.kind == AtomKind.NUMBER for a in atoms)


class TestDeoverlap:
    def test_money_not_double_counted_as_number(self):
        atoms = extract_atoms("$1,243,500")
        assert len([a for a in atoms if a.kind == AtomKind.MONEY]) == 1
        assert len([a for a in atoms if a.kind == AtomKind.NUMBER]) == 0


class TestNormalization:
    def test_magnitude_suffixes(self):
        assert normalize_number("$1.24M") == 1_240_000.0

    def test_thousand_separators(self):
        assert normalize_number("1,234,500") == 1_234_500.0

    def test_date_formats_converge(self):
        iso = normalize_date("06/28/2026")
        assert iso == normalize_date("June 28, 2026")
        assert iso == normalize_date("2026-06-28")

    def test_significant_digits(self):
        assert count_significant_digits("1.24M") == 3
        assert count_significant_digits("1,234,500") == 7
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/deterministic-groundedness-scoring.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `parrot/security/` exists, confirm no `groundedness/` dir yet
4. **Update status** in `sdd/tasks/index/deterministic-groundedness-scoring.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2041-groundedness-extractors.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
