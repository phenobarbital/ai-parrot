# TASK-5478: `LibraryPageIndexToolkit` facade and `pageindex-library` template

**Feature**: FEAT-876 — Bookstore notebooks over a shared PageIndex
**Spec**: `sdd/specs/bookstore-notebooks-shared-pageindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5475, TASK-5476, TASK-5477
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 3** (§3), goal G3, decision `library-served-by-bookstore-facade-over-both-scopes`,
design-research S2/S4/S6/S7. One stdio server (`parrot mcp-local pageindex-library`) serves the full
`pageindex_*` surface over the project **and** global library. The facade routes each tree to its scope,
applies the policy table of spec §2, and delegates to `Bookstore._toolkit(scope)`. It reads the catalog but
never writes `library.db`; lazy registration happens on the Bookstore read side (TASK-5477).
§8 Q2 resolved 2026-11-11: protection only through this server — no generic ownership marker.

---

## Scope

- Create `knowledge/bookstore/pageindex.py` with `LibraryPageIndexToolkit(AbstractToolkit)`:
  `name="pageindex-library"`, `tool_prefix="pageindex"`, `llm_dependent_tools = PageIndexToolkit.llm_dependent_tools`.
- `_resolve(tree_name)` and `_authorize(tree_name, op)` implementing the policy table (book: all writes denied;
  notes: rename/delete denied; free: allowed). Classification by **name + catalog** (S2): `_library_notes`, or
  `<X>_notes` where `X` is a catalogued book, is `notes` even without a row.
- One delegating coroutine per `PageIndexToolkit` public tool (28 today, list in Contract) with the **same name,
  parameters and docstring**, plus the new `list_library_trees`. `create_tree` adds `scope: str = "project"`.
- `rename_tree` authorizes `src` and `dst`, both must resolve to the same scope (S4).
- `search` / `retrieve`: `use_llm_walk` defaults to `self._store.has_llm` (S7).
- `search_documents_scoped(tree_names, ...)`: group names by scope, call each scope toolkit, merge.
- Create template `pageindex-library.yaml` (body fixed in spec §3 M3).
- Tests: new `test_pageindex_facade.py`; template tests in `tests/mcp/test_pageindex_template.py`.

**NOT in scope**: `mcp/toolkit_server.py`, `toolkit_seed.py`, `toolkit_install.py`, `hosts.py`, `local_cli.py`,
`pageindex.yaml` — must stay byte-identical (spec AC). `find_books` (TASK-5480).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/pageindex.py` | CREATE | Facade toolkit |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex-library.yaml` | CREATE | Packaged template |
| `packages/ai-parrot/tests/knowledge/bookstore/test_pageindex_facade.py` | CREATE | Policy, routing, schema tests |
| `packages/ai-parrot/tests/mcp/test_pageindex_template.py` | MODIFY | Template discovery + stdio handshake for pageindex-library |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` at task-writing time (2026-11-11). Use these exact names.
> If you need anything not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                                # verified: bookstore/toolkit.py:25
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, PageIndexWriteDenied   # :220; exception from TASK-5476
from parrot.knowledge.pageindex.store import JSONTreeStore                         # verified: pageindex/store.py:23
from parrot.knowledge.bookstore.config import resolve_locations                    # verified: config.py:79
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError, LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX  # :264, :197; constants from TASK-5477
from parrot.knowledge.bookstore.models import BookCard                             # verified: models.py:152
from parrot.mcp.toolkit_seed import available_templates, load_template, seed_toolkit_sections  # verified: tests/mcp/test_pageindex_template.py:21
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/bookstore/library.py
class Bookstore:
    def __init__(self, locations: list[LibraryLocation], adapter=None, lightweight_model=None, ...)   # line 278
    locations: list[LibraryLocation]                                  # each has .scope, .trees_dir, .db_path
    def has_llm(self) -> bool                                         # line 313 (property)
    def _catalog(self, scope) -> CatalogStore                         # line 326
    def _toolkit(self, scope) -> PageIndexToolkit                     # line 331 (_NullAdapter when no adapter, :336)
    async def _ready_toolkit(self, scope) -> PageIndexToolkit         # line 343 — use this before delegating (sweeps reserved trees)
