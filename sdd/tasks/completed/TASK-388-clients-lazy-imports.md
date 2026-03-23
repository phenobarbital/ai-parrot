# TASK-388: Core Clients Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

Core client files (`parrot/clients/base.py`, `parrot/clients/gpt.py`) currently import heavy optional dependencies (pydub, pytesseract) at module level, causing import failures when those packages aren't installed. This task converts them to lazy imports using the utility from TASK-386.

Note: pandas stays in core per owner decision, so `parrot/clients/base.py` pandas import remains as-is.

Implements: Spec Module 3 — Core Clients Lazy Imports.

---

## Scope

- In `parrot/clients/base.py`: convert `pydub` import to lazy import using `lazy_import("pydub", extra="audio")`.
- In `parrot/clients/gpt.py`: convert `pytesseract` import to lazy import using `lazy_import("pytesseract", extra="ocr")`.
- Use `from __future__ import annotations` + `TYPE_CHECKING` for type hints that reference these modules.
- Verify `from parrot.clients import ...` works without pydub/pytesseract installed.

**NOT in scope**: Changing pandas imports (stays in core). Changing any tool files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/base.py` | MODIFY | Lazy-import pydub |
| `parrot/clients/gpt.py` | MODIFY | Lazy-import pytesseract |

---

## Implementation Notes

### Pattern to Follow
```python
from parrot._imports import lazy_import

# Remove: import pydub / from pydub import AudioSegment
# Replace with lazy import inside the method that uses it:

class SomeClient:
    def process_audio(self, audio_data):
        pydub = lazy_import("pydub", extra="audio")
        segment = pydub.AudioSegment(...)
```

### Key Constraints
- Do not change any logic — only move imports from module-level to method-level
- Preserve all existing functionality when deps are installed
- Clear error message when deps are missing

### References in Codebase
- `parrot/_imports.py` — the utility from TASK-386
- `parrot/clients/base.py:31` — current pandas import (KEEP)
- `parrot/clients/gpt.py` — current pytesseract import location

---

## Acceptance Criteria

- [ ] `from parrot.clients.base import *` works without pydub installed
- [ ] `from parrot.clients.gpt import *` works without pytesseract installed
- [ ] Audio processing still works when pydub is installed
- [ ] OCR still works when pytesseract is installed
- [ ] Missing dep raises clear error: `pip install ai-parrot[audio]` / `pip install ai-parrot[ocr]`
- [ ] All existing tests pass: `pytest tests/ -v -k "client"` (with deps installed)

---

## Test Specification

```python
# tests/test_lazy_imports.py (append to existing)
import pytest
from unittest.mock import patch
import builtins

class TestClientLazyImports:
    def test_base_client_import_without_pydub(self):
        """base client module imports without pydub."""
        original_import = builtins.__import__
        def block_pydub(name, *args, **kwargs):
            if name == "pydub" or name.startswith("pydub."):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=block_pydub):
            import importlib
            import parrot.clients.base
            importlib.reload(parrot.clients.base)
            # Should not raise

    def test_gpt_client_import_without_pytesseract(self):
        """GPT client module imports without pytesseract."""
        original_import = builtins.__import__
        def block_pytesseract(name, *args, **kwargs):
            if name == "pytesseract" or name.startswith("pytesseract."):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=block_pytesseract):
            import importlib
            import parrot.clients.gpt
            importlib.reload(parrot.clients.gpt)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-388-clients-lazy-imports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
