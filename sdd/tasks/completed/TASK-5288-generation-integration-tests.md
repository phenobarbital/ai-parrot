# TASK-5288: Integration tests: concurrent processes, readers during reindex, crash, legacy read-only

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5287
**Assigned-to**: unassigned

---

## Context

Implements the spec §4 **Integration Tests** table. Unit tests prove each piece; these prove the
guarantees end to end: no lost update across processes, no missing tree or empty body for a reader
during a Bookstore reindex, crash safety between the blob writes and the JSON switch, and a legacy
tree that is only read is never written.

---

## Scope

- Create `test_generation_integration.py` with the four tests of spec §4 Integration Tests.
- Two processes (`multiprocessing` spawn) each run `add_node` 20 times on one tree with their own
  `PageIndexToolkit`; the final tree has 40 added nodes and generation `1 + 40`; no
  `StaleGenerationError` escapes (`_mutate` retries).
- A reader loops `Bookstore.read_section` while an "updated" `add_book` runs; it never sees a
  missing tree or an empty body.
- Crash between bodies and JSON: make `JSONTreeStore.save` raise after the blobs are written;
  the tree is unchanged; `vacuum_tree(name, max_age_s=0)` removes the orphans.
- Legacy read-only: write a legacy tree by hand, snapshot every file's `(path, mtime_ns, size)`,
  run `get_tree`, `search` (BM25 only) and `retrieve`; the snapshot is identical.

**NOT in scope**: any production code change. A test that fails reveals a defect in an earlier
task — record it in the Completion Note and open a ledger issue rather than patching other modules here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py` | CREATE | End-to-end guarantees |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import PageIndexToolkit, StaleGenerationError   # __init__ (+ TASK-5282 exports)
from parrot.knowledge.pageindex.store import JSONTreeStore                     # verified: store.py:23
```

### Existing Signatures to Use
```python
# knowledge/pageindex/toolkit.py (after TASK-5283..5286)
    PageIndexToolkit(adapter, storage_dir, ..., generation_grace_s=3600, lock_timeout_s=30.0)
    async def create_tree(self, tree_name, doc_name=None) -> dict
    async def add_node(self, tree_name, title, ...) -> dict          # line ~1110 — read its exact parameters before use
    async def get_tree / search / retrieve / get_generation / vacuum_tree
# PageIndexToolkit dereferences adapter.model and adapter.client at construction (toolkit.py:108-117):
# use a stand-in like bookstore/library.py:_NullAdapter (line 149) — BM25-only search needs no LLM.

# knowledge/bookstore/library.py
    def read_section(self, book_id, node_id) -> dict[str, Any]       # line 367
    async def add_book(...)                                          # line 977
```

### Does NOT Exist
- ~~a pytest marker for multi-process tests in this repo~~ — use plain tests with timeouts on joins

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/store.py#JSONTreeStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Child processes need importable top-level functions (spawn) and `asyncio.run` inside.
- Use `search(..., use_llm_walk=False)` so no LLM is called.
- Keep the whole file under ~60 s; join child processes with a timeout and fail clearly on hang.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module with the four tests below — *why*: they are the spec's integration table.
2. Run them; on a failure, find which earlier task's guarantee broke and report it.

### `packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py` (CREATE)
```python
"""End-to-end guarantees of FEAT-831 generation publication."""

import asyncio
import multiprocessing as mp
from types import SimpleNamespace

import pytest

from parrot.knowledge.pageindex import PageIndexToolkit


def _adapter():
    return SimpleNamespace(model="none", client=None)


def _writer(storage_dir: str, tree: str, count: int) -> None:
    async def run() -> None:
        tk = PageIndexToolkit(adapter=_adapter(), storage_dir=storage_dir)
        for i in range(count):
            await tk.add_node(tree_name=tree, title=f"n{i}")   # FILL IN: match add_node's real parameters
    asyncio.run(run())


def test_two_processes_one_tree(tmp_path):
    asyncio.run(PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path).create_tree("t"))
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(str(tmp_path), "t", 20)) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    # FILL IN: reload; 40 added nodes; generation id == 41


@pytest.mark.asyncio
async def test_bookstore_reindex_keeps_book_readable(tmp_path):
    # FILL IN: reader task loops read_section during an "updated" add_book; no error, no empty body
    ...


@pytest.mark.asyncio
async def test_crash_between_bodies_and_json(tmp_path, monkeypatch):
    # FILL IN
    ...


@pytest.mark.asyncio
async def test_legacy_tree_read_only_untouched(tmp_path):
    # FILL IN
    ...
```

### FILL IN checklist
- [ ] the four test bodies; AC-1..AC-4

---

## Acceptance Criteria

- [ ] AC-1: `test_two_processes_one_tree` passes: 40 added nodes, generation 41.
- [ ] AC-2: `test_bookstore_reindex_keeps_book_readable` passes.
- [ ] AC-3: `test_crash_between_bodies_and_json` passes.
- [ ] AC-4: `test_legacy_tree_read_only_untouched` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_generation_integration.py -q`

---

## Test Specification

See the Implementation Blueprint — the deliverable of this task is the test module itself.

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
9. **Close the task** with `parrot sdd task close TASK-5288 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
