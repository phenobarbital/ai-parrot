# Code Review: TASK-5163 — PDF renderer — BOOLEAN prints Yes / No radio choices

**Spec**: sdd/specs/formdesigner-boolean-yes-no.spec.md
**Reviewed files**: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py
**Overall verdict**: ⚠ Approved with notes

---

## Summary
BOOLEAN now emits two `form.radio` widgets sharing one name with drawn Yes/No text, reads the RAW prefill (fixing the `bool("False")` latent bug), and adds `required` only when requested. Matches the spec and the tests confirm the AcroForm structure.

## Findings

### 🔴 Critical (must fix before merge)
- none

### 🟡 Major (should fix)
- none

### 🟢 Minor / Suggestions
- **pdf.py:419-434** — Choice spacing is computed from `c.stringWidth` rather than the fixed 30 mm of the task blueprint; this is a harmless improvement. Text baseline is `y` (blueprint suggested `y + 0.8*mm`); alignment with the 4 mm widget is cosmetic and was not checked visually.
- **pdf.py:430-431** — `c.setFont` is called inside the loop on every iteration; trivial, could be hoisted. Note it also leaves the canvas font changed for later fields, which already set their own font in this renderer.
- **pdf.py:99-118** — duplicate of the HTML5 normalizer (see TASK-5162 note).

## Deferred Findings

| Severity | Title | Issue ID | Filed By |
|----------|-------|----------|----------|
| none     | n/a   | n/a      | n/a      |

> No confirmed 🔴/🟡 findings, so nothing to file.

## Acceptance Criteria Check
| Criterion | Status | Notes |
|-----------|--------|-------|
| Radio group with Yes and No kids, visible text, no lone checkbox | ✅ | test_pdf_boolean_has_yes_no_choices (Ff radio bit, 2 kids, text via pypdf) |
| Prefilled False selects No; no prefill selects neither | ✅ | bool and 'False' string both covered |
| required only when field.required | ✅ | Ff bit 2 asserted both ways |
| Existing test_pdf.py passes; ruff clean | ⚠ | tests pass; `ruff` not available on PATH for the reviewer shell |

## Adversarial Cross-Check
Reviewer: external `codex` (neutral brief: diff origin/dev...HEAD + requirement, no conclusions supplied). Output: `/tmp/claude-1000/sdd-logs/reviews/feat800-codex.txt`.

| Finding | Disposition | Reason |
|---------|-------------|--------|
| No concrete bugs/regressions reported | n/a | Its claim of "22 focused tests passed" was spot-checked: the two new test files hold 17 (html5) + 5 (pdf) = 22 tests, and my own run of `tests/unit/renderers` + `tests/unit/test_renderers.py` gave 269 passed. Evidence is consistent. |

## Positive Highlights
- Smallest possible blast radius: shared radio markup reused instead of a third variant.
- Prefill normalization handles `bool` before `int`, avoiding the classic `True == 1` trap.
- Tests exercise real output (HTML strings, parsed PDF) rather than mocks.