# How bookstore/mcp_server.py builds an adapter from an LLM client — mirror it (verified: mcp_server.py:62 create_bookstore_mcp_server(locations, adapter=None, lightweight_model=None))
# packages/ai-parrot/src/parrot/knowledge/bookstore/config.py
def resolve_locations(cwd=None, include_global=True, require_exists=False) -> list[LibraryLocation]   # line 79
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py — public coroutines (name: first params) — delegate ALL of them:
#   list_trees(); create_tree(tree_name, doc_name); delete_tree(tree_name); rename_tree(src, dst, *, overwrite)
#   get_tree, get_generation, list_documents, outline, read_pages, read_segments, agentic_retrieve, index_segments,
#   optimize(tree_name, node_id, apply=False, ...), vacuum_tree, search(tree_name, query, top_k, use_bm25, use_llm_walk, ...),
#   retrieve(tree_name, query, ...), search_documents_scoped(tree_names, query, ...), tag_node, insert_markdown,
#   insert_ebook, insert_content, import_file, import_pdf, import_folder, delete_node, add_node, update_node_content, update_node
#   llm_dependent_tools (:265) = {insert_content, import_file, import_folder, search_documents_scoped, agentic_retrieve} (prefixed)
#   write_tools (TASK-5476) — the 17 prefixed write names
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py (unchanged): passes kwargs["llm_client"] when the section has llm: (:338-343); drops llm_dependent_tools otherwise (:335)
```

### Does NOT Exist
- ~~a multi-`storage_dir` `PageIndexToolkit`~~ — the facade composes two single-dir toolkits through `Bookstore`.
- ~~`Bookstore.list_trees`~~ — enumerate with `JSONTreeStore(loc.trees_dir).list_names()` per location.
- ~~writes to `library.db` from the facade~~ — forbidden (G2); never call `CatalogStore.upsert`/`remove` here.
- ~~edits to `mcp/toolkit_server.py`, `toolkit_seed.py`, `pageindex.yaml`~~ — byte-identical AC.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/pageindex.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex-library.yaml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_pageindex_facade.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/mcp/test_pageindex_template.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#resolve_locations",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates"
  ]
}
```

---

## Implementation Notes

- **LLM wiring**: `create_toolkit_mcp_server` passes `llm_client=<AbstractClient>`. Build the Bookstore adapter
  exactly the way `bookstore/mcp_server.py` / `cli.py` build one from a client (read those call sites first and
  reuse the same helper — do not invent a new adapter class). `None` → `Bookstore(adapter=None)` (no LLM).
- **Delegation shape (planner decision)**: write explicit `async def` methods for the tools with routing or policy
  logic (`list_trees`, `list_library_trees`, `create_tree`, `rename_tree`, `search`, `retrieve`,
  `search_documents_scoped`) and generate the remaining single-tree delegators in a loop at module import with
  `functools.wraps(getattr(PageIndexToolkit, name))` so the signature/docstring the tool generator reads is
  PageIndex's own. Verify `AbstractToolkit._generate_tools` (`tools/toolkit.py:575`) picks up the wrapped
  coroutines (`inspect.iscoroutinefunction` + signature via `__wrapped__`); if it does not, write them explicitly.
- `_resolve`: catalogued row in any scope decides (project first). Else name rule (S2): `_library_notes` →
  notes (scope = project unless only global has the tree); `<X>_notes` with `X` catalogued → notes in `X`'s scope.
  Else free: project if the tree exists there, else global if it exists there, else project.
- Denial message for a book tree must name `<book_id>_notes`: e.g.
  `"'<id>' is a Bookstore book (read-only evidence). Write notes in '<id>_notes' instead."`
- Reserved names (`--staging-`, `--replaced-`) are hidden from `list_trees`/`list_library_trees` and denied for writes.
- Lazy-import heavy modules inside methods; no `print` — the factory runs under `redirect_stdout(stderr)`.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Read `bookstore/mcp_server.py` and `toolkit_server.py:300-374` — *why*: reuse the adapter construction and match the factory contract.
2. Write the facade (`__init__`, `_resolve`, `_authorize`, explicit routed tools, generated delegators) — *why*: G3 single server.
3. Write the template — *why*: auto-discovered by `available_templates()` with zero changes to the seeder.
4. Tests (policy table, S2/S4/S6/S7, name-set equality, template + stdio handshake).

