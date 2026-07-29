# TASK-1949: Add pytest coverage for para.style is None scenario (NAV-9269)

**Feature**: msword-loader-none-name-fix
**Feature ID**: FEAT-385
**Spec**: sdd/specs/msword-loader-none-name-fix.spec.md
**Status**: [x] done
**Priority**: high
**Effort**: S
**Depends-on**: TASK-1948
**Assigned-to**: unassigned
**Jira**: NAV-9269

---

## Context

After the one-line guard is applied in TASK-1948, this task adds a pytest
test file that exercises the `para.style is None` path to prevent regressions.

## Scope

Create `tests/loaders/test_mswordloader_none_name_fix.py` with tests that:
1. Confirm `docx_to_markdown()` does not crash when a paragraph has `style=None`.
2. Confirm the None-style paragraph is emitted as plain body text.
3. Confirm heading and list styles still render correctly (regression guard).
4. Confirm a mixed document (some None styles, some valid) loads successfully.

## Files to Create

- `tests/loaders/test_mswordloader_none_name_fix.py`

## Implementation Notes

Use `unittest.mock.MagicMock` to simulate python-docx objects — no actual
`.docx` file needed. Patch `docx.Document` in the loader's module namespace:
`parrot_loaders.docx.docx.Document`.

```python
from unittest.mock import MagicMock, patch
import pytest
from parrot_loaders.docx import MSWordLoader


def _make_para(style_name, text):
    """Helper: create a mock paragraph."""
    para = MagicMock()
    if style_name is None:
        para.style = None
    else:
        para.style = MagicMock()
        para.style.name = style_name
    para.text = text
    return para


def _make_doc(paragraphs, tables=None):
    doc = MagicMock()
    doc.paragraphs = paragraphs
    doc.tables = tables or []
    return doc
```

## Reference Code

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — the function under test
- `tests/loaders/test_docx_loader_fix.py` — existing test patterns to follow

## Test Specification

```python
def test_none_style_paragraph_treated_as_body():
    """Para with style=None must not crash and renders as body text."""

def test_heading_style_still_works():
    """Heading paragraphs still produce markdown headings."""

def test_list_style_still_works():
    """List paragraphs still produce markdown list items."""

def test_mixed_doc_with_none_style():
    """Document mixing None and valid styles loads without error."""
```

## Acceptance Criteria

- [ ] `tests/loaders/test_mswordloader_none_name_fix.py` exists and contains
      all four test cases above.
- [ ] `pytest tests/loaders/test_mswordloader_none_name_fix.py -v` passes (all
      4 tests green).
- [ ] `pytest tests/loaders/ -q` passes (no regressions).
- [ ] `ruff check tests/loaders/test_mswordloader_none_name_fix.py` exits 0.

## Output

When complete:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/msword-loader-none-name-fix.json` TASK-1949 status to "done"
3. Commit with message: `test: add coverage for para.style None in MSWordLoader (NAV-9269)`

### Completion Note
**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-07-27
**Notes**: Created `tests/loaders/test_mswordloader_none_name_fix.py` with 7 tests (one extra: `test_none_style_name_treated_as_body` for the `style.name is None` edge case). All 7 tests pass. `ruff check` exits 0.
**Deviations from spec**: 7 tests instead of 4 — added `test_none_style_no_attribute_error` (explicit `pytest.raises` guard) and `test_load_succeeds_with_none_style_paragraph` (async `_load()` integration), plus the `style.name is None` edge case test.
