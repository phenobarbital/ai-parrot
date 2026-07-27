---
id: FEAT-383
slug: fix-msword-loader-none-name
title: "Fix MSWordLoader NoneType error on .name attribute (NAV-9269)"
type: feature
base_branch: dev
status: draft
jira: NAV-9269
created_at: "2026-07-27T00:00:00Z"
author: jlara@trocglobal.com
---

# FEAT-383: Fix MSWordLoader NoneType error on .name attribute

## Motivation

`MSWordLoader.docx_to_markdown()` crashes on `.docx` files that contain a
paragraph whose `style` attribute is `None`.  python-docx returns `None` for
paragraphs whose applied style has been deleted from or is otherwise absent in
the document's style table.  The crash surfaces as:

```
[INFO]  Loading Word file: /tmp/Security Training Update (PEAK) Final-en-US.docx
[ERROR] Task error: 'NoneType' object has no attribute 'name'
[ERROR] Error loading 'NoneType' object has no attribute 'name'
```

The unhandled `AttributeError` propagates through the async task runner in
`packages/ai-parrot/src/parrot/loaders/abstract.py` (lines 586 and 597),
causing the entire document load to fail silently (returns nothing to the
caller).

Jira: NAV-9269

## Root Cause Analysis

File: `packages/ai-parrot-loaders/src/parrot_loaders/docx.py`, line 23

```python
# Unconditional .name access on a potentially-None style object
style = para.style.name.lower()
```

`python-docx`'s `Paragraph.style` property can return `None` when the named
style referenced by the paragraph is not present in the document's style
definitions.  Calling `.name` on `None` raises:

```
AttributeError: 'NoneType' object has no attribute 'name'
```

The stack then unwinds into the `controlled_task` coroutine in `abstract.py`
where it is logged at ERROR level and returned as an exception object rather
than a document list.

## Fix Approach

Guard the `.name` access with an explicit `None` check before calling
`.lower()`:

```python
style = para.style.name.lower() if para.style is not None else ""
```

When the style is absent, the paragraph is treated as body text (the `else`
branch of the existing `if "heading" in style` / `elif style.startswith("list")`
chain), which is the correct graceful-degradation behaviour.

## Affected Files

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — one-line change at
  the top of the `for para in doc.paragraphs:` loop (line 23).
- `tests/loaders/test_mswordloader_none_style.py` — new test file covering the
  `para.style is None` case.

## Acceptance Criteria

- [ ] `ruff check .` exits 0 (no lint regressions introduced).
- [ ] `pytest -q` exits 0 (all existing tests continue to pass).
- [ ] A new pytest test (`tests/loaders/test_mswordloader_none_style.py`) covers
      the `para.style is None` scenario and passes.
- [ ] `MSWordLoader` successfully loads a `.docx` file where at least one
      paragraph has a `None` style and returns a non-empty list of `Document`
      objects.