### `packages/ai-parrot/src/parrot/knowledge/bookstore/pageindex.py` (CREATE)
```python
"""PageIndex tools over the Bookstore library (project + global) with Bookstore's write policy (FEAT-876)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, PageIndexWriteDenied
from parrot.tools.toolkit import AbstractToolkit

from .config import resolve_locations
from .library import LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX, Bookstore
from .models import BookCard

logger = logging.getLogger(__name__)

_STRUCTURAL_DENIED_FOR_NOTES = frozenset({"rename_tree", "delete_tree"})


class LibraryPageIndexToolkit(AbstractToolkit):
    """pageindex_* tools over the project + global libraries, with Bookstore's write policy."""

    name = "pageindex-library"
    tool_prefix = "pageindex"
    llm_dependent_tools: frozenset[str] = PageIndexToolkit.llm_dependent_tools

    def __init__(
        self,
        project_root: Optional[str | Path] = None,
        llm_client: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
        max_result_chars: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # FILL IN: adapter from llm_client exactly as bookstore/mcp_server.py does (None when no client)
        adapter = None
        self._store = Bookstore(resolve_locations(project_root), adapter=adapter, lightweight_model=lightweight_model)
        self._max_result_chars = max_result_chars

    def _resolve(self, tree_name: str) -> tuple[str, Optional[BookCard], str, PageIndexToolkit]:
        """``(scope, card, kind, toolkit)`` with ``kind`` in ``{book, notes, free}`` (spec §2, S2)."""
        # FILL IN: Implementation Notes "_resolve" — bounded by test_facade_routes_global_tree,
        #   test_facade_classifies_unregistered_notebook_by_name
        raise NotImplementedError

    def _authorize(self, tree_name: str, op: str) -> None:
        """Apply the policy table; raise PageIndexWriteDenied with a ``<id>_notes`` hint for books."""
        scope, card, kind, _ = self._resolve(tree_name)
        if kind == "book":
            raise PageIndexWriteDenied(
                f"{tree_name!r} is a Bookstore book (read-only evidence). "
                f"Write notes in {tree_name + NOTEBOOK_SUFFIX!r} instead."
            )
        if kind == "notes" and op in _STRUCTURAL_DENIED_FOR_NOTES:
            raise PageIndexWriteDenied(f"{tree_name!r} is a Bookstore notebook: {op} is not allowed")

    async def list_trees(self) -> list[str]:
        """List all PageIndex tree names available in the library (project and global)."""
        # FILL IN: merged, de-duplicated, sorted names; hide reserved (--staging-/--replaced-) — bounded by S6
        raise NotImplementedError

    async def list_library_trees(self) -> list[dict[str, Any]]:
        """List library trees with their scope and kind (book, notes or free)."""
        # FILL IN: [{tree_name, scope, kind}] per location — bounded by S6
        raise NotImplementedError

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None, scope: str = "project") -> dict[str, Any]:
        """Create an empty tree in the project (default) or global library."""
        # FILL IN: refuse a catalogued/book name via _authorize semantics; delegate to the scope's _ready_toolkit
        raise NotImplementedError

    async def rename_tree(self, src: str, dst: str, *, overwrite: bool = False) -> dict[str, Any]:
        """Rename a tree inside one library scope."""
        self._authorize(src, "rename_tree")
        self._authorize(dst, "rename_tree")
        # FILL IN: both endpoints must resolve to the same scope, else PageIndexWriteDenied; delegate — bounded by S4
        raise NotImplementedError

    # FILL IN: search / retrieve (use_llm_walk default self._store.has_llm), search_documents_scoped (group by scope),
    #   and the generated single-tree delegators (Implementation Notes "Delegation shape") — every write delegator calls
    #   self._authorize(tree_name, <unprefixed op>) first; optimize only when apply=True.
```
**Why**: the policy is Bookstore's (dependency direction bookstore → pageindex); the served names equal the plain
server's so agents and the unchanged factory see the same surface (S6/S7).

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/pageindex-library.yaml` (CREATE)
```yaml
# parrot:summary: PageIndex tools over the Bookstore library (project + global) — books read-only, notebooks writable.
# parrot:requires_llm: false
# parrot:requires_dist: bm25s,pymupdf
# parrot:requires_pip: ai-parrot[bookstore]
  pageindex-library:
    class: parrot.knowledge.bookstore.pageindex.LibraryPageIndexToolkit
    kwargs:
      project_root: {{repo_root}}
      max_result_chars: 24000
    # Add a model to enable the LLM-dependent tools and the LLM tree walk.
    # llm: anthropic:claude-haiku-5-5
    exclude: [pageindex_agentic_retrieve]
    env: {}
