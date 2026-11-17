# TASK-5372: Toolkit: locked flag via update_node and body-edit locking

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5371
**Assigned-to**: unassigned

---

## Context

Spec §2 "Locked nodes" and the Decision `body-edit-locks-a-segment-backed-node` (resolves FEAT-840 §8). Neither edit
calls the optimizer (AC-6).

## Scope

- `update_node(..., locked: Optional[bool] = None)`: toggles `locked` with `locked_reason: "manual"` (pop the reason
  when unlocking). The existing "neither title nor summary" ValueError must also accept `locked`.
- `update_node_content`: when `node.get("doc_id")`, set `locked=True`, `locked_reason="body_edited"`.
- Test `test_locked_semantics`.

**NOT in scope**: optimizer changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | update_node(locked=), update_node_content locks segment-backed nodes |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` | MODIFY | test_locked_semantics |

---

## Codebase Contract (Anti-Hallucination)

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
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.update_node",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.update_node_content"
  ]
}
```

---

## Implementation Notes

- Read the current `update_node` body (:2224-) before editing: keep its validation message and return shape, add
  `"locked"` to the returned dict when set.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` (MODIFY)
```python
# In update_node_content's apply (anchor `    async def update_node_content(` :2194; occurrences: 1),
# AFTER `            txn.set_body(node, body or "")`:
            if node.get("doc_id"):
                node["locked"] = True
                node["locked_reason"] = "body_edited"

# update_node signature (anchor `    async def update_node(` :2224; occurrences: 1) gains, after `summary: Optional[str] = None,`:
        locked: Optional[bool] = None,
# FILL IN: in the apply closure: if locked is True -> node["locked"]=True, node["locked_reason"]="manual";
#          if locked is False -> pop both keys; widen the ValueError guard; document the arg in Args:
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py` (MODIFY)
```python
def test_locked_semantics(): ...   # FILL IN: spec §4 row (sibling + full-tree optimize; locked ancestor above selection)
```

---

## Acceptance Criteria

- [ ] AC-8 (lock part), AC-6 (no edit calls the optimizer — assert with a patched `plan_deterministic`).


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_toolkit.py -q`

---

## Test Specification

Spec §4 row `test_locked_semantics`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5372 — Toolkit: locked flag via update_node and body-edit locking`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: f9914e62af

Delivered via sdd-coder pool (merged). Scope: toolkit locked semantics.
Validation: merge-tier wave (5372+5373) — 212 passed, exit 0.
Deviations: none noted.

