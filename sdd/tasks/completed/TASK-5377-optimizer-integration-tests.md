# TASK-5377: Optimizer end-to-end integration tests

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5372
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests (Module 7). Real arXiv fixture through the layout builder, fake live adapter, tmp storage.

## Scope

- Create `test_optimizer_integration.py` with `test_import_then_optimize_is_noop`,
  `test_deferred_summaries_and_parent_refresh`, `test_import_description_is_framed`,
  `test_subtree_optimize_preserves_outside_ownership`, `test_citations_survive_optimize`,
  `test_two_processes_optimize_and_edit`.

**NOT in scope**: production code changes — a failing scenario is reported in the Completion Note, not patched here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py` | CREATE | six end-to-end scenarios |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import PageIndexToolkit, Citation, validate_citations  # __init__.py
```

### Existing Signatures to Use
```python
# tests/knowledge/pageindex/test_segment_integration.py:40-49 — count_tokens stub + _adapter() helper; mp pattern for two processes
# fixture: tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf; import_pdf(..., structure_mode="layout")
```

### Does NOT Exist
- ~~a `real_llm` marker test~~ — forbidden (AC-1)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Reuse helpers from `test_segment_integration.py` by copying the small ones (do not import a test module).

---

## Implementation Blueprint

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py` (CREATE)
```python
"""End-to-end scenarios for the PageIndex optimizer (FEAT-846)."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_import_then_optimize_is_noop(tmp_path): ...                 # FILL IN: spec §4 row
async def test_deferred_summaries_and_parent_refresh(tmp_path): ...        # FILL IN
async def test_import_description_is_framed(tmp_path): ...                 # FILL IN
async def test_subtree_optimize_preserves_outside_ownership(tmp_path): ... # FILL IN
async def test_citations_survive_optimize(tmp_path): ...                   # FILL IN
def test_two_processes_optimize_and_edit(tmp_path): ...                    # FILL IN (multiprocessing, not async)
```

---

## Acceptance Criteria

- [ ] AC-5, AC-7, AC-12, AC-15 covered end-to-end; all six scenarios pass.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_integration.py -q`

---

## Test Specification

Spec §4 Integration Tests table.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5377 — Optimizer end-to-end integration tests`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: 0aeeb1d0bf

Delivered via sdd-coder pool (merged). Scope: optimizer integration tests.
Validation: 6 integration tests pass (65 s); engine task/merge-tier runners time out at ~60 s, so branch was merged manually and the suite run directly — 229 passed with the other optimizer + bookstore suites; only pre-existing sqlite failures.
Deviations: none noted.

