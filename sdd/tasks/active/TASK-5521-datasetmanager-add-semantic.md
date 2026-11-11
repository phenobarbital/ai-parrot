# TASK-5521: DatasetManager.add_semantic and end-to-end tests (M5)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5518, TASK-5520
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Thin registration with a lazy import, plus the end-to-end proof over the DuckDB fixture.

---

## Scope

- `add_semantic(...)` inserted before `add_query`, same shape as `add_query`.
- End-to-end tests (spec §4 Integration Tests): fetch, RLS per subject on one entry, masking, truncation, audit, bridged identity.

**NOT in scope**: documentation (TASK-5522).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | add_semantic |
| `packages/ai-parrot-semantic/tests/test_e2e_dataset_source.py` | CREATE | end-to-end tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
# inside add_semantic only (lazy):
from parrot.semantic.dataset_source import SemanticDataSource  # created by TASK-5520
```

### Existing Signatures to Use
```python
# tool.py
def add_query(self, name, query_slug, description=None, metadata=None, is_active=True, ...) -> str  # line 1483
    # body pattern lines 1517-1534: lazy import, build source, DatasetEntry(source=self._make_source(source), ...)
self._dataplane_guard   # line 668
# Path and Union are already imported in tool.py (line 17-18)
# Tool path: AbstractToolkit.get_tool(name) (toolkit.py:648); ToolkitTool._execute injects
#   _permission_context into _pre_execute (toolkit.py:174-178), which sets _pctx_var (tool.py:2871-2872)
```

### Does NOT Exist
- ~~a module-level `parrot.semantic` import in core~~ — forbidden; import inside the method.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-semantic/tests/test_e2e_dataset_source.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.add_query",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager._make_source"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Exactly one of `toolkit` or (`models_dir` and `dialect`) → else `ValueError`.
- `ImportError` message names `ai-parrot-semantic`.
- When building the toolkit here and `dataplane_guard` is not in `toolkit_kwargs`, pass `self._dataplane_guard`.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:1517-1534` — add_query body.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Insert the method before add_query.
2. Write e2e tests over the DuckDB fixture.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def add_query(' tool.py)
# BEFORE — insert above `    def add_query(` (verified: tool.py:1483 at task time; re-grep, earlier tasks shift lines)
    def add_semantic(
        self,
        name: str,
        *,
        model: str,
        toolkit: Optional[Any] = None,
        models_dir: Optional[Union[str, Path]] = None,
        dialect: Optional[str] = None,
        default_query: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_active: bool = True,
        usage_guidance: Optional[Dict[str, List[str]]] = None,
        **toolkit_kwargs: Any,
    ) -> str:
        """Register a dataset backed by a governed Semantic Layer model (FEAT-880).

        Exactly one of ``toolkit`` or (``models_dir`` and ``dialect``) is required.

        Returns:
            Confirmation message.

        Raises:
            ImportError: when ai-parrot-semantic is not installed.
            ValueError: when both or neither source of the toolkit is given.
        """
        try:
            from parrot.semantic.dataset_source import SemanticDataSource
        except ImportError as exc:
            raise ImportError("add_semantic requires the 'ai-parrot-semantic' package") from exc
        # FILL IN: argument validation (ValueError); build the source with SemanticDataSource(...) or
        #   SemanticDataSource.from_models_dir(..., dataplane_guard=self._dataplane_guard default);
        #   then DatasetEntry(name=, description=description or source.describe(), source=self._make_source(source),
        #   metadata=metadata or {}, is_active=, auto_detect_types=self.auto_detect_types,
        #   usage_guidance=, protected=True); store in self._datasets[name]; log; return message.
```

### FILL IN checklist
- [ ] add_semantic body.
- [ ] e2e tests: `test_e2e_semantic_dataset_fetch`, `_rls_per_subject`, `_masking`, `_truncation`, `_audited`, `_bridged_identity`, plus `test_add_semantic_argument_validation`, `test_add_semantic_missing_distribution` (monkeypatch `sys.modules['parrot.semantic.dataset_source'] = None`).

---

## Acceptance Criteria

- [ ] `add_semantic` works from a toolkit and from models_dir+dialect
- [ ] End-to-end tests in spec §4 pass, including per-subject rows on one manager entry and the bridged tool path
- [ ] No module-level `parrot.semantic` import in packages/ai-parrot/src

---

## Validation Commands

- `pytest packages/ai-parrot-semantic/tests/test_e2e_dataset_source.py -q`
- `pytest packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py -q`
- `pytest packages/ai-parrot-semantic/tests/test_e2e_governed.py -q`

---

## Test Specification

Copy the `_EvaluatorGuard`, `_context` and `_toolkit` helpers from `tests/test_e2e_governed.py:20-75`. For the bridged test call the manager's `fetch_dataset` tool via `dm.get_tool("fetch_dataset")` (FILL IN: confirm the registered tool name) with `_permission_context=ctx`, without `bind_semantic_context`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug datasetmanager-semantic-source --feature-id FEAT-880`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/datasetmanager-semantic-source.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/datasetmanager-semantic-source.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH` set to the absolute `src` dirs of every changed package (worktree rule)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5521 datasetmanager-semantic-source verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
