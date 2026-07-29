---
type: Wiki Overview
title: 'TASK-1029: Update `FormStorage.list_forms()` ABC docstring contract'
id: doc:sdd-tasks-completed-task-1029-formstorage-abc-list-forms-docstring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 4 of the spec relies on `list_forms()` returning richer entries
relates_to:
- concept: mod:parrot
  rel: mentions
---

# TASK-1029: Update `FormStorage.list_forms()` ABC docstring contract

**Feature**: FEAT-148 — Enriched List of Created Forms in parrot-formdesigner
**Spec**: `sdd/specs/formbuilder-list-created-forms.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`FormStorage` is the abstract base for persistence backends.
Module 4 of the spec relies on `list_forms()` returning richer entries
than the current docstring promises (`{"form_id", "title"}`).

This task updates the ABC's docstring contract so future implementations
know they SHOULD include `version`, `description`, and `created_at`
(ISO-8601 string) when available. **No signature change**, no behaviour
change — only documentation.

Implements Module 3 of the spec.

---

## Scope

- Update only the docstring of `FormStorage.list_forms` to describe the
  expected dict keys.
- The docstring MUST state that:
  - `form_id` and `version` are required keys.
  - `title`, `description`, `created_at` are optional but SHOULD be
    populated when the backend has them.
  - `created_at` is an ISO-8601 string (`datetime.isoformat()`).

**NOT in scope**:
- Changing the method signature, return type annotation, or behaviour.
- Modifying `PostgresFormStorage.list_forms()` (covered by TASK-1030).
- Adding new abstract methods.
- Refactoring `FormRegistry.load_from_storage()` (it already iterates
  on `form_id` keys — backwards-compatible).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py` | MODIFY | Update `FormStorage.list_forms` docstring (lines ~84-91) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

No new imports.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormStorage(ABC):                                   # line 29
    @abstractmethod
    async def save(self, form, style=None) -> str: ...    # line 39
    @abstractmethod
    async def load(self, form_id, version=None) -> FormSchema | None: ...  # line 56
    @abstractmethod
    async def delete(self, form_id) -> bool: ...          # line 73
    @abstractmethod
    async def list_forms(self) -> list[dict[str, str]]:   # line 85
        """List all persisted forms.

        Returns:
            List of dicts with at minimum {"form_id": ..., "title": ...}.
        """
```

The current docstring (lines 86-91) is what this task replaces.

### Does NOT Exist

- ~~`FormStorage.list_descriptors()`~~ — does not exist; do not add.
- ~~`FormStorage.list_form_ids()`~~ — only on `FormRegistry`, not on
  `FormStorage`.
- ~~A `FormDescriptor` Pydantic model~~ — not introduced by this feature
  (the response is a plain dict in the handler).

---

## Implementation Notes

### Pattern to Follow

Replace the existing 4-line docstring with a richer description that
documents the optional keys. Keep it Google-style (matching the rest of
this file).

### Key Constraints

- Do NOT change the return type annotation `list[dict[str, str]]`.
  (Strict typing of the inner dict would force a breaking change on
  downstream code; we leave the annotation loose and document the
  contract in prose.)
- Do NOT add `Args:` — the method takes no arguments.
- Keep the existing single-line summary.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot/formdesigner/services/storage.py:213-243`
  — current concrete implementation that this docstring describes.

---

## Acceptance Criteria

- [ ] `FormStorage.list_forms` docstring lists every supported key:
      `form_id`, `version`, `title`, `description`, `created_at`.
- [ ] Docstring marks `form_id` and `version` as required and the
      others as optional.
- [ ] Docstring mentions that `created_at` is an ISO-8601 string.
- [ ] Method signature unchanged (`async def list_forms(self) -> list[dict[str, str]]`).
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py`.
- [ ] Existing tests pass: `pytest packages/parrot-formdesigner/tests/unit/ -v -k "registry or storage"` (no regressions).

---

## Test Specification

A lightweight contract test — add to a sensible spot
(e.g. `tests/unit/test_storage_list.py` from TASK-1031, or extend
`tests/unit/test_core_models.py`):

```python
def test_form_storage_list_forms_docstring_contract():
    """FormStorage.list_forms docstring documents the rich keys."""
    from parrot.formdesigner.services.registry import FormStorage
    doc = FormStorage.list_forms.__doc__ or ""
    for key in ("form_id", "version", "title", "description", "created_at"):
        assert key in doc, f"docstring should mention {key}"
    assert "ISO-8601" in doc or "isoformat" in doc.lower()
```

(This test can live in TASK-1031's new test file — coordinate with that
task's author if both run sequentially.)

---

## Agent Instructions

1. **Read the spec** §3 Module 3.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — `grep -n "async def list_forms"
   packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py`
   should return line 85.
4. **Edit** the docstring only.
5. **Run** linter on the file.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update** `sdd/tasks/index/formbuilder-list-created-forms.json` →
   `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Updated `FormStorage.list_forms` docstring to document required keys (`form_id`, `version`) and optional keys (`title`, `description`, `created_at`) with ISO-8601 note. Also removed pre-existing unused `Any` import from `typing`. Ruff check clean.

**Deviations from spec**: none
