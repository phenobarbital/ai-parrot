# TASK-5279: Immutable body blobs, live-JSON resolution and sweep in NodeContentStore

**Feature**: FEAT-831 — PageIndex Generation Publication
**Spec**: `sdd/specs/pageindex-generation-publication.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3** as amended in spec revision 0.2. Bodies move from
`<tree>/<node_id>.md` to immutable blobs `<tree>/bodies/<flat_concept_id>.<sha16>.md`
referenced by `node["body_ref"]`. Eleven call sites outside the toolkit read bodies by
`node_id` (spec §2 "Readers that key bodies by `node_id`"); they are not edited — `load`,
`has` and `loader_for(tree_name)` resolve the key through the live tree JSON when the legacy
file is absent.

---

## Scope

- Add `bodies_dir`, `body_path`, `save_body` (atomic, idempotent), `load_body` (cached),
  `load_node`, `sweep_unreferenced`.
- Add the live resolution index: map `node_id` → `body_ref` and flat concept id → `body_ref`
  from `<storage_dir>/<tree_name>.json`, cached per tree and rebuilt when the JSON's
  `(st_mtime_ns, st_size)` changes; `node_id` wins over a flat id on collision.
- `load()` / `has()`: legacy file first, then the live index.
- `loader_for(tree_name, tree=None)`: with `tree`, resolve through that (pinned) tree with
  `load_node`; without, use `load`.
- Make `save()` atomic (temp + fsync + `os.replace`); it stays for OKF sidecars.
- `delete_tree()` also removes `bodies/` and `embeddings/`.
- Extend `test_content_store.py`.

**NOT in scope**: writing blobs from the toolkit (TASK-5283+), OKF projection changes
(TASK-5281), editing any of the eleven readers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` | MODIFY | Blobs, resolution, sweep |
| `packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py` | MODIFY | New tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.content_store import NodeContentStore      # verified: content_store.py:38
from parrot.knowledge.okf.utils import flatten_concept_id_for_filename     # verified: knowledge/okf/utils.py:18
from parrot.knowledge.pageindex.utils import structure_to_list             # verified: used at okf/projection.py:30
```

### Existing Signatures to Use
```python
# knowledge/pageindex/content_store.py
_TREE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")          # line 34
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")             # line 35
class NodeContentStore:                                        # line 38
    def __init__(self, storage_dir, cache_size=256) -> None    # line 55 — self._dir, self._cache (OrderedDict[(tree, key)] → str)
    def _validate_tree_name(self, tree_name) -> None           # line 66
    def _tree_dir(self, tree_name) -> Path                     # line 77 → <dir>/<tree_name>
    def _node_path(self, tree_name, node_id) -> Path           # line 81
    def _cache_get / _cache_put / _cache_evict / _cache_evict_tree   # lines 86-107
    def save(self, tree_name, node_id, markdown) -> None       # line 111 (plain write_text :115)
    def load(self, tree_name, node_id) -> Optional[str]        # line 118
    def has(self, tree_name, node_id) -> bool                  # line 135
    def delete_tree(self, tree_name) -> int                    # line 151 (only *.md unlinked, rmdir best effort)
    def list_node_ids(self, tree_name) -> list[str]            # line 198
    def loader_for(self, tree_name) -> Callable[[str], Optional[str]]   # line 212

