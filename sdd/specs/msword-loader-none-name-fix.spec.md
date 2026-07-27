---
id: FEAT-385
slug: msword-loader-none-name-fix
title: "Fix MSWordLoader NoneType crash on para.style.name (NAV-9269)"
type: hotfix
base_branch: dev
status: approved
jira_key: NAV-9269
created_at: "2026-07-27T00:00:00Z"
author: jlara@trocglobal.com
---

# FEAT-385: Fix MSWordLoader NoneType crash on para.style.name

**Feature ID**: FEAT-385
**Date**: 2026-07-27
**Author**: jlara@trocglobal.com
**Status**: approved
**Jira**: NAV-9269
**Type**: hotfix
**Base branch**: dev

---

## 1. Motivation & Business Requirements

### Problem Statement

`MSWordLoader.docx_to_markdown()` crashes on `.docx` files that contain a
paragraph whose `style` attribute is `None`. python-docx returns `None` for
paragraphs whose applied style has been deleted from or is otherwise absent
in the document's style table. The crash surfaces as:

```
[INFO]  2026-07-27 16:56:53,148 Parrot.Loaders.MSWordLoader(docx.py:79) :: Loading Word file: /tmp/Security Training Update (PEAK) Final-en-US.docx
[ERROR] 2026-07-27 16:56:53,161 Parrot.Loaders.MSWordLoader(abstract.py:586) :: Task error: 'NoneType' object has no attribute 'name'
[ERROR] 2026-07-27 16:56:53,161 Parrot.Loaders.MSWordLoader(abstract.py:597) :: Error loading 'NoneType' object has no attribute 'name'
```

The `AttributeError` propagates through the `controlled_task` coroutine in
`packages/ai-parrot/src/parrot/loaders/abstract.py` (lines 586 and 597),
causing the entire document load to fail and return nothing to the caller.

Jira: NAV-9269

### Goals
- Guard the `para.style.name` access so that paragraphs with a `None` style
  are treated as body text rather than crashing the loader.
- Add a pytest fixture-based test that reproduces the crash scenario and
  verifies the fix.
- Zero regression on existing loader behaviour.

### Non-Goals (explicitly out of scope)
- Changing the chunking behaviour introduced in TASK-638 (double-chunking fix).
- Handling `None` styles in table cells (those are processed separately via
  `cell.text` and do not call `.style.name`).
- Modifying `abstract.py` — the fix belongs in the loader itself.

---

## 2. Root Cause Analysis

**File**: `packages/ai-parrot-loaders/src/parrot_loaders/docx.py`, line 23

```python
# Unconditional .name access on a potentially-None style object
style = para.style.name.lower()
```

`python-docx`'s `Paragraph.style` property can return `None` when the named
style referenced by the paragraph is not present in the document's style
definitions. Calling `.name` on `None` raises:

```
AttributeError: 'NoneType' object has no attribute 'name'
```

The stack then unwinds into the `controlled_task` coroutine in `abstract.py`
where it is logged at ERROR level (lines 586 and 597) and the document load
returns nothing.

---

## 3. Fix Approach

Guard the `.name` access with an explicit `None` check before calling
`.lower()`:

```python
# Before (line 23 of docx.py)
style = para.style.name.lower()

# After
style = para.style.name.lower() if para.style is not None else ""
```

When the style is absent, the paragraph is treated as body text (the `else`
branch of the existing `if "heading" in style` / `elif style.startswith("list")`
chain), which is the correct graceful-degradation behaviour.

### Component Diagram
```
docx.Document(path)
  └── for para in doc.paragraphs:
        para.style  ── None? ──→ style = ""  (body text path)
                    └─ present ─→ style = para.style.name.lower()
```

---

## 4. Affected Files

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — one-line guard
  at the top of the `for para in doc.paragraphs:` loop (line 23).
- `tests/loaders/test_mswordloader_none_name_fix.py` — new test file covering
  the `para.style is None` case.

---

## 5. Test Specification

### Unit Tests
| Test | Description |
|---|---|
| `test_none_style_paragraph_treated_as_body` | Para with `style=None` renders as plain text |
| `test_heading_style_still_works` | Heading paragraphs still produce `# heading` |
| `test_list_style_still_works` | List paragraphs still produce `- item` |
| `test_mixed_doc_with_none_style` | Doc with mix of None and valid styles loads without crash |

### Test Data / Fixtures
```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_paragraph_none_style():
    """Return a mock docx Paragraph whose .style is None."""
    para = MagicMock()
    para.style = None
    para.text = "Body paragraph without style"
    return para
```

---

## 6. Acceptance Criteria

- [ ] `ruff check .` exits 0 (no lint regressions introduced).
- [ ] `pytest -q` exits 0 (all existing tests continue to pass).
- [ ] `docx_to_markdown()` no longer raises `AttributeError` when a
      paragraph's `.style` is `None`.
- [ ] Paragraphs with `None` style are emitted as plain body text.
- [ ] Existing heading and list style rendering is unchanged.
- [ ] A new pytest test (`tests/loaders/test_mswordloader_none_name_fix.py`)
      covers the `para.style is None` scenario and passes.
- [ ] `MSWordLoader` successfully loads a `.docx` file where at least one
      paragraph has a `None` style and returns a non-empty list of `Document`
      objects.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep the fix minimal: one conditional expression replacing the bare attribute access.
- Do NOT refactor surrounding logic — this is a surgical bugfix.
- Test using `unittest.mock.MagicMock` to simulate python-docx objects without
  requiring actual `.docx` files in the test suite.

### Known Risks / Gotchas
- python-docx `Paragraph.style` can also return a style object whose `.name`
  attribute is itself `None` in edge cases (corrupt documents). The guard
  `para.style.name.lower() if para.style is not None else ""` covers the
  `style is None` case but not the `style.name is None` case. A follow-up
  ticket can address the deeper guard if needed.
- The `markdownify` post-processing step (`md(markdown_text)`) is unaffected
  by this change.

---

## 8. Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | jlara@trocglobal.com | Initial hotfix spec for NAV-9269 |
