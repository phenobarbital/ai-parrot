# TASK-375: Export EmbeddingRegistry from Embeddings Package

**Feature**: first-time-caching-embedding-model
**Feature ID**: FEAT-054
**Spec**: `sdd/specs/first-time-caching-embedding-model.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-374
**Assigned-to**: unassigned

---

## Context

> After the registry is implemented (TASK-374), it must be exported from the
> `parrot.embeddings` package so consumers can import it as
> `from parrot.embeddings import EmbeddingRegistry`.
> Implements Spec Module 3.

---

## Scope

- Update `parrot/embeddings/__init__.py` to export `EmbeddingRegistry`
- Ensure the import is lazy (no model loading at import time)
- Verify the public import path works

**NOT in scope**: The registry implementation (TASK-374), consumer refactoring (TASK-376–379).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/embeddings/__init__.py` | MODIFY | Add `EmbeddingRegistry` export |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/embeddings/__init__.py
from .registry import EmbeddingRegistry

supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}
```

### Key Constraints
- Import must not trigger model loading — the registry is lazy by design
- Keep existing `supported_embeddings` dict intact
- Do not uncomment the existing commented-out imports (they were commented for a reason)

### References in Codebase
- `parrot/embeddings/__init__.py` — current state with `supported_embeddings`

---

## Acceptance Criteria

- [ ] `from parrot.embeddings import EmbeddingRegistry` works
- [ ] `from parrot.embeddings import supported_embeddings` still works
- [ ] Importing the package does NOT load any models
- [ ] No circular import issues

---

## Test Specification

```python
def test_embedding_registry_importable():
    """Registry is importable from the embeddings package."""
    from parrot.embeddings import EmbeddingRegistry
    assert EmbeddingRegistry is not None
    assert hasattr(EmbeddingRegistry, 'instance')

def test_supported_embeddings_still_works():
    """Existing exports are preserved."""
    from parrot.embeddings import supported_embeddings
    assert 'huggingface' in supported_embeddings
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-374 must be completed
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-375-embedding-registry-exports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-20
**Notes**: Added `from .registry import EmbeddingRegistry` and `__all__` to `parrot/embeddings/__init__.py`. Import is after `supported_embeddings` dict (which the registry itself imports), avoiding circular imports.

**Deviations from spec**: none
