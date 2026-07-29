# TASK-1942: Guard para.style None access in MSWordLoader.docx_to_markdown

**Feature**: fix-mswordloader-none-name
**Feature ID**: FEAT-382
**Spec**: sdd/specs/fix-mswordloader-none-name.spec.md
**Status**: [ ] pending | [ ] in-progress | [ ] done
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

`MSWordLoader.docx_to_markdown()` calls `para.style.name.lower()` on every
paragraph of a Word document. `python-docx` can return `None` for `para.style`
when the paragraph's named style is absent from the document's style table
(e.g. a style referenced by the paragraph was later deleted). This causes
`AttributeError: 'NoneType' object has no attribute 'name'` which propagates
through the async runner and drops the entire document.

The Jira ticket tracking this bug is **NAV-9270**.

## Scope

Apply a one-line guard to `docx_to_markdown()` so that a `None` style is
treated as an empty string (falling through to the plain-body-text branch).
No other logic changes are permitted by this task.

## Files to Create/Modify

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — change line 23

## Implementation Notes

Current (broken) code at line 23:
```python
style = para.style.name.lower()
```

Replace with:
```python
style = para.style.name.lower() if para.style is not None else ""
```

No imports need to change. The fix is a single expression replacement.

## Acceptance Criteria

- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` line 23 uses the
      guarded expression.
- [ ] `ruff check packages/ai-parrot-loaders/` exits 0.
- [ ] `pytest tests/loaders/ -q` exits 0 (existing tests still pass; new test
      added in TASK-1943 is not required here).

## Output

When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/fix-mswordloader-none-name.json` status to "done"
3. Add a brief completion note below.

### Completion Note

(Agent fills this in when done)