```
**Why**: mirrors `pageindex.yaml` (2-space indented section, same header keys) so `available_templates()` and the
seeder accept it without code changes.

### `packages/ai-parrot/tests/knowledge/bookstore/test_pageindex_facade.py` (CREATE)
```python
"""FEAT-876 M3 — LibraryPageIndexToolkit routing and write policy."""
from __future__ import annotations

import pytest

from parrot.knowledge.bookstore.pageindex import LibraryPageIndexToolkit
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, PageIndexWriteDenied

# FILL IN fixtures: two_scope_locations (spec §4 Test Data) — monkeypatch PARROT_LIBRARY_DIR / PARROT_HOME per
#   config.resolve_locations; a catalogued book added through Bookstore.add_book with a markdown file.
# FILL IN tests (spec §4 M3 rows): test_facade_serves_same_names_as_pageindex_toolkit,
#   test_facade_routes_global_tree, test_facade_denies_book_tree_with_hint, test_facade_denies_rename_of_notebook,
#   test_facade_rename_authorizes_both_endpoints, test_facade_classifies_unregistered_notebook_by_name,
#   test_facade_no_llm_filtering_matches_pageindex, test_facade_list_trees_schema_unchanged,
#   test_facade_allows_free_tree, test_mcp_write_then_bookstore_read (integration, same process)
```

### `packages/ai-parrot/tests/mcp/test_pageindex_template.py` (MODIFY)
```python
# APPEND (helpers _spawn/_handshake/_call/_configure_section exist in this file, lines 131-215)
# FILL IN: test_template_pageindex_library_seeds_and_serves — "pageindex-library" in available_templates();
#   seed_toolkit_sections seeds the section with project_root = repo root; stdio handshake lists pageindex_* names
#   and pageindex_list_library_trees; stdout stays pure JSON-RPC.
```

### FILL IN checklist
- [ ] `__init__` adapter construction — bounded by mcp_server.py's existing pattern
- [ ] `_resolve` — bounded by Notes and S2
- [ ] `list_trees` / `list_library_trees` — bounded by S6
- [ ] `create_tree`, `rename_tree` — bounded by S4
- [ ] `search` / `retrieve` / `search_documents_scoped` / generated delegators — bounded by S7 and AC-1
- [ ] Facade tests + template test — bounded by spec §4 M3 rows

---

## Acceptance Criteria

- [ ] AC-1: `{t.name for t in facade.get_tools()}` equals the plain `PageIndexToolkit` set plus `pageindex_list_library_trees` (LLM-dependent tools hidden by the factory without `llm:` exactly as for `pageindex`).
- [ ] AC-2: every write tool on a catalogued book raises `PageIndexWriteDenied` naming `<book_id>_notes`; a notebook refuses `rename_tree`/`delete_tree` and accepts node ops; a free tree is fully writable.
- [ ] AC-3: `rename_tree` refuses a book at either endpoint and a free tree onto a book/notebook name (S4).
- [ ] AC-4: `<book>_notes` without a catalog row is already a notebook (rename/delete denied) (S2).
- [ ] AC-5: `pageindex_list_trees` returns `list[str]`; `list_library_trees` returns `[{tree_name, scope, kind}]` (S6).
- [ ] AC-6: without `llm:`, `search` runs BM25 only and does not fail on `_NullAdapter` (S7).
- [ ] AC-7: `parrot mcp-local pageindex-library` handshake lists the tools; stdout is pure; `toolkit_server.py`, `toolkit_seed.py`, `pageindex.yaml` unchanged (`git diff origin/dev -- <paths>` empty).
- [ ] AC-8: a note written through the facade appears in `Bookstore.read_section(...)["annotations"]` in the same process.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_pageindex_facade.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py -q`

---

## Test Specification

```python
# see the CREATE/MODIFY test blocks in the blueprint
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
9. **Close** with `parrot sdd task close TASK-5478 bookstore-notebooks-shared-pageindex verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
