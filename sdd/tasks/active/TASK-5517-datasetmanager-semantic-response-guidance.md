# TASK-5517: DatasetManager: semantic metadata, completeness and runtime guidance in fetch_dataset (M2b)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5516
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview items 5-6 (rev 0.2 review findings e705c70f5488 and 40769f9cad7e). The tool response must expose semantic truncation and distinguish inline completeness from source completeness, and the runtime rule 'Never re-fetch a loaded dataset' must exempt changed queries on semantic datasets.

---

## Scope

- After materialize in `fetch_dataset`, when `df.attrs.get("semantic")` is present: add `semantic` (model, audit_id, truncated, row_count only), `inline_complete`, set `complete = inline_complete and not truncated`, add a truncation warning, and phrase the preview note as 'materialized result' (no FULL-dataset claim).
- Update `DEFAULT_USAGE_RULES` rule 1 and the `fetch_dataset` docstring (`conditions` arg).

**NOT in scope**: anything about how the frame is produced (TASK-5520) or stored (TASK-5518).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | response metadata + guidance |
| `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` | MODIFY | M2b tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.dataset_manager import DatasetManager
```

### Existing Signatures to Use
```python
# tool.py
DEFAULT_USAGE_RULES: str = (   # line 613; rule 1 text lines 616-619 ends 'Never re-fetch a loaded dataset.'
def get_usage_rules(self) -> str  # line 4216
# fetch_dataset docstring arg `conditions:` line 3478
# result dict starts `"status": "materialized",` line 3797; return_all/complete at 3811-3817;
#   preview note 3818-3822; `if nan_warnings: result["warnings"] = nan_warnings` 3832-3833; return 3834
```

### Does NOT Exist
- ~~`fetch_dataset` response key `semantic` / `inline_complete`~~ — added here.
- ~~compiled SQL in `attrs["semantic"]`~~ — the source never stores SQL; never expose it.

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
      "path": "packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.fetch_dataset",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.get_usage_rules"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Responses for frames without `attrs["semantic"]` must be byte-for-byte unchanged.
- Read the metadata from the materialized `df` before the PBAC column drop (attrs survive `drop`, but read early).
- Copy only the four keys.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:3811-3833` — the inline/preview logic being extended.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `semantic_meta = dict(df.attrs.get("semantic") or {})` right after materialize succeeds — *why*: single source of truth.
2. After the inline/preview block, add the semantic fields and warning — *why*: agents cannot see attrs.
3. Change the preview note wording only when `semantic_meta` is set.
4. Edit rule 1 of DEFAULT_USAGE_RULES and the docstring — *why*: runtime instructions, not only the wiki.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — semantic response fields
```python
# occurrences: 1 (verified: grep -c '        if nan_warnings:' tool.py — confirm it is the one at tool.py:3832 inside fetch_dataset)
# BEFORE — insert above `        if nan_warnings:` (verified: tool.py:3832)
        if semantic_meta:
            semantic = {k: semantic_meta.get(k) for k in ("model", "audit_id", "truncated", "row_count")}
            result["semantic"] = semantic
            result["inline_complete"] = bool(return_all)
            result["complete"] = bool(return_all) and not bool(semantic["truncated"])
            if semantic["truncated"]:
                nan_warnings = list(nan_warnings or [])
                nan_warnings.append(
                    f"- Dataset '{resolved}' is a TRUNCATED semantic result: the policy row limit was reached "
                    f"({semantic['row_count']} rows materialized). Aggregate further in the semantic query."
                )
```

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — capture metadata
```python
# FILL IN: insert `semantic_meta = dict(df.attrs.get("semantic") or {})` immediately after the successful
#   `df = await self.materialize(name, force_refresh=force_refresh, **params)` (tool.py:3678, inside the try) —
#   bounded by: must exist (as {}) on every success path so the block above can test it.
# FILL IN: preview note (tool.py:3818-3822) — when semantic_meta is set, say "materialized result" instead of
#   "The FULL dataset"; keep the ordinary wording otherwise.
```

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — guidance
```python
# FILL IN: DEFAULT_USAGE_RULES rule 1 (tool.py:616-619) — keep 'Never re-fetch a loaded dataset' for ordinary
#   datasets and add: semantic datasets are the result of ONE query; call fetch_dataset again with new
#   `conditions` when metrics, dimensions, grain, filters, ordering, limit, offset or saved query change;
#   aggregate through semantic metrics, not raw SQL or a previous aggregate in pandas.
# FILL IN: fetch_dataset docstring `conditions:` (tool.py:3478) — add the semantic fields
#   (metrics, dimensions, time_dimensions, filters, order_by, limit, offset, saved_query) and the re-fetch rule.
```

### FILL IN checklist
- [ ] `semantic_meta` capture on every success path — bounded by AC-1.
- [ ] preview-note wording — bounded by 'no FULL-dataset claim for semantic frames'.
- [ ] usage rule 1 + docstring text — bounded by spec §2 'Runtime guidance'.
- [ ] tests `test_fetch_dataset_semantic_response_completeness`, `test_semantic_runtime_query_guidance`.

---

## Acceptance Criteria

- [ ] Semantic responses carry `semantic` (4 keys), `inline_complete` and `complete = inline_complete and not truncated`
- [ ] A capped result shows a truncation warning even when all rows are inline; no FULL-dataset claim
- [ ] Ordinary responses unchanged
- [ ] `get_usage_rules()` and the fetch_dataset description require re-fetch for changed semantic queries

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py -q`

---

## Test Specification

Append to the core test file: a `_GovernedSource` variant whose fetch sets `df.attrs["semantic"]` (truncated True/False × 3 rows / 600 rows) and assert the response keys; and one test asserting the re-fetch wording appears in `DatasetManager().get_usage_rules()` and in `DatasetManager.fetch_dataset.__doc__`.

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
9. **Close the task** with `parrot sdd task close TASK-5517 datasetmanager-semantic-source verified`
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
