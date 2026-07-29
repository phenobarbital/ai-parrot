---
id: FEAT-382
slug: fix-mswordloader-none-name
title: "Fix MSWordLoader NoneType error on .name attribute"
type: feature
base_branch: dev
status: draft
jira: NAV-9270
created_at: "2026-07-27T19:33:00Z"
author: jlara@trocglobal.com
---

# FEAT-382: Fix MSWordLoader NoneType error on .name attribute

## Motivation

`MSWordLoader.docx_to_markdown()` crashes on any `.docx` file that contains
a paragraph whose style attribute is `None` (python-docx returns `None` for
paragraphs whose applied style has been deleted or is otherwise unavailable in
the document's style table).  The crash surfaces as:

```
[ERROR] Task error: 'NoneType' object has no attribute 'name'
[ERROR] Error loading 'NoneType' object has no attribute 'name'
```

The error propagates through the async task runner in
`parrot/loaders/abstract.py` (lines 586 and 597) and swallows the entire
document, returning nothing to the caller.

## Root Cause Analysis

File: `packages/ai-parrot-loaders/src/parrot_loaders/docx.py`

```python
# Line 23 — unconditional .name access on potentially-None style
style = para.style.name.lower()
```

`python-docx` documents `para.style` can be `None` when the paragraph's
named style is not present in the document's style definitions.  Calling
`.name` on `None` raises `AttributeError`.

## Fix Approach

Guard the `.name` access before calling `.lower()`:

```python
style = para.style.name.lower() if para.style is not None else ""
```

When the style is absent the paragraph is treated as body text (the `else`
branch of the existing `if "heading" in style` / `elif style.startswith("list")`
chain), which is the correct fallback behaviour.

## Affected File

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — one-line change at
  the top of the `for para in doc.paragraphs:` loop.

## Acceptance Criteria

- [ ] `ruff check .` exits 0 (no lint regressions introduced).
- [ ] `pytest -q` exits 0 (all existing tests continue to pass).
- [ ] A new pytest test (`tests/loaders/test_mswordloader_none_style.py`) covers
      the `para.style is None` case and passes.
- [ ] `MSWordLoader` successfully loads the previously-failing file (or any docx
      where at least one paragraph has a `None` style) and returns a non-empty
      list of `Document` objects.
