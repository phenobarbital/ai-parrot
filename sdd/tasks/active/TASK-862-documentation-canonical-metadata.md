# TASK-862: Documentation for canonical metadata shape

**Feature**: FEAT-125 — AI-Parrot Loaders Metadata Standardization
**Spec**: `sdd/specs/ai-parrot-loaders-metadata-standarization.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-855, TASK-856, TASK-857, TASK-858, TASK-859, TASK-860
**Assigned-to**: unassigned

---

## Context

This task implements **Module 6** of the spec. It documents the canonical
metadata shape, the `document_meta` contract, and the `language`/`title`
defaults. This is the foundation for the upcoming contextual-retrieval
feature and must be discoverable by developers writing new loaders.

---

## Scope

- Create or update loader documentation under `docs/` to cover:
  1. The canonical `Document.metadata` shape (all standard fields + `document_meta`).
  2. The `document_meta` contract: exactly 5 keys, closed shape, no extras.
  3. The `language` and `title` defaults and how to override them.
  4. The rule: "extras live at top level, never in `document_meta`".
  5. How to write a new loader that complies (use `create_metadata`, pass extras as `**kwargs`).
  6. Brief note that this is the foundation for contextual-retrieval embedding headers.

- Add inline docstrings to `create_metadata`, `_derive_title`, and `_validate_metadata` in `abstract.py` if not already present from TASK-855.

**NOT in scope**: Code changes. Test changes. API changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/loaders-metadata.md` | CREATE | Main documentation page for canonical metadata |
| `packages/ai-parrot/src/parrot/loaders/abstract.py` | MODIFY | Add/improve docstrings on new methods if missing |

---

## Codebase Contract (Anti-Hallucination)

### Verified References
```python
# After all prior tasks, AbstractLoader has:
# __init__(..., language: str = 'en', ...)
# self.language: str
# create_metadata(path, doctype, source_type, doc_metadata, *, language=None, title=None, **kwargs)
# _derive_title(path) -> str
# _validate_metadata(metadata) -> dict
```

### Does NOT Exist
- ~~`docs/loaders.md`~~ — verify if a loader docs page already exists; may need to create from scratch.
- ~~`Document.document_meta`~~ — no typed accessor; document using `metadata["document_meta"]` dict access.

---

## Implementation Notes

### Documentation structure
```markdown
# Loader Metadata Standard

## Canonical Shape
Every `Document.metadata` dict produced by a loader follows this shape: ...

## document_meta Contract
The `document_meta` sub-dict contains exactly 5 keys: ...

## Writing a New Loader
When implementing a new loader: ...

## Contextual Retrieval
This metadata shape is the foundation for upcoming contextual-retrieval
embedding headers that prefix each chunk with source context.
```

### Key Constraints
- Use Google-style docstrings (per project convention).
- Keep documentation concise — developers should be able to read it in 5 minutes.
- Include a concrete example of `create_metadata` usage with extras.

---

## Acceptance Criteria

- [ ] `docs/loaders-metadata.md` exists with canonical shape documentation
- [ ] Docstrings present on `create_metadata`, `_derive_title`, `_validate_metadata`
- [ ] Documentation explains the closed-shape `document_meta` rule
- [ ] Documentation explains `language` and `title` defaults
- [ ] Documentation includes a "Writing a New Loader" guide section
- [ ] Documentation mentions contextual-retrieval as the motivation

---

## Test Specification

No code tests required. Documentation review by human.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-855 through TASK-860 are in `tasks/completed/`
3. **Check if `docs/loaders.md` or similar exists**: `find docs/ -name "*loader*"`
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-862-documentation-canonical-metadata.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
