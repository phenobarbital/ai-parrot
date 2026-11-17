# Code Review: TASK-5162 — HTML5 renderer — BOOLEAN renders as Yes / No radios

**Spec**: sdd/specs/formdesigner-boolean-yes-no.spec.md
**Reviewed files**: packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py
**Overall verdict**: ⚠ Approved with notes

---

## Summary
BOOLEAN now goes through `_render_boolean_radio_group` on both the form-field branch and the registry (`_BooleanRenderer`); the checkbox map entry and the dead `_render_checkbox` are removed, and `_render_radio_group(options=None)` keeps SELECT output identical. Correct and minimal; only minor notes.

## Findings

### 🔴 Critical (must fix before merge)
- none

### 🟡 Major (should fix)
- none

### 🟢 Minor / Suggestions
- **html5.py:39-62 / pdf.py:99-118** — `_normalize_boolean` and `pdf._boolean_selected` are byte-for-byte duplicates. Spec allowed either option ("implementer picks ONE") and the independent-renderers choice is recorded, so this is accepted debt, not a defect.
- **html5.py:1520-1543** — the REST-arguments `boolean → checkbox` path still emits `type="checkbox"`. This is explicitly NG1 (out of scope); noted only so nobody reads the "no checkbox" AC as covering it.
- **html5.py:~817** — `label_text` is concatenated unescaped, same as the SELECT branch it mirrors; no new exposure introduced.

## Deferred Findings

| Severity | Title | Issue ID | Filed By |
|----------|-------|----------|----------|
| none     | n/a   | n/a      | n/a      |

> No confirmed 🔴/🟡 findings, so nothing to file.

## Acceptance Criteria Check
| Criterion | Status | Notes |
|-----------|--------|-------|
| No BOOLEAN path emits type=checkbox | ✅ | type map entry removed, registry + form branch both radios; verified by test_boolean_renders_two_radios_yes_no and test_boolean_registry_path_matches |
| None → none checked; True/'true'/1 → Yes; False/'false'/0 → No | ✅ | `is bool` handled before the int/str sets, so no bool/int confusion |
| required emitted; label once; data-depends-on unchanged | ✅ | required comes from shared radio markup; wrapper div untouched |
| SELECT render_as: radio unchanged | ✅ | exact-string golden test passes |
| ruff clean; test_renderers.py passes | ⚠ | test_renderers.py passes (269 total). `ruff` is not on PATH in this worktree shell, so lint was not independently re-run by the reviewer |

## Adversarial Cross-Check
Reviewer: external `codex` (neutral brief: diff origin/dev...HEAD + requirement, no conclusions supplied). Output: `/tmp/claude-1000/sdd-logs/reviews/feat800-codex.txt`.

| Finding | Disposition | Reason |
|---------|-------------|--------|
| No concrete bugs/regressions reported | n/a | Its claim of "22 focused tests passed" was spot-checked: the two new test files hold 17 (html5) + 5 (pdf) = 22 tests, and my own run of `tests/unit/renderers` + `tests/unit/test_renderers.py` gave 269 passed. Evidence is consistent. |

## Positive Highlights
- Smallest possible blast radius: shared radio markup reused instead of a third variant.
- Prefill normalization handles `bool` before `int`, avoiding the classic `True == 1` trap.
- Tests exercise real output (HTML strings, parsed PDF) rather than mocks.
