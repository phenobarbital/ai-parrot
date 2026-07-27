# TASK-1946: Guard para.style None access in MSWordLoader.docx_to_markdown

**Feature**: FEAT-384 — Fix MSWordLoader NoneType crash on para.style.name access (NAV-9269)
**Spec**: `sdd/specs/fix-msword-loader-none-style.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`MSWordLoader.docx_to_markdown()` crashes on `.docx` files that contain a
paragraph whose `style` attribute is `None`. python-docx returns `None` for
paragraphs whose applied style is absent from the document's style table.
The crash (`AttributeError: 'NoneType' object has no attribute 'name'`)
propagates through the async task runner and causes the entire document load
to fail silently. This task applies the one-line surgical fix.

Jira: NAV-9269

---

## Scope

- Replace the bare `para.style.name.lower()` call at line 23 of
  `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` with a
  None-guarded conditional expression.
- No other logic changes in the file.

**NOT in scope**: modifying `abstract.py`, table cell handling, or the
chunking pipeline.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` | MODIFY | Replace line 23 with guarded expression |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py:1-8
from typing import List
from pathlib import PurePath
import re
import mammoth
import docx
from markdownify import markdownify as md
from parrot.stores.models import Document
from parrot.loaders.abstract import AbstractLoader
```

### Existing Signatures to Use
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py:17-34
def docx_to_markdown(self, docx_path):
    doc = docx.Document(docx_path)
    md_lines = []
    for para in doc.paragraphs:
        style = para.style.name.lower()   # line 23 — CHANGE THIS LINE
        text = para.text.strip()
        if not text:
            continue
        if "heading" in style:
            level = re.sub(r"[^\d]", "", style) or "1"
            md_lines.append(f"{'#' * int(level)} {text}")
        elif style.startswith("list"):
            md_lines.append(f"- {text}")
        else:
            md_lines.append(text)
```

### Does NOT Exist
- ~~`para.style.get_name()`~~ — does not exist; use `.name`
- ~~`para.style_name`~~ — not a real attribute on python-docx `Paragraph`
- ~~`MSWordLoader.safe_style()`~~ — no such helper method exists

---

## Implementation Notes

### Exact Change

Replace line 23:
```python
# Before
style = para.style.name.lower()

# After
style = para.style.name.lower() if para.style is not None else ""
```

That is the entire change. Do NOT modify any other lines.

### Key Constraints
- One-line change only — no refactoring.
- Do not alter the surrounding `if/elif/else` block.
- Do not add any helper methods.

---

## Acceptance Criteria

- [ ] Line 23 of `docx.py` uses the `if para.style is not None else ""` guard.
- [ ] The file is syntactically valid (no import changes, no indentation errors).
- [ ] `pytest tests/loaders/ -v` passes (or there are no existing loader tests to break).

---

## Test Specification

Covered by TASK-1947. No new tests are required in this task.

---

## Agent Instructions

1. **Read** `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` to confirm line 23.
2. **Apply** the one-line guard change.
3. **Verify** the file is syntactically valid.
4. **Move** this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