# The tree JSON of `tree_name` lives at  <self._dir>/<tree_name>.json  (JSONTreeStore._path_for, store.py:40-42 —
# same storage_dir: PageIndexToolkit builds both stores from it, toolkit.py:114-115).
```

### Does NOT Exist
- ~~`body_ref`, `bodies/`, `save_body`, `load_body`, `load_node`, `sweep_unreferenced`~~ — added here
- ~~an import of `parrot.knowledge.pageindex.generation` from this module~~ — forbidden: TASK-5282 makes `generation.py` import this module (cycle). Validate the key format locally.
- ~~a sweep of OKF sidecars~~ — `<flat_concept_id>.md` files are live projections and must never be swept

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py#NodeContentStore"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Body key regex: `^[A-Za-z0-9_-]{1,64}\.[0-9a-f]{16}$` (`_BODY_KEY_RE`).
- Blob cache key: `(tree_name, f"bodies/{key}")` — `/` cannot appear in node ids, so no collision.
- Blobs are immutable: `save_body` returns early when the file already exists.
- `sweep_unreferenced(tree_name, tree, *, max_age_s)` deletes, when `mtime` is older than `max_age_s`:
  (a) files in `bodies/` whose key no node of `tree` references; (b) `<node_id>.md` files whose node in
  `tree` has a `body_ref` and whose stem is not that node's flat concept id. Nothing else.
  Return the count.
- The live index must not raise on a missing or unreadable JSON: return an empty mapping.
- Use `structure_to_list` to walk nodes.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_BODY_KEY_RE` and the blob API below `save` — *why*: everything else builds on it.
2. Add the live index helpers, then route `load`/`has` through them — *why*: keeps the eleven readers working.
3. Change `loader_for`, `save`, `delete_tree`; add `sweep_unreferenced`.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/pageindex/content_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")' content_store.py)
# AFTER — insert below that line (verified: content_store.py:35)
_BODY_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.[0-9a-f]{16}$")
```

```python
# occurrences: 1 (verified: grep -cF '    def load(self, tree_name: str, node_id: str) -> Optional[str]:' content_store.py)
# BEFORE — insert above that line (verified: content_store.py:118)
    # ---- immutable body blobs (FEAT-831) -----------------------------

    def bodies_dir(self, tree_name: str) -> Path:
        """``<storage_dir>/<tree_name>/bodies``."""
        return self._tree_dir(tree_name) / "bodies"

    def body_path(self, tree_name: str, key: str) -> Path:
        """Path of blob ``key``; raises ``ValueError`` for a malformed key."""
        if not _BODY_KEY_RE.match(key or ""):
            raise ValueError(f"invalid body key {key!r}")
        return self.bodies_dir(tree_name) / f"{key}.md"

    def save_body(self, tree_name: str, key: str, markdown: str) -> Path:
        """Write blob ``key`` atomically (temp + fsync + os.replace); no-op when it exists."""
        # FILL IN — bounded by AC-1
        raise NotImplementedError

    def load_body(self, tree_name: str, key: str) -> Optional[str]:
        """Return blob ``key`` (cached) or ``None`` when absent."""
        # FILL IN
        raise NotImplementedError

    def load_node(self, tree_name: str, node: dict[str, Any]) -> Optional[str]:
        """``body_ref`` → ``<flat_concept_id>.md`` → ``<node_id>.md``; first hit wins."""
        # FILL IN: read legacy files directly (self._node_path), not through load(), to avoid live resolution — AC-2
        raise NotImplementedError

    def _live_index(self, tree_name: str) -> dict[str, str]:
        """Map node_id and flat concept id → body_ref from the live tree JSON (cached by signature)."""
        # FILL IN: stat <self._dir>/<tree_name>.json; reuse self._live[tree_name] when (mtime_ns, size)
        # matches; else json.load, walk with structure_to_list, node_id entries override flat ones — AC-3
        raise NotImplementedError

    def sweep_unreferenced(self, tree_name: str, tree: dict[str, Any], *, max_age_s: int) -> int:
        """Delete unreferenced blobs and superseded ``<node_id>.md`` files older than ``max_age_s``."""
        # FILL IN — bounded by Key Constraints (a)/(b) and AC-5
        raise NotImplementedError
