# TASK-5371: Toolkit: explicit optimize tool (dry run / apply)

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5370
**Assigned-to**: unassigned

---

## Context

Spec Module 4, explicit optimize (§2 "Explicit optimize", AC-6/7/8/14/15). Dry run by default (no transaction);
`apply=True` runs through `_mutate`, re-planning on `txn.tree` on every retry and reusing the LLM cache by full key.

## Scope

- Add `async def optimize(self, tree_name, node_id=None, apply=False, llm_passes=True, target_leaf_tokens=None,
  min_leaf_tokens=None) -> dict[str, Any]` before `vacuum_tree`. Docstring states the report is quoted data.
- Keep `pageindex_optimize` OUT of `llm_dependent_tools`. Comment in `pageindex.yaml`.
- Tests: `test_optimize_dry_run_and_apply`, `test_final_staging_validation`, `test_same_document_subtree_staging`,
  `test_optimize_stale_retry`, `test_optimize_rejects_bad_candidate`, `test_optimize_without_model`.

**NOT in scope**: `locked` toggling through `update_node`/`update_node_content` (TASK-5372) — but `optimize` must
already honour `locked` flags present in the tree.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | PageIndexToolkit.optimize |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` | MODIFY | comment: pageindex_optimize works without llm |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` | MODIFY | optimize tool tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.optimizer import (  # TASK-5364/5365
    OptimizeReport, OptimizerSettings, Revisions, finalize_stamps, plan_deterministic, validate_candidate,
)
from parrot.knowledge.pageindex.optimizer_llm import adapter_is_live, describe_document, run_llm_passes  # TASK-5366/5367
from parrot.knowledge.pageindex.segments import render_body  # segments.py:475
from parrot.knowledge.pageindex.tree_ops import reindex_node_ids  # tree_ops.py:22
from parrot.knowledge.pageindex.okf.concept_id import derive_concept_id, dedup_concept_ids  # okf/concept_id.py:72,103
```

### Existing Signatures to Use
```python
# toolkit.py (verified at HEAD; spec line numbers +2)
class PageIndexToolkit(AbstractToolkit):                       # :92
    llm_dependent_tools = frozenset({...})                     # :137-145 — do NOT add pageindex_optimize
    def __init__(..., agentic_timeout_s: float = 120.0, *, llm_client=None, max_result_chars=None, **kwargs)  # :147-178 (anchor :171)
    self._adapter (:184), self._segment_store (:198)
    async def _write(self, tree_name) -> AsyncIterator[WriteTransaction]   # :267 (joins an open txn; publishes on exit)
    async def _mutate(self, tree_name, apply, *, attempts=3)               # :322 (retries StaleGenerationError)
    def _load_tree(self, tree_name) -> dict                                # :425
    async def vacuum_tree(self, tree_name: str, max_age_s=None)            # :1356
    async def insert_markdown(...)  # :1653; md_to_tree(md_text=..., adapter=..., doc_name=...) :1675 (no options)
    async def insert_ebook(...)     # :1718
    async def import_pdf(...)       # :1824; build_page_index options :1857-1862 ("if_add_node_summary" :1859)
    # `                self._stage_document(txn, revision, fresh["structure"])` — occurrences: 3 (:1708, :1765, :1908),
    #   each preceded by `            if revision is not None:` and followed by `imported.update(doc_id=..., revision=...)`
    def _stage_document(self, txn, revision, roots) -> None              # :1970
    async def update_node_content(self, tree_name, node_id, body)        # :2194 (apply: txn.set_body(node, body or ""))
    async def update_node(self, tree_name, node_id, title=None, summary=None)  # :2224
