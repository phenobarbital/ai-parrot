# TASK-2369: BOE identifier utilities

**Feature**: FEAT-449 — Legal Norms Graph (BOE consolidated legislation with temporal validity)
**Spec**: `sdd/specs/legal-norms-graph-boe.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Principle §1.2 of the parent design states that identifiers are canonical
keys, not text: every node `_key` derives from a stable public identifier. `norma._key` is the
BOE id (e.g. `BOE-A-2015-10566`) and `articulo._key` is `{norma}:{art}`. This task provides the
single, tested place where BOE ids are validated and canonicalised, so every downstream module
(parser, datasource, tests) shares one implementation.

Deliberately scoped to **BOE only**. ECLI/ROJ/CELEX helpers arrive with the sources that need
them (Sprint 2+), and adding them now would be speculative.

---

## Scope

- Implement `normalize_boe_id(raw: str) -> str` — trims, upper-cases the letter segment, and
  returns the canonical `BOE-A-YYYY-NNNNN` form.
- Implement `is_valid_boe_id(raw: str) -> bool` — returns whether a string is a well-formed
  BOE id, without raising.
- Implement `article_key(boe_id: str, article: str) -> str` — builds the `{norma}:{art}`
  composite key used as `articulo.key_field`.
- Write unit tests covering valid ids, malformed input, whitespace, and case variation.

**NOT in scope**: ECLI, ROJ or CELEX parsing; any network access; any graph or ontology code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/__init__.py` | CREATE | Package marker for the legal toolkit tree |
| `packages/ai-parrot-tools/src/parrot_tools/legal/ids.py` | CREATE | BOE id regex, normalisation, validation, composite key |
| `packages/ai-parrot-tools/tests/legal/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot-tools/tests/legal/test_ids.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact references. Do NOT invent imports or helpers.

### Verified Imports

This task has **no internal ai-parrot dependencies**. Standard library only:

```python
import re
```

### Existing Signatures to Use

None — this is a leaf module with no integration points. It is imported by TASK-2372
(parser) and TASK-2373 (datasource).

### Does NOT Exist

- ~~`parrot_tools.legal`~~ — the entire package tree is created by THIS task. Do not
  assume any sibling module (`boe/`, `cendoj/`, `models.py`) exists yet.
- ~~`parrot.interfaces.legal`~~ — `parrot/interfaces/` is a **mixins** package for bot
  functionality, not a home for domain models. Do not put legal code there.
- ~~Any existing BOE/ECLI/CELEX helper anywhere in the repo~~ — a grep for
  `cendoj|eurlex|celex|BOE-A-|ECLI:` across all of `packages/` returns **zero** matches.
  You are writing the first one.

---

## Implementation Notes

### Pattern to Follow

BOE identifiers have the shape `BOE-<section letter>-<year>-<sequence>`, e.g.
`BOE-A-2015-10566`. Keep the regex anchored and explicit:

```python
_BOE_ID_RE = re.compile(r"^BOE-[A-Z]-\d{4}-\d+$")
```

### Key Constraints

- Pure functions, no I/O, no async needed here (this is the one module in the feature that
  is legitimately synchronous — it does no I/O).
- Full Google-style docstrings and strict type hints (project standard).
- `normalize_boe_id` should raise `ValueError` with a clear message on unparseable input;
  `is_valid_boe_id` must never raise.
- Do not silently "fix" an id that is structurally wrong — normalisation means whitespace
  and case, not guessing missing segments.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/` — sibling toolkit packages for layout
  conventions.

---

## Acceptance Criteria

- [ ] `normalize_boe_id("  boe-a-2015-10566 ")` returns `"BOE-A-2015-10566"`
- [ ] `normalize_boe_id` raises `ValueError` on structurally invalid input
- [ ] `is_valid_boe_id` returns `False` (never raises) for malformed input
- [ ] `article_key("BOE-A-2015-10566", "5")` returns `"BOE-A-2015-10566:5"`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/test_ids.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/`
- [ ] Imports work: `from parrot_tools.legal.ids import normalize_boe_id, is_valid_boe_id, article_key`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_ids.py
import pytest
from parrot_tools.legal.ids import normalize_boe_id, is_valid_boe_id, article_key


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
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/legal-norms-graph-boe.spec.md` for full context.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** in `sdd/tasks/index/legal-norms-graph-boe.json` → `"in-progress"`.
5. **Implement** following the scope above.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2369-legal-id-utilities.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
