# TASK-4479: sl_run_sql and sl_save_result_as_dataset hand-off (M10b, security-gated)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4478
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 + §2 item 6 + AC10/AC12: free SQL (disabled by default) on the IDENTICAL governance path, and the hand-off of a governed result into a subject/session-scoped `DatasetManager` from a host factory. A factory returning a shared manager is refused.

---

## Scope

- Add `run_sql(model, sql)` (exposed only when `allow_raw_sql=True`) going through `_run_governed`'s governance stage with raw SQL input.
- Add `save_result_as_dataset(result_id, name, description=None)` (exposed only with `dataset_manager_factory`): claim the handle, re-check member rights + PBAC, call `add_dataframe` on the factory's manager.
- Add `_dataset_manager_for(ctx)` with shared-instance detection (a manager object returned for two different subject digests → `SemanticResultError`).
- Make the two tools conditional in `__init__` (remove from `exclude_tools` when enabled).
- Write `test_e2e_handoff.py`: `test_toolkit_shared_manager_rejected`, `test_e2e_handoff_two_users_two_sessions`, `test_e2e_masked_inference_matrix`, and the raw-SQL leg of the PBAC denial paths.

**NOT in scope**: the HTTP route (TASK-4480).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` | MODIFY | run_sql + save_result_as_dataset + _dataset_manager_for |
| `packages/ai-parrot-semantic/tests/test_e2e_handoff.py` | CREATE | hand-off + raw SQL e2e |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified on `dev` @ 754878f67, 2026-10-19). Use these exact imports, class names and
> method signatures. **DO NOT** invent, guess or assume anything not listed here — verify first.
> `grep` in this repo is aliased to `ugrep` by RTK: use `grep -F` for anchors with `(`, `[`, `{`.

### Verified Imports
```python
import weakref
import pandas as pd
from parrot.tools.dataset_manager import DatasetManager                   # verified: handlers/datasets.py:32 (import site); class at dataset_manager/tool.py:499
from parrot.semantic.results import ResultHandle                          # TASK-4476
from parrot.semantic.errors import SemanticResultError, SemanticAccessError   # TASK-4464
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager:   # line 499
    def add_dataframe(self, name: str, df: pd.DataFrame, description: Optional[str] = None,
                      metadata: Optional[Dict[str, Any]] = None, is_active: bool = True,
                      computed_columns: Optional[List[Any]] = None,
                      usage_guidance: Optional[Dict[str, List[str]]] = None) -> str   # line 1091
# TASK-4477 — SemanticLayerToolkit._run_governed(query, *, execute) ; self._handles: ResultHandleStore ; self._pipeline
```

### As-built governance notes (added 2026-10-19 — use these, not the spec skeleton)
- Raw SQL MUST go through `GovernancePipeline.govern(...)` (it threads RLS/mask trusted nodes into the guard).
- Usage rights apply only to masked columns and members declared `sensitive: true`
  (`enforce_usage_rights(..., sensitive_members=...)`, option A chosen by the user 2026-10-19, commit 7761f4483).
- `ModelPolicy.usage_allowed/mask_for/mask_rule` take physical `<schema>.<table>.<column>` names.
- `SemanticAuditLedger.verify` is async; core DuckDB source is broken here (issue:58d44d14dd8a) — e2e tests patch
  the duckdb source `query()` as `tests/test_e2e_governed.py` does.

### Does NOT Exist
- ~~Registering a DataSource in the target manager~~ — only a copied DataFrame (`add_dataframe`); never a source (cf. issue:90cf04ce8edd).
- ~~Trusting `metadata` on the handle for authorization~~ — claim() re-verifies; metadata is descriptive.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_e2e_handoff.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager"
  ]
}
```

---

## Implementation Notes

- Shared-manager detection: keep a `weakref.WeakKeyDictionary[DatasetManager, str]` manager → subject digest; a second digest for the same object → refuse (AC10).
- Raw SQL: validate it references only tables of the named model before governance; then the same pipeline (PBAC, lineage, RLS, masking, guard, audit `raw_sql=True`).

### Key Constraints
- Async-first; sync CPU-only work (sqlglot, sidemantic compile) runs under `asyncio.to_thread` at the call site.
- Pydantic v2 models; `logging.getLogger(__name__)` / `self.logger`, never `print`.
- Google-style docstrings, strict type hints, 120-column lines; `ruff check` clean (TID251 bans apply).
- Fail closed wherever governance is involved (spec §7 "Patterns to Follow").
- Worktree testing: prefix pytest with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` (add `:packages/ai-parrot-server/src` for server tests); never `uv sync` inside a worktree.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim,
> then complete every `# FILL IN:` marker. Never change a signature, class name or path the
> blueprint fixes (they come from the spec §3 Interface Skeletons).

### Steps (in order)
1. Add `run_sql` — *why*: AC12 identical governance path.
2. Add hand-off + factory check — *why*: AC10.
3. Make exposure conditional — *why*: tools absent unless enabled.
4. Write the e2e tests.

### `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py` (MODIFY)
```python
# occurrences: verify at task start — anchor `    async def _run_governed(self, query: SemanticQuery, *, execute: bool) -> Any:`
#   (created by TASK-4477; expected 1: grep -c -F '    async def _run_governed(' packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py)
# BEFORE — insert above that anchor:
    async def run_sql(self, model: str, sql: str) -> SemanticQueryResult | dict:
        """Run free read-only SQL against one model's tables through the same governance pipeline
        (PBAC, lineage, RLS, masking, positive guard, audit). Only available when enabled by the host."""
        # FILL IN: same stages as _run_governed minus compile — bounded by AC12; audit raw_sql=True
        raise NotImplementedError

    async def save_result_as_dataset(self, result_id: str, name: str, description: str | None = None) -> dict:
        """Save a previous governed result (by its result_id) as a dataset in your own DatasetManager."""
        # FILL IN: ctx = current_pctx() (None -> SemanticAccessError); handle = self._handles.claim(...);
        #   re-check member rights + PBAC for handle.model; dm = await self._dataset_manager_for(ctx);
        #   dm.add_dataframe(name, pd.DataFrame(handle.rows, columns=handle.columns), description=description,
        #                    metadata={"semantic_audit_id": handle.audit_id, "model": handle.model})
        raise NotImplementedError

    async def _dataset_manager_for(self, ctx: PermissionContext) -> "DatasetManager":
        """Call the host factory; the same manager instance for two subjects raises SemanticResultError."""
        # FILL IN: weakref map manager -> subject_digest(ctx) — bounded by AC10
        raise NotImplementedError

# AND in __init__ (after exclude_tools is computed): when allow_raw_sql -> drop "run_sql" from self.exclude_tools;
#   when dataset_manager_factory is not None -> drop "save_result_as_dataset" (same idiom as
#   DatabaseQueryToolkit.__init__, databasequery/toolkit.py:175-176, but removing instead of adding)
```
**Why**: spec §3 M10 — exposure by `exclude_tools`, both tools last (Worktree Strategy).

### FILL IN checklist
- [ ] `run_sql` — bounded by AC12.
- [ ] `save_result_as_dataset` — bounded by AC10.
- [ ] `_dataset_manager_for` — bounded by AC10.
- [ ] Conditional exposure in `__init__`.
- [ ] e2e test bodies.

---

## Acceptance Criteria

- [ ] `test_toolkit_tool_exposure` (full: `sl_run_sql` only with `allow_raw_sql`; `sl_save_result_as_dataset` only with a factory) passes (AC10, AC12).
- [ ] `test_toolkit_shared_manager_rejected`, `test_e2e_handoff_two_users_two_sessions`, `test_e2e_masked_inference_matrix` pass.
- [ ] TASK-4478's suite (`tests/test_e2e_governed.py`) and TASK-4477's `tests/test_toolkit.py` still pass — run them too (declared by those tasks, so not listed as this task's own Validation Commands).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run with `PYTHONPATH=packages/ai-parrot-semantic/src:packages/ai-parrot/src` in a worktree.

- `pytest packages/ai-parrot-semantic/tests/test_e2e_handoff.py -q`

---

## Test Specification

```python
# packages/ai-parrot-semantic/tests/test_e2e_handoff.py
import pytest
from ._models import models_dir, duckdb_warehouse  # noqa: F401


async def test_toolkit_shared_manager_rejected(models_dir, duckdb_warehouse, allow_all_guard, pctx_factory):
    # FILL IN: factory returning ONE DatasetManager for every ctx -> second subject's save -> SemanticResultError
    ...


async def test_e2e_handoff_two_users_two_sessions(...):
    # FILL IN: foreign/expired handles rejected; identical dataset names isolated per manager;
    #          read after a policy digest change denied
    ...


async def test_e2e_masked_inference_matrix(...):
    # FILL IN: via sl_run_sql and structured filters: WHERE/HAVING/JOIN/GROUP/ORDER/window/alias/CTE/derived on a
    #          masked column without usage rights -> usage_denied; with usage_roles -> allowed
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug semantic-layer --feature-id FEAT-704 --spec sdd/specs/semantic-layer.spec.md --index sdd/tasks/index/semantic-layer.json`).
2. **Read the spec** (`sdd/specs/semantic-layer.spec.md`), especially the sections named in Context.
3. **Check dependencies** — every `Depends-on` task is `done` in `sdd/tasks/index/semantic-layer.json`.
4. **Verify the Codebase Contract** before writing code; fix a stale entry in this file first.
5. **Implement** exactly the files above, following the blueprint; touch nothing else.
6. **Validate**: `ruff check --fix <files>`, then the Validation Commands.
7. **Commit** only the listed files: `feat(semantic-layer): TASK-4479 — sl_run_sql and sl_save_result_as_dataset hand-off (M10b, security-gated)`.
8. **Close** with `scripts/sdd/close_task.sh TASK-4479 semantic-layer verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