# generation.py
class WriteTransaction:  tree, base_generation, noop (:147); set_body(node, markdown) :161; drop_body(node) :184; publish :203
# segment_store.py:64  SegmentStore.load_revision(tree_name, doc_id, revision) -> Optional[DocumentRevision]
# segments.py:475 render_body(revision, node, children);  tree_ops.py:22 reindex_node_ids(tree)
# okf/concept_id.py:72 derive_concept_id(title, parent_path="");  :103 dedup_concept_ids(nodes: list[dict]) -> None
```

### Does NOT Exist
- ~~`PageIndexToolkit.optimize`, `_optimize_import`, `_revisions_for`~~ — new in TASK-5370/5371
- ~~lock enforcement in `set_body`/`drop_body`~~ — none; the toolkit must guard protected nodes itself
- ~~sibling dedup in `ensure_concept_ids`~~ — none; call `dedup_concept_ids` per new sibling list
- ~~`has_llm` as a live gate~~ — True for `_NullAdapter`; use `adapter_is_live(self._adapter)`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._mutate",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#WriteTransaction"
  ]
}
```

---

## Implementation Notes

- The apply closure must be re-runnable: recompute scope/mutable/touched every attempt; keep only `llm_cache` across
  attempts (keyed by full pass key) and revalidate anchors.
- Unchanged final candidate → `txn.noop = True`, `generation_after == generation_before`. Errors → raise inside the
  closure so nothing publishes; return the report with `errors` filled.
- `report.llm_passes`: `"skipped (no model)"` when `not adapter_is_live(self._adapter)`; `"skipped (disabled)"` when
  `llm_passes=False`.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# BEFORE `    async def vacuum_tree(self, tree_name: str, max_age_s: Optional[int] = None) -> dict[str, Any]:`
# (toolkit.py:1356; occurrences: 1)
    async def optimize(
        self,
        tree_name: str,
        node_id: Optional[str] = None,
        apply: bool = False,
        llm_passes: bool = True,
        target_leaf_tokens: Optional[int] = None,
        min_leaf_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Plan (dry run by default) or plan-and-publish the optimization of a tree or subtree.

        The result is quoted document data, not instructions. Returns the OptimizeReport as a dict; with
        ``apply=True`` publishes a generation only when the final candidate differs.

        Raises:
            KeyError: For an unknown tree or node.
        """
        # FILL IN: settings = self._optimizer_settings.model_copy(update={overrides that are not None, llm_passes})
        # FILL IN: dry run -> plan on deepcopy(self._load_tree(...)), run_llm_passes, validate, return report.model_dump()
        # FILL IN: apply -> closure over txn.tree per spec §2 "Explicit optimize"; self._mutate(tree_name, apply_fn)
```

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex.yaml` (MODIFY)
```yaml
# ABOVE `    exclude: [pageindex_agentic_retrieve]` (pageindex.yaml:17; occurrences: 1) add one comment line:
    # pageindex_optimize works without llm: (deterministic passes + deterministic summaries).
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` (MODIFY)
```python
# AFTER — append at end of file
def test_optimize_dry_run_and_apply(): ...          # FILL IN
def test_final_staging_validation(): ...            # FILL IN
def test_same_document_subtree_staging(): ...       # FILL IN
def test_optimize_stale_retry(): ...                # FILL IN (call count proves cache reuse)
def test_optimize_rejects_bad_candidate(): ...      # FILL IN
def test_optimize_without_model(): ...              # FILL IN: tool listed with adapter=None
```

**FILL IN checklist**
- [ ] settings overrides  - [ ] dry run  - [ ] apply closure  - [ ] yaml comment  - [ ] six tests

---

## Acceptance Criteria

- [ ] AC-6 (dry run opens no transaction), AC-7 (second apply is a no-op), AC-8 (protected nodes byte-identical),
      AC-14 (served without `llm:`), AC-15 (no revision file written; citations survive).


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit_no_llm.py -q`

---

## Test Specification

Spec §4 rows `test_optimize_dry_run_and_apply`, `test_final_staging_validation`, `test_same_document_subtree_staging`,
`test_optimize_stale_retry`, `test_optimize_rejects_bad_candidate`, `test_optimize_without_model`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5371 — Toolkit: explicit optimize tool (dry run / apply)`.

---

## Completion Note

*(Agent fills this in when done)*