```
Initialise `self._live: dict[str, tuple[tuple[int, int], dict[str, str]]] = {}` in `__init__`
(after `self._cache` at content_store.py:63) and add `import json`, `import shutil`,
`import tempfile`, `import time` and `Any` from `typing`.

`load` (content_store.py:118): after `if not path.is_file():` replace `return None` with a
lookup `key = self._live_index(tree_name).get(node_id)` → `return self.load_body(tree_name, key) if key else None`.
`has` (content_store.py:135): same fallback, returning `bool`.

```python
# occurrences: 1 (verified: grep -cF '    def loader_for(self, tree_name: str) -> Callable[[str], Optional[str]]:' content_store.py)
# REPLACE the signature at content_store.py:212 and branch on `tree`
    def loader_for(
        self, tree_name: str, tree: Optional[dict[str, Any]] = None
    ) -> Callable[[str], Optional[str]]:
        # (keep the existing docstring; add: "With ``tree``, ids resolve against that tree (pinned).")
        # FILL IN: when tree is given, build {node_id: node} once with structure_to_list and return a
        # closure calling load_node; otherwise keep the existing closure (which calls load) — AC-4
```

`save` (content_store.py:111): write through a temp file in the same directory, `fsync`,
`os.replace` — same pattern as `save_body`.

`delete_tree` (content_store.py:151): before the final `rmdir`, `shutil.rmtree` the `bodies`
and `embeddings` subdirectories with `ignore_errors=True`, and `self._live.pop(tree_name, None)`.

### FILL IN checklist
- [ ] `save_body` atomic + idempotent; AC-1
- [ ] `load_body` with cache
- [ ] `load_node` fallback order; AC-2
- [ ] `_live_index` cached by signature; AC-3
- [ ] `loader_for` pinned branch; AC-4
- [ ] `sweep_unreferenced`; AC-5

---

## Acceptance Criteria

- [ ] AC-1: `save_body` leaves no temp file on failure, never overwrites an existing blob, and rejects a malformed key.
- [ ] AC-2: `load_node` returns the blob when `body_ref` is set, else `<flat_concept_id>.md`, else `<node_id>.md`.
- [ ] AC-3: with a tree JSON on disk whose node `0001` has `body_ref`, `load(tree, "0001")` and `has(tree, "0001")` find the blob although no `0001.md` exists; rewriting the JSON is picked up (signature change).
- [ ] AC-4: `loader_for(tree, tree_dict)` resolves through `tree_dict` even after the JSON on disk changed.
- [ ] AC-5: `sweep_unreferenced` removes old unreferenced blobs and superseded `<node_id>.md`, keeps fresh ones, live blobs, OKF sidecars and non-node files.
- [ ] AC-6: `delete_tree` removes `bodies/` and `embeddings/`.
- [ ] Existing `test_content_store.py` tests pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py -q`

---

## Test Specification

```python
# add to packages/ai-parrot/tests/knowledge/pageindex/test_content_store.py
import json, os, time

def _write_tree(tmp_path, name, structure):
    (tmp_path / f"{name}.json").write_text(json.dumps({"structure": structure}))

def test_save_body_is_idempotent(tmp_path):
    store = NodeContentStore(tmp_path)
    key = "intro.0123456789abcdef"
    store.save_body("t", key, "a")
    store.save_body("t", key, "b")          # immutable
    assert store.load_body("t", key) == "a"

def test_load_resolves_through_live_json(tmp_path):
    store = NodeContentStore(tmp_path)
    store.save_body("t", "intro.0123456789abcdef", "body")
    _write_tree(tmp_path, "t", [{"node_id": "0001", "concept_id": "intro", "body_ref": "intro.0123456789abcdef"}])
    assert store.load("t", "0001") == "body"
    assert store.has("t", "0001")

def test_load_node_fallback_order(tmp_path):
    # FILL IN: body_ref beats intro.md beats 0001.md
    ...

def test_sweep_respects_grace_and_sidecars(tmp_path):
    # FILL IN: old orphan blob + old superseded 0001.md removed (os.utime back 2h); fresh orphan,
    # live blob, intro.md sidecar and a non-node file kept
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
9. **Close the task** with `parrot sdd task close TASK-5279 pageindex-generation-publication verified`.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
