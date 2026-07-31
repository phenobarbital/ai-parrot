---
id: FEAT-384
slug: fix-msword-loader-none-style
title: "Fix MSWordLoader NoneType crash on para.style.name access (NAV-9269)"
type: feature
base_branch: dev
status: approved
jira: NAV-9269
created_at: "2026-07-27T00:00:00Z"
author: jlara@trocglobal.com
---

# Feature Specification: Fix MSWordLoader NoneType Crash on para.style.name

**Feature ID**: FEAT-384
**Date**: 2026-07-27
**Author**: jlara@trocglobal.com
**Status**: approved
**Target version**: current

---

## 1. Motivation & Business Requirements

### Problem Statement

`MSWordLoader.docx_to_markdown()` crashes on `.docx` files that contain a
paragraph whose `style` attribute is `None`. python-docx returns `None` for
paragraphs whose applied style has been deleted from or is otherwise absent
in the document's style table. The crash surfaces as:

```
[INFO]  Loading Word file: /tmp/Security Training Update (PEAK) Final-en-US.docx
[ERROR] Task error: 'NoneType' object has no attribute 'name'
[ERROR] Error loading 'NoneType' object has no attribute 'name'
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

## 2. Architectural Design

### Overview

A single one-line guard in `docx_to_markdown()` eliminates the crash.
When `para.style` is `None`, fall back to an empty string so the existing
`if "heading" in style` / `elif style.startswith("list")` chain treats the
paragraph as body text.

```python
# Before (line 23 of docx.py)
style = para.style.name.lower()

# After
style = para.style.name.lower() if para.style is not None else ""
```

### Component Diagram
```
docx.Document(path)
  └── for para in doc.paragraphs:
        para.style  ── None? ──→ style = ""  (body text path)
                    └─ present ─→ style = para.style.name.lower()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `MSWordLoader.docx_to_markdown()` | modify | one-line guard at para loop head |
| `AbstractLoader.controlled_task()` | none (read-only) | error handler that surfaces crash |

### Data Models

No new data models. `para.style` is a `docx.styles.style._ParagraphStyle` or
`None` as returned by python-docx.

### New Public Interfaces

None. The fix is internal to `docx_to_markdown()`.

---

## 3. Module Breakdown

### Module 1: None-style guard in MSWordLoader
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/docx.py`
- **Responsibility**: Guard `para.style.name` access; treat absent styles as body text.
- **Depends on**: none

### Module 2: pytest coverage for None-style scenario
- **Path**: `tests/loaders/test_mswordloader_none_style.py`
- **Responsibility**: Reproduce the crash with a mock docx Document and verify the fix.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_none_style_paragraph_treated_as_body` | Module 2 | Para with `style=None` renders as plain text |
| `test_heading_style_still_works` | Module 2 | Heading paragraphs still produce `# heading` |
| `test_list_style_still_works` | Module 2 | List paragraphs still produce `- item` |
| `test_mixed_doc_with_none_style` | Module 2 | Document with mix of None and valid styles loads without crash |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_paragraph(style_name):
    """Return a mock docx Paragraph whose .style.name returns style_name,
    or whose .style is None when style_name is None."""
    para = MagicMock()
    if style_name is None:
        para.style = None
    else:
        para.style.name = style_name
    return para
```

---

## 5. Acceptance Criteria

- [ ] `docx_to_markdown()` no longer raises `AttributeError` when a paragraph's
      `.style` is `None`.
- [ ] Paragraphs with `None` style are emitted as plain body text.
- [ ] Existing heading and list style rendering is unchanged.
- [ ] `pytest tests/loaders/test_mswordloader_none_style.py -v` passes.
- [ ] No other test suite regresses: `pytest tests/loaders/ -v`.

---

## 6. Codebase Contract

### Verified Imports
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py
from typing import List
from pathlib import PurePath
import re
import mammoth
import docx
from markdownify import markdownify as md
from parrot.stores.models import Document
from parrot.loaders.abstract import AbstractLoader
```

### Existing Class Signatures
```python
# packages/ai-parrot-loaders/src/parrot_loaders/docx.py:11
class MSWordLoader(AbstractLoader):
    extensions: List[str] = ['.doc', '.docx']  # line 15

    def docx_to_markdown(self, docx_path):       # line 17
        # line 22-23: THE CRASH SITE
        for para in doc.paragraphs:
            style = para.style.name.lower()       # line 23 — None-unsafe

    async def _load(self, path: PurePath, **kwargs) -> List[Document]:  # line 70
```

```python
# packages/ai-parrot/src/parrot/loaders/abstract.py:581
async def controlled_task(task):
    async with self.semaphore:
        try:
            return await task
        except Exception as e:
            self.logger.error(f"Task error: {e}")    # line 586
            return e
# line 597: self.logger.error(f"Error loading {res}")
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| guard expression | `para.style` attribute | conditional expression | `docx.py:23` |

### Does NOT Exist (Anti-Hallucination)
- ~~`para.style.get_name()`~~ — does not exist; use `.name`
- ~~`para.style_name`~~ — not a real attribute on python-docx `Paragraph`
- ~~`MSWordLoader.safe_style()`~~ — no such helper method exists
- ~~`AbstractLoader.handle_none_style()`~~ — does not exist

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
  ticket can address the deeper guard if needed; for now match the reported
  crash exactly.
- The `markdownify` post-processing step (`md(markdown_text)`) is unaffected
  by this change.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `python-docx` | `>=0.8` | Core `.docx` parsing |
| `markdownify` | any | HTML → Markdown post-processing |

---

## 8. Open Questions

- [x] Is the fix limited to `para.style is None` or also `para.style.name is None`? — *Resolved*: Guard only `para.style is None` to match the reported crash exactly. A deeper guard is out of scope.
- [x] Should the fix live in `docx.py` or `abstract.py`? — *Resolved*: `docx.py` — the fix is loader-specific; `abstract.py` already handles generic exceptions.

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks)
- Task 1 (guard) and Task 2 (tests) are sequential — tests depend on the fix.
- No cross-feature dependencies.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-27 | jlara@trocglobal.com | Initial spec for NAV-9269 |
