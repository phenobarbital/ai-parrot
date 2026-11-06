# TASK-5281: OKF projection reads bodies through load_node

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5279
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 7**. Publication runs `project_sidecars` on the candidate before
the JSON switch (spec §2 step 5) and aborts on failure. The function already raises; what changes
is where it reads bodies from — the node's `body_ref` blob first — and that it no longer deletes
old `<node_id>.md` files (the sweep owns legacy files, TASK-5279).

---

## Scope

- Replace the two-step body lookup (`content_store.py` keys at `okf/projection.py:134-137`) with
  `content_store.load_node(tree_name, node)`.
- Remove the old-key cleanup (`okf/projection.py:149-153`); keep `ProjectionReport.old_files_removed`
  in the model (it simply stays empty) — *because* removing a field is an API change.
- Update the module docstring (lines 1-21) to say legacy files are swept, not deleted here.
- Update `test_okf_projection.py`: the "old node_id removed" test (`:163`) now asserts the file is kept;
  add a test that a `body_ref` blob is the sidecar body.

**NOT in scope**: calling the projector from publication (TASK-5283), the toolkit's swallowing
wrapper (TASK-5283).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py` | MODIFY | Body lookup via load_node; no legacy deletion |
| `packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py` | MODIFY | Adjusted and new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.okf.projection import project_sidecars, ProjectionReport  # verified: okf/projection.py:97, :33
from parrot.knowledge.pageindex.content_store import NodeContentStore                     # verified: okf/projection.py:27
```

### Existing Signatures to Use
```python
# knowledge/pageindex/okf/projection.py
class ProjectionReport(BaseModel)                                  # line 33 (files_written, nodes_projected, old_files_removed)
def project_sidecar(node: dict, tree_name: str, body: str) -> str  # line 50
def _strip_frontmatter(content: str) -> str                        # line 65
def project_sidecars(tree, tree_name, content_store) -> ProjectionReport  # line 97
    flat_id = flatten_concept_id_for_filename(concept_id)          # line 131
    existing = content_store.load(tree_name, flat_id)              # line 134
    # node_id fallback + old_key                                   # lines 135-138
    content_store.save(tree_name, flat_id, sidecar_content)        # line 145
    if old_key and old_key != flat_id: ... delete_node             # lines 149-153

# knowledge/pageindex/content_store.py (after TASK-5279)
    def load_node(self, tree_name: str, node: dict[str, Any]) -> Optional[str]   # body_ref → <flat>.md → <node_id>.md
```

### Does NOT Exist
- ~~a try/except inside `project_sidecars`~~ — it raises; keep it that way
- ~~`ProjectionReport` removal of `old_files_removed`~~ — the field stays

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py#project_sidecars",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The flat sidecar may hold frontmatter; `_strip_frontmatter` already handles it — keep calling it on the loaded body.
- Output stays byte-deterministic (`test_okf_projection.py:142`).

---

## Implementation Blueprint

### Steps (in order)
1. Replace the lookup — *why*: the blob is the authoritative body after FEAT-831.
2. Delete the cleanup block — *why*: deleting `<node_id>.md` while an older generation may still read it breaks the grace period.
3. Adjust the tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        existing = content_store.load(tree_name, flat_id)' okf/projection.py)
# REPLACE lines 133-138 (the "Load existing body" block) with:
        # Load the body: body_ref blob → flat sidecar → node_id file (FEAT-831).
        existing = content_store.load_node(tree_name, node)
```
```python
# occurrences: 1 (verified: grep -cF '        if old_key and old_key != flat_id:' okf/projection.py)
# DELETE lines 149-153 (the "Clean up old node_id.md" block) and the now-unused `old_key` / `node_id`
# locals; legacy files are removed by NodeContentStore.sweep_unreferenced after the grace period.
```

### FILL IN checklist
- [ ] update the function and module docstrings to the new behaviour

---

## Acceptance Criteria

- [ ] AC-1: a node with `body_ref` gets a sidecar whose body is the blob content.
- [ ] AC-2: an existing `<node_id>.md` is no longer deleted by projection.
- [ ] AC-3: projection output is byte-identical across two runs; failures still raise.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py -q`

---

## Test Specification

```python
# add to / adjust in packages/ai-parrot/tests/knowledge/pageindex/test_okf_projection.py
def test_projection_reads_body_ref(tmp_path):
    store = NodeContentStore(tmp_path)
    store.save_body("t", "intro.0123456789abcdef", "BLOB BODY")
    tree = {"structure": [{"node_id": "0001", "concept_id": "intro", "type": "section",
                           "title": "Intro", "body_ref": "intro.0123456789abcdef"}]}
    project_sidecars(tree, "t", store)
    assert "BLOB BODY" in (tmp_path / "t" / "intro.md").read_text()

# the test at :163 ("old node_id removed") becomes:
def test_projection_keeps_legacy_node_file(tmp_path):
    # FILL IN: legacy 0001.md present → after projection it still exists
    ...
```

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
9. **Close the task** with `parrot sdd task close TASK-5281 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
