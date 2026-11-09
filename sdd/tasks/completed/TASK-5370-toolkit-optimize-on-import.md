# TASK-5370: Toolkit: optimizer settings and optimize-on-import hook

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5367, TASK-5368
**Assigned-to**: unassigned

---

## Context

Spec Module 4, import half (G5 import, G8, AC-6/AC-16, §2 "Import"). Every import that produces a revision optimizes the
new subtree inside its own transaction right after `_stage_document`, when `optimize_on_import` (default True).

## Scope

- Constructor: `optimize_on_import: bool = True`, `optimizer_settings: Optional[OptimizerSettings | dict] = None`
  (after `agentic_timeout_s`); store `self._optimize_on_import`, `self._optimizer_settings`.
- `_revisions_for(tree_name, roots)` and `_optimize_import(txn, revision, roots, *, with_summaries)`.
- Hook the three `_stage_document` sites; switch builder summaries off on the optimized path
  (`import_pdf` options, `md_to_tree(options={"if_add_node_summary": "no"})`); run `describe_document` after
  `_optimize_import` when `with_doc_description` and a live adapter.
- Export `OptimizerSettings`, `OptimizeReport` from `__init__.py`.
- Test `test_optimize_on_import_paths`.

**NOT in scope**: the `optimize` tool (TASK-5371); lock semantics (TASK-5372). With `optimize_on_import=False` every path
must be byte-identical to today (AC-16).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | ctor options, _revisions_for, _optimize_import, import hooks, describe |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` | MODIFY | export OptimizerSettings, OptimizeReport |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` | CREATE | M4 tests (import paths) |

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
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._stage_document",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/generation.py#WriteTransaction"
  ]
}
```

---

## Implementation Notes

- `_optimize_import` order: plan_deterministic on `txn.tree` scoped to the new roots → run_llm_passes (live only) →
  reindex/concept ids for new nodes → stage bodies of mutable touched nodes (`render_body` → `txn.set_body`, empty →
  `txn.drop_body`) → validate_candidate → finalize_stamps → validate again → replace the subtree in `txn.tree`. Any
  validation error raises (aborting the import). Never call `txn.noop` here — the import must still publish.
- `import_pdf` with `optimize_on_import`: `"if_add_node_summary": "no"` and `"if_add_doc_description": "no"`; the
  description comes from `describe_document` afterwards, stored where `build_page_index` puts `doc_description`.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# AFTER `        agentic_timeout_s: float = 120.0,` (toolkit.py:171; occurrences: 1)
        optimize_on_import: bool = True,
        optimizer_settings: Optional["OptimizerSettings | dict"] = None,
# FILL IN: in the body, self._optimize_on_import = optimize_on_import;
#          self._optimizer_settings = OptimizerSettings.model_validate(optimizer_settings or {}) if dict/None else as-is

# NEW methods — insert right above `    def _stage_document(` (:1970; occurrences: 1)
    def _revisions_for(self, tree_name: str, roots: list[dict]) -> Revisions:
        """Load every (doc_id, revision) named under ``roots`` through SegmentStore; missing files are skipped."""
        # FILL IN

    async def _optimize_import(self, txn: WriteTransaction, revision: DocumentRevision, roots: list[dict],
                               *, with_summaries: bool) -> OptimizeReport:
        """Plan and run requested passes on the just-imported subtree (spec §3 M4 docstring)."""
        # FILL IN — order in Implementation Notes; bounded by AC-5, AC-6

# AT each of the 3 sites (occurrences: 3 — disambiguate by enclosing method insert_markdown :1708,
#   insert_ebook :1765, import_pdf :1908):
            if revision is not None:
                self._stage_document(txn, revision, fresh["structure"])
                if self._optimize_on_import:
                    await self._optimize_import(txn, revision, fresh["structure"], with_summaries=<FILL IN per path>)
                imported.update(doc_id=revision.doc_id, revision=revision.revision)

# import_pdf options (:1859): "if_add_node_summary": "yes" if with_summaries and not self._optimize_on_import else "no"
#                     (:1860): same rule for "if_add_doc_description"; then FILL IN describe_document call
# insert_markdown md_to_tree (:1675): add options={"if_add_node_summary": "no"} only when self._optimize_on_import
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/__init__.py` (MODIFY)
```python
# AFTER `    "EvidenceBundle",` (__init__.py:69; occurrences: 1)
    "OptimizerSettings",
    "OptimizeReport",
# FILL IN: add the matching `from .optimizer import OptimizerSettings, OptimizeReport` with the module's other imports
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` (CREATE)
```python
"""Toolkit integration of the PageIndex optimizer (FEAT-846 M4)."""
import pytest

def test_optimize_on_import_paths(): ...   # FILL IN: pdf (fake builder with _segments), markdown, ebook; flag off == today
```

**FILL IN checklist**
- [ ] ctor body  - [ ] `_revisions_for`  - [ ] `_optimize_import`  - [ ] 3 hook sites  - [ ] options  - [ ] export  - [ ] test

---

## Acceptance Criteria

- [ ] AC-6 (import part), AC-16 (flag off byte-identical), AC-5 (every optimized import validates), AC-12 (description framed).


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_segment_import.py -q`

---

## Test Specification

Spec §4 row `test_optimize_on_import_paths`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5370 — Toolkit: optimizer settings and optimize-on-import hook`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: a42e9586d9 (coder, attempt 3) + 669d61bdc4 (orchestrator test fixes)

Delivered via sdd-coder pool: attempts 1-2 (terra) and 3 (sol) all failed the engine's task-tier validation on `test_toolkit.py::test_insert_markdown_then_search`; attempt 3's branch was merged manually.

Root cause (not a coder defect): `optimize_on_import` defaults to True, and the optimizer merges sections under `min_leaf_tokens` (200) into their parent, so the legacy fixture's tiny "Installation" section no longer survived as a node. Spec AC-16 says existing import tests run unchanged under `optimize_on_import=False`.

Deviation (files outside the task list, orchestrator-edited):
- `tests/knowledge/pageindex/test_toolkit.py`: `toolkit` fixture now passes `optimize_on_import=False`.
- `tests/knowledge/bookstore/test_library.py::test_reindex_roundtrip_markdown`: replacement chapter enlarged above the optimizer's minimum leaf size (Bookstore optimizes new books by design, spec G12).

Validation: test_optimizer_toolkit, test_toolkit, test_segment_import, test_toolkit_no_llm, test_layout_import, bookstore/ — 291 passed; the 1 failure + 4 errors in bookstore/test_integration_graph.py (sqlite 'unable to open database file') are pre-existing, reproduced on the pre-task baseline.

