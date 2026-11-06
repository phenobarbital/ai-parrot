# TASK-5277: Durable JSON tree save, signature and generation read

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4**. The tree JSON is the publication point of a generation
(spec §2 Overview, step 6), so `JSONTreeStore.save` must be durable (`fsync` before
`os.replace`) and the publisher needs a cheap signature and generation read for the stale check
(step 2).

---

## Scope

- In `JSONTreeStore.save`: `flush` + `os.fsync` the temp file before `os.replace`, then `fsync`
  the directory (best effort); return the new signature `(st_mtime_ns, st_size)`.
- Add `signature(tree_name) -> tuple[int, int] | None` (`None` when the file is missing).
- Add `read_generation(tree_name) -> Optional[int]` returning `tree["generation"]["id"]`, or
  `None` for a missing file, a legacy tree without `generation`, or a malformed value.
- Extend `test_store.py`.

**NOT in scope**: removing `PageIndexToolkit._tree_signature` (TASK-5285), any caller change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` | MODIFY | fsync, signature, read_generation |
| `packages/ai-parrot/tests/knowledge/pageindex/test_store.py` | MODIFY | New tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.store import JSONTreeStore  # verified: store.py:23
```

### Existing Signatures to Use
```python
# knowledge/pageindex/store.py
_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")  # line 20
class JSONTreeStore:                                     # line 23
    self._dir: Path                                      # line 33
    def _path_for(self, tree_name) -> Path               # line 40 (validates the name)
    def load(self, tree_name) -> dict[str, Any]          # line 57
    def save(self, tree_name, tree) -> None              # line 63 — mkstemp :73-77, os.fdopen + json.dump :79-80,
                                                         #   os.replace(tmp_path, path) :81, unlink tmp on failure :82-87
    def delete(self, tree_name) -> bool                  # line 89

# knowledge/pageindex/toolkit.py (reference for the signature shape — do not edit)
    def _tree_signature(self, tree_name) -> tuple[int, int] | None   # lines 182-188: stat → (st_mtime_ns, st_size)
```

### Does NOT Exist
- ~~`JSONTreeStore.signature` / `read_generation`~~ — added by this task
- ~~`fsync` anywhere in `store.py`~~ — added by this task
- ~~a `generation` key in trees written today~~ — legacy trees have none; `read_generation` returns `None`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore.save"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `test_atomic_write_cleans_temp_on_failure` (`test_store.py:56`) must keep passing: the temp
  file is still unlinked when anything before `os.replace` raises.
- Directory `fsync` may fail on some filesystems; wrap it in `try/except OSError` and log at
  debug — *because* durability of the rename is best effort there, while the file itself is synced.
- The return value changes from `None` to the signature; current callers ignore it.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `fsync` lines inside the `with os.fdopen(...)` block — *why*: data must reach disk before the rename publishes it.
2. Add the directory `fsync` after `os.replace` and return `self.signature(tree_name)` — *why*: the publisher records it.
3. Add `signature` and `read_generation` below `delete` — *why*: stale check (spec step 2).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '            os.replace(tmp_path, path)' store.py)
# REPLACE the body of the try at store.py:78-81 with:
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(tree, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            # (existing unlink-and-reraise block stays unchanged)
        # FILL IN: best-effort directory fsync (os.open(self._dir, os.O_RDONLY) → os.fsync → os.close)
        signature = self.signature(tree_name)
        assert signature is not None  # just written
        return signature
```
Change the signature line `def save(self, tree_name: str, tree: dict[str, Any]) -> None:`
(occurrences: 1, store.py:63) to return `tuple[int, int]` and document it.

```python
# occurrences: 1 (verified: grep -cF '    def delete(self, tree_name: str) -> bool:' store.py)
# BEFORE — insert above `    def delete(self, tree_name: str) -> bool:` (verified: store.py:89)
    def signature(self, tree_name: str) -> tuple[int, int] | None:
        """Return ``(st_mtime_ns, st_size)`` of the tree JSON, or ``None`` when it is missing."""
        try:
            st = self._path_for(tree_name).stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def read_generation(self, tree_name: str) -> Optional[int]:
        """Return ``tree["generation"]["id"]``, or ``None`` for a missing, legacy or malformed tree."""
        # FILL IN: load (FileNotFoundError → None), read the nested id, accept only int >= 1
        raise NotImplementedError
```
Add `Optional` to the `typing` import (store.py:16).

### FILL IN checklist
- [ ] directory fsync, best effort; bounded by Key Constraints
- [ ] `read_generation` parsing; bounded by AC-3

---

## Acceptance Criteria

- [ ] AC-1: `save` calls `os.fsync` on the temp file before `os.replace` (verified with mocks and call order).
- [ ] AC-2: `save` returns the same value `signature()` returns right after it; `signature()` is `None` for a missing tree.
- [ ] AC-3: `read_generation` returns the id for `{"generation": {"id": 3}}`, and `None` for a missing file, a legacy tree and `{"generation": "x"}`.
- [ ] Existing `test_store.py` tests pass unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_store.py -q`

---

## Test Specification

```python
# add to packages/ai-parrot/tests/knowledge/pageindex/test_store.py
def test_store_save_fsyncs_before_replace(store, tmp_path):
    # FILL IN: patch os.fsync and os.replace in parrot.knowledge.pageindex.store with a shared
    # Mock manager; assert the fsync call precedes the replace call
    ...

def test_save_returns_signature(store):
    sig = store.save("t", {"structure": []})
    assert sig == store.signature("t")

def test_signature_missing_is_none(store):
    assert store.signature("absent") is None

def test_read_generation(store):
    store.save("g", {"structure": [], "generation": {"id": 3, "published_at": "x", "parent": 2}})
    store.save("legacy", {"structure": []})
    assert store.read_generation("g") == 3
    assert store.read_generation("legacy") is None
    assert store.read_generation("absent") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug pageindex-generation-publication --feature-id FEAT-831`).
   Run tests with `PYTHONPATH=packages/ai-parrot/src` — the shared venv is editable-installed
   against the main checkout.
2. **Read the spec** at the path listed above for full context (§2 Overview is the design).
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/pageindex-generation-publication.json`.
4. **Verify the Codebase Contract** before writing code: re-run the `grep -c` of every MODIFY
   anchor; a count of `0` means drift — stop and report, do not invent an attachment point.
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file.
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
7. **Verify** — run the Validation Commands and `ruff check` on the files you touched.
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `parrot sdd task close TASK-5277 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
