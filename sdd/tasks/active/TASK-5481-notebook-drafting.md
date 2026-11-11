# TASK-5481: Notebook drafting: library sectors and per-book reading guides

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5480
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 6** (§3), goal G6. Bookstore can *propose* structure — the human (or an agent on
the human's suggestion) refines it. Drafts are ordinary notebook nodes with `metadata.origin="draft"`; any node
with another origin is never overwritten. Without an LLM, communities map 1:1 to sectors.

---

## Scope

- In `notebooks.py`, add `async draft_library_notebook(store, scope="project", *, use_llm=True) -> dict` returning
  `{created, updated, skipped_human}`:
  - candidates from `store.communities()` (label, member_book_ids, centroid) plus `BookCard.topics/genre/traditions`;
  - with `use_llm and store.has_llm`: one `store.adapter.ask_structured(prompt, SectorDraft)` per community;
    on failure fall back to the no-LLM path for that community;
  - without LLM: one sector per community, `code` = sequential `"000"`, `"010"`, … , `title` = community label,
    anchors = member books (no `node_id`);
  - write with `ensure_notebook(None, scope)` → `add_node` / `tag_node(metadata={"note_kind": "sector",
    "origin": "draft", "sector_code": code, "anchors": [...]})`; an existing node with the same `sector_code` and
    `origin="draft"` is updated; one with another origin is skipped (`skipped_human += 1`).
- `async draft_book_notebook(store, book_id) -> dict`: one `note` per top-level ToC entry (depth 0 or the minimum
  depth present), anchored `{book_id, scope, node_id, doc_id, revision}`, empty body, `origin="draft"`; same
  never-overwrite rule.
- Tests in `test_notebooks.py`.

**NOT in scope**: CLI `notebook draft` (TASK-5483).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py` | MODIFY | `draft_library_notebook`, `draft_book_notebook` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_notebooks.py` | MODIFY | Drafting tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from .library import Bookstore, LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX, notebook_tree_name   # TASK-5477
from .models import Anchor, BookCommunity, SectorDraft                               # BookCommunity models.py:~295; SectorDraft TASK-5475
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
def communities(self) -> list[BookCommunity]                       # line 1408
def has_llm(self) -> bool                                          # line 313 (property)
adapter                                                             # exposes `await adapter.ask_structured(prompt, Schema)` (carding.py:227)
def get_toc(self, book_id) -> dict                                 # line 638 (entries: node_id, title, depth, start_page, end_page[, has_notes])
async def ensure_notebook(self, book_id: Optional[str], scope="project") -> BookCard   # TASK-5477
async def _ready_toolkit(self, scope) -> PageIndexToolkit           # line 343
def resolve_book(self, book_id) -> tuple[BookCard, LibraryLocation]   # line 621
# packages/ai-parrot/src/parrot/knowledge/bookstore/models.py
class BookCommunity: community_id, label, label_origin, description, algorithm, size, cohesion,
                     centroid_book_id, member_book_ids: list[str], inter_relations, computed_at   # lines 323-334
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
async def add_node(self, tree_name, title, body="", parent_node_id=None, summary=None, categories=None, metadata=None)   # line 2674
async def tag_node(self, tree_name, node_id, categories=None, metadata=None)   # line 1958 (shallow merge)
async def list_documents(self, tree_name)                           # doc_id → revision of the book tree
```

### Does NOT Exist
- ~~`Bookstore.draft_sectors`~~ — drafting lives in `notebooks.py`, not on `Bookstore`.
- ~~a Dewey code table shipped in the repo~~ — codes are generated (LLM or sequential).
- ~~overwriting `origin != "draft"` nodes~~ — forbidden (AC-2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_notebooks.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.communities",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.ensure_notebook",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#SectorDraft",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCommunity",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.add_node"
  ]
}
```

---

## Implementation Notes

- Prompt (LLM path): give the community label, description and the member books' titles/topics/traditions; ask for
  one `SectorDraft` (Dewey-like 3-digit `code`, short `title`, one-line `rationale`, `books` = members). Keep it
  short; the reply is validated by the schema.
- Find existing sector nodes by walking the notebook tree (`JSONTreeStore` + `structure_to_list`) and indexing
  `metadata.sector_code` — never rely on titles.
- Use `add_node(..., metadata=...)` for new nodes (one call), `tag_node` for updates.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Shared helper `_existing_by_key(store, scope, tree, key_fn)` — *why*: both drafts need the never-overwrite rule.
2. `draft_library_notebook` (no-LLM first, then LLM per community) — *why*: G6 degrades without a model.
3. `draft_book_notebook` — *why*: reading-guide skeleton.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/notebooks.py` (MODIFY — append)
```python
async def draft_library_notebook(store: Bookstore, scope: str = "project", *, use_llm: bool = True) -> dict[str, Any]:
    """Propose Dewey-like sectors with book anchors into ``_library_notes`` of ``scope``.

    Returns:
        ``{"created": n, "updated": n, "skipped_human": n}``.
    """
    counts = {"created": 0, "updated": 0, "skipped_human": 0}
    await store.ensure_notebook(None, scope)
    toolkit = await store._ready_toolkit(scope)
    communities = [c for c in store.communities() if c.member_book_ids]
    # FILL IN: existing = {sector_code: (node_id, origin)} from the notebook tree;
    #   drafts = [await _sector_from_llm(store, c) if use_llm and store.has_llm else None] → fallback _sector_from_community(c, i);
    #   create / update / skip per the never-overwrite rule — bounded by AC-1, AC-2
    return counts


async def draft_book_notebook(store: Bookstore, book_id: str) -> dict[str, Any]:
    """Reading-guide skeleton: one empty ``note`` per top-level ToC entry, anchored, ``origin='draft'``."""
    counts = {"created": 0, "updated": 0, "skipped_human": 0}
    card, loc = store.resolve_book(book_id)
    await store.ensure_notebook(card.book_id, loc.scope)
    # FILL IN: top-level entries of card.toc (min depth); anchors carry doc_id/revision of the book's single document;
    #   key existing nodes by the anchored node_id; never overwrite non-draft nodes — bounded by AC-3
    return counts


def _sector_from_community(community: BookCommunity, index: int) -> SectorDraft:
    """No-LLM fallback: one sector per community."""
    return SectorDraft(
        code=f"{index * 10:03d}",
        title=community.label,
        rationale=community.description,
        books=[Anchor(book_id=book_id) for book_id in community.member_book_ids],
    )


async def _sector_from_llm(store: Bookstore, community: BookCommunity) -> Optional[SectorDraft]:
    """Ask the configured model for one sector; ``None`` on any failure (caller falls back)."""
    # FILL IN: build the prompt per Implementation Notes; await store.adapter.ask_structured(prompt, SectorDraft);
    #   catch Exception → logger.warning + None — bounded by AC-1
    return None
```
**Why**: `SectorDraft.books` anchors carry `scope` — set it to the book's scope when writing (S11). Add the
`BookCommunity`, `SectorDraft` imports to the existing `.models` import line created by TASK-5480.

### FILL IN checklist
- [ ] `draft_library_notebook` create/update/skip loop — bounded by AC-1, AC-2
- [ ] `_sector_from_llm` prompt + failure path — bounded by AC-1
- [ ] `draft_book_notebook` — bounded by AC-3
- [ ] Tests

---

## Acceptance Criteria

- [ ] AC-1: `draft_library_notebook(store, use_llm=False)` on a library with communities creates one sector per community with `origin="draft"`, `note_kind="sector"`, a `sector_code` and book anchors; an LLM failure falls back to the same result.
- [ ] AC-2: re-running after a human edit (node `origin="human"`) leaves the edited node intact and counts it in `skipped_human`.
- [ ] AC-3: `draft_book_notebook` writes one empty, anchored `note` per top-level ToC entry; re-running is idempotent.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_notebooks.py -q`

---

## Test Specification

```python
async def test_draft_library_without_llm_uses_communities(...): ...   # persist a BookCommunity via the catalog first
async def test_draft_never_overwrites_human_nodes(...): ...
async def test_draft_book_notebook_skeleton_idempotent(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug bookstore-notebooks-shared-pageindex --feature-id FEAT-876`).
   Run tests with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
2. **Read the spec** at the path above (§2 Overview, the module section named in Context, §6, §7).
3. **Check dependencies** — every `Depends-on` task must be `done` in
   `sdd/tasks/index/bookstore-notebooks-shared-pageindex.json`.
4. **Verify the Codebase Contract** before writing code; if an entry is stale, fix the contract here first.
   Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `in-progress` (set `started_at`) and commit only that file.
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path.
7. **Validate**: `ruff check --fix <files>` and the Validation Commands below.
8. **Commit the code** — stage only the files listed in this task.
9. **Close** with `parrot sdd task close TASK-5481 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
