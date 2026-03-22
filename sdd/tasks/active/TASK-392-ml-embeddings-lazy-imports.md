# TASK-392: ML/Embeddings Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

ML and embedding modules import `sentence-transformers`, `faiss`, and `torch` at module level. These are among the heaviest dependencies in the project (torch alone is ~2GB). They must be lazy-imported so the core framework loads without ML packages.

Implements: Spec Module 7 — ML/Embeddings Lazy Imports.

---

## Scope

- Convert top-level imports to `lazy_import()` in:
  - `parrot/memory/core.py` — sentence-transformers → `lazy_import(..., extra="embeddings")`
  - `parrot/memory/skills/store.py` — faiss → standardize existing try/except to `lazy_import()`
  - `parrot/memory/episodic/embedding.py` — sentence-transformers
  - `parrot/embeddings/base.py` — sentence-transformers, faiss
  - `parrot/embeddings/huggingface.py` — sentence-transformers
  - `parrot/embeddings/registry.py` — sentence-transformers
  - `parrot/bots/flow/storage/mixin.py` — sentence-transformers
- Replace existing ad-hoc patterns (try/except + FAISS_AVAILABLE flags) with `lazy_import()`.
- Use `TYPE_CHECKING` for type annotations.

**NOT in scope**: torch in loaders/voice (TASK-395). Financial tools (TASK-393).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/memory/core.py` | MODIFY | Lazy-import sentence-transformers |
| `parrot/memory/skills/store.py` | MODIFY | Standardize faiss lazy import |
| `parrot/memory/episodic/embedding.py` | MODIFY | Lazy-import sentence-transformers |
| `parrot/embeddings/base.py` | MODIFY | Lazy-import sentence-transformers, faiss |
| `parrot/embeddings/huggingface.py` | MODIFY | Lazy-import sentence-transformers |
| `parrot/embeddings/registry.py` | MODIFY | Lazy-import sentence-transformers |
| `parrot/bots/flow/storage/mixin.py` | MODIFY | Lazy-import sentence-transformers |

---

## Implementation Notes

### Pattern to Follow
```python
from parrot._imports import lazy_import

class EmbeddingStore:
    def encode(self, text: str):
        st = lazy_import("sentence_transformers", package_name="sentence-transformers", extra="embeddings")
        model = st.SentenceTransformer(self.model_name)
        return model.encode(text)
```

### Replacing existing FAISS_AVAILABLE pattern
```python
# BEFORE (parrot/memory/skills/store.py):
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

# AFTER:
from parrot._imports import lazy_import

# In method:
faiss = lazy_import("faiss", package_name="faiss-cpu", extra="embeddings")
```

### Key Constraints
- `sentence_transformers` module name vs `sentence-transformers` pip name — use `package_name` param
- `faiss` module name vs `faiss-cpu` pip name — use `package_name` param
- Some files use FAISS_AVAILABLE flag for conditional logic — replace with try/lazy_import pattern

---

## Acceptance Criteria

- [ ] All listed files importable without sentence-transformers/faiss installed
- [ ] Embedding functionality works when sentence-transformers is installed
- [ ] FAISS functionality works when faiss-cpu is installed
- [ ] Missing dep raises: `pip install ai-parrot[embeddings]`
- [ ] No leftover `FAISS_AVAILABLE` or `try: import faiss` patterns in modified files
- [ ] All existing tests pass with deps installed

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Read each file** before modifying — note existing patterns to replace
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-392-ml-embeddings-lazy-imports.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
