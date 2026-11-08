# TASK-5369: OKF alias resolution and bundle export rewriting

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 3, OKF half (G10, AC-11). A node removed by a merge keeps resolving: its `concept_id` is in the absorber's
`aliases`. `OKFToolkit` resolves aliases; `export_okf_bundle` rewrites links and `relates_to` targets naming an alias.

## Scope

- `OKFToolkit.__init__`: map each alias to the node too; a live `concept_id` always wins over an equal alias.
- `export_okf_bundle`: add aliases to `concept_file_map` (absorber's path) and build `alias_to_concept`; pass it to
  `_export_frontmatter(node, tree_name, alias_to_concept)`, which maps `relates_to` concepts through it.

**NOT in scope**: an `aliases` frontmatter key (never written); `import_okf_bundle`; `parrot.knowledge.okf` shared module.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` | MODIFY | aliases map to the absorbing node |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` | MODIFY | alias -> absorber path and concept on export |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py` | MODIFY | test_okf_alias_resolution |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py` | MODIFY | test_okf_bundle_rewrites_aliases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.tools import OKFToolkit     # okf/tools.py:46 (NOT an AbstractToolkit)
from parrot.knowledge.pageindex.okf.bundle import export_okf_bundle  # okf/bundle.py:252
```

### Existing Signatures to Use
```python
# okf/tools.py:66   def __init__(self, tree, graph, content_store, tree_name, store=None); _by_concept_id built :81-85
# okf/tools.py:174  def get_concept(self, concept_id) -> dict  (KeyError when unknown);  :255 def cite(self, concept_id) -> dict
# okf/bundle.py:146 def _rewrite_pageindex_uris(text, src_rel_path, concept_file_map) -> tuple[str, int]  (only ids in map)
# okf/bundle.py:185 def _export_frontmatter(node: dict, tree_name: str) -> str   (relates_to :205-207)
# okf/bundle.py:286-291 concept_file_map build; :325 frontmatter = _export_frontmatter(node, tree_name)
```

### Does NOT Exist
- ~~alias handling in `OKFToolkit`, `project_frontmatter` or the bundle~~ — added here
- ~~an `aliases` key in exported frontmatter~~ — must stay absent (AC-11)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py#OKFToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py#export_okf_bundle",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py#_export_frontmatter"
  ]
}
```

---

## Implementation Notes

- Two passes in `OKFToolkit.__init__`: first all live `concept_id`s, then aliases with `setdefault` — so a live id wins.
- Same precedence in `export_okf_bundle`: aliases never overwrite a live `concept_file_map` entry.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/tools.py` (MODIFY)
```python
# AFTER — below `                self._by_concept_id[cid] = node` (okf/tools.py:85; occurrences: 1), dedented to the `for` level
        for node in structure_to_list(tree.get("structure", [])):
            for alias in node.get("aliases") or []:
                if alias:
                    self._by_concept_id.setdefault(alias, node)
```
**Why**: second loop guarantees a live `concept_id` wins over an equal alias.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/bundle.py` (MODIFY)
```python
# REPLACE `def _export_frontmatter(node: dict, tree_name: str) -> str:` (bundle.py:185; occurrences: 1)
def _export_frontmatter(node: dict, tree_name: str, alias_to_concept: Optional[dict[str, str]] = None) -> str:
# and inside, the relates_to item (bundle.py:206):
#     {"concept": (alias_to_concept or {}).get(r.get("concept", ""), r.get("concept", "")), "rel": ...}

# AFTER the concept_file_map loop ending `            concept_file_map[cid] = _build_export_path(cid, concept_type_val)` (:291; occurrences: 1)
    alias_to_concept: dict[str, str] = {}
    for node in nodes:
        cid = node.get("concept_id", "")
        for alias in node.get("aliases") or []:
            if cid and alias and alias not in concept_file_map:
                concept_file_map[alias] = concept_file_map[cid]
                alias_to_concept[alias] = cid

# REPLACE `        frontmatter = _export_frontmatter(node, tree_name)` (:325; occurrences: 1)
        frontmatter = _export_frontmatter(node, tree_name, alias_to_concept)
# FILL IN: ensure `Optional` is imported in bundle.py (check its typing imports)
```

### Tests (MODIFY)
```python
# test_okf_tools.py:   def test_okf_alias_resolution(): ...          # FILL IN: get_concept + cite resolve alias
# test_okf_bundle.py:  def test_okf_bundle_rewrites_aliases(): ...   # FILL IN: link + relates_to rewritten; live id wins; no aliases key
```

**FILL IN checklist**
- [ ] relates_to mapping  - [ ] typing import  - [ ] two tests

---

## Acceptance Criteria

- [ ] AC-11: alias resolves via `get_concept`/`cite`; exported links and `relates_to` naming it point at the absorber;
      no `aliases` frontmatter key.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_tools.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_bundle.py -q`

---

## Test Specification

Spec §4 rows `test_okf_alias_resolution`, `test_okf_bundle_rewrites_aliases`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5369 — OKF alias resolution and bundle export rewriting`.

---

## Completion Note

*(Agent fills this in when done)*
