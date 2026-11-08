# TASK-5368: Node schema fields and key_items in BM25 / embeddings

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 3, schema + indexing half (G9, AC-10, AC-18). Makes `key_items` visible to BM25, embeddings and search
results, and declares the new optional node fields. Delegation-eligible per spec §3.

## Scope

- Add five optional fields to `PageIndexNode` after `structure_source`.
- Add module-level `key_item_text(node)` in `hybrid_search.py`; use it in `_flatten_corpus` and add `key_items` to search
  result dicts when present.
- Add `extra: str = ""` to `NodeEmbeddingStore.content_key` (digest unchanged when empty) and feed labels into
  `build_tree_matrix` text and key.

**NOT in scope**: OKF aliases (TASK-5369); `get_or_embed` (`embedding_store.py:210`) stays unchanged; `outline` already
passes `key_items` through.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` | MODIFY | key_items, locked, locked_reason, aliases, optimizer fields |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | key_item_text helper; labels in BM25 text and in results |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` | MODIFY | content_key(extra=); labels in embedded text |
| `packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py` | MODIFY | test_schema_fields_roundtrip |
| `packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py` | MODIFY | test_bm25_and_embedding_see_key_items (BM25 half) |
| `packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py` | MODIFY | content_key / embedded text with labels |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.schemas import PageIndexNode          # schemas.py:118
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # hybrid_search.py:52
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore   # embedding_store.py:44
```

### Existing Signatures to Use
```python
# schemas.py:118  class PageIndexNode(BaseModel): ... doc_id :129, revision :130, span :131, owned :132,
#                 structure_source: Optional[str] = None  :133;  model_config extra="allow" :136
# hybrid_search.py:165  def _flatten_corpus(self) -> tuple[list[str], list[str]]  (texts.append :179)
# hybrid_search.py:418-427 results.append({"node_id", "title", "summary", "score", "source"})
# embedding_store.py:96-97  @staticmethod def content_key(model_id: str, title: str, summary: str) -> str  — sha1(model_id\x00title\x00summary)
# embedding_store.py:291-298 build_tree_matrix loop: key = self.content_key(self._model_id, title, summary) :296; text = ... :297
```

### Does NOT Exist
- ~~an `extra` parameter on `content_key`~~ — added here; keep the three-positional call digest identical
- ~~`key_item_text` anywhere~~ — new module-level helper in `hybrid_search.py`
- ~~writers of `key_items`~~ — the optimizer (TASK-5366) writes them; here they are only read

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py#PageIndexNode",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py#HybridPageIndexSearch._flatten_corpus",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore.content_key",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py#NodeEmbeddingStore.build_tree_matrix"
  ]
}
```

---

## Implementation Notes

- `content_key` with `extra` non-empty: append `"\x00" + extra` to the hashed payload; with `extra == ""` the bytes
  hashed must be exactly today's, so existing vectors are reused (AC-18).
- Embedding text: `f"{title} {summary} {labels}".strip()`; keep the existing empty-string condition semantics.

---

## Implementation Blueprint

**Steps (in order)**
1. schemas.py: insert the fields. 2. hybrid_search.py: helper + two edits. 3. embedding_store.py: two edits. 4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/schemas.py` (MODIFY)
```python
# AFTER — insert below `    structure_source: Optional[str] = None` (verified: schemas.py:133)
# occurrences: 1 (verified: grep -c '    structure_source: Optional\[str\] = None' schemas.py)
    key_items: Optional[list[dict]] = None
    locked: Optional[bool] = None
    locked_reason: Optional[str] = None
    aliases: Optional[list[str]] = None
    optimizer: Optional[dict] = None
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` (MODIFY)
```python
# NEW module-level helper — place right above `class HybridPageIndexSearch` (hybrid_search.py:52)
def key_item_text(node: dict) -> str:
    """Space-joined ``key_items`` labels of ``node`` or ``""``."""
    return " ".join(str(k.get("label", "")) for k in (node.get("key_items") or []) if k.get("label"))

# REPLACE `            texts.append(f"{title} {summary} {body}".strip())` (verified: hybrid_search.py:179; occurrences: 1)
            texts.append(f"{title} {summary} {key_item_text(node)} {body}".strip())
# FILL IN: confirm the loop variable holding the node dict is named `node` at :165-180; adapt the call if not

# AFTER `                "summary": node.get("summary") or node.get("prefix_summary") or "",` (hybrid_search.py:423; occurrences: 1)
# FILL IN: build the dict as `entry`, then `if node.get("key_items"): entry["key_items"] = node["key_items"]`
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/embedding_store.py` (MODIFY)
```python
# REPLACE signature `    def content_key(model_id: str, title: str, summary: str) -> str:` (embedding_store.py:97; occurrences: 1)
    def content_key(model_id: str, title: str, summary: str, extra: str = "") -> str:
# FILL IN: body — when extra: payload += "\x00" + extra; docstring: unchanged digest when extra is empty

# REPLACE lines :296-297 (anchor `            text = f"{title} {summary}".strip() if (title or summary) else ""`, occurrences: 1)
            labels = key_item_text(node)
            key = self.content_key(self._model_id, title, summary, extra=labels)
            text = f"{title} {summary} {labels}".strip() if (title or summary or labels) else ""
# import: from parrot.knowledge.pageindex.hybrid_search import key_item_text — FILL IN: if this creates an import cycle
#         (check hybrid_search imports embedding_store), define the same 1-line helper locally instead
```

### Tests (MODIFY)
```python
# test_schemas.py:          def test_schema_fields_roundtrip(): ...            # FILL IN
# test_hybrid_search.py:    def test_bm25_and_embedding_see_key_items(): ...   # FILL IN (corpus text + results)
# test_embedding_store.py:  def test_content_key_extra_and_labels(): ...       # FILL IN (unchanged key w/o extra)
```

**FILL IN checklist**
- [ ] loop-variable check  - [ ] results entry  - [ ] content_key body  - [ ] import-cycle check  - [ ] three tests

---

## Acceptance Criteria

- [ ] AC-10: labels in BM25 corpus text, embedded text and key, and in search results.
- [ ] AC-18: `content_key(model_id, title, summary)` digest unchanged; new fields optional; old trees validate.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_schemas.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_hybrid_search.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_embedding_store.py -q`

---

## Test Specification

Spec §4 rows `test_schema_fields_roundtrip`, `test_bm25_and_embedding_see_key_items`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5368 — Node schema fields and key_items in BM25 / embeddings`.

---

## Completion Note

*(Agent fills this in when done)*
