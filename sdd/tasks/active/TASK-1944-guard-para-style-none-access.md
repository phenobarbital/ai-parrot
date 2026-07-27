# TASK-1944: Guard para.style None access in MSWordLoader.docx_to_markdown

**Feature**: fix-msword-loader-none-name
**Feature ID**: FEAT-383
**Spec**: sdd/specs/fix-msword-loader-none-name.spec.md
**Status**: [ ] pending
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

`MSWordLoader.docx_to_markdown()` crashes when a paragraph's `.style` is
`None` because python-docx returns `None` for styles absent from the
document's style table.  The crash (`AttributeError: 'NoneType' object has
no attribute 'name'`) propagates through the async task runner and causes the
entire document load to fail silently.

Jira: NAV-9269

## Scope

Apply a one-line None-guard at line 23 of
`packages/ai-parrot-loaders/src/parrot_loaders/docx.py` so that
`docx_to_markdown` never calls `.name` on a `None` style object.

## Files to Create/Modify

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — change line 23

## Implementation Notes

Replace:
```python
style = para.style.name.lower()
```
with:
```python
style = para.style.name.lower() if para.style is not None else ""
```

When `style` is `""` the paragraph falls through to the plain-text `else`
branch of the existing heading/list dispatch, which is the correct graceful
degradation.

## Reference Code

- `packages/ai-parrot-loaders/src/parrot_loaders/docx.py` — full file context
- `packages/ai-parrot/src/parrot/loaders/abstract.py` lines 580-603 — async
  task runner that catches and logs the AttributeError

## Acceptance Criteria

- [ ] Line 23 of `docx.py` uses the guarded form shown above.
- [ ] `ruff check .` exits 0.
- [ ] `pytest -q` exits 0 (no regressions in existing loader tests).

## Output

When complete, move this file to `sdd/tasks/completed/` and update
`sdd/tasks/index/fix-msword-loader-none-name.json` status to "done".

### Completion Note

(Agent fills this in when done)
