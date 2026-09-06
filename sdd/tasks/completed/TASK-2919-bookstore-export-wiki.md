# TASK-2919: Bookstore — `export-wiki` to a wikitoolkit plane + `bookstore` namespace registration

**Feature**: FEAT-533 — Bookstore Conceptual Relations
**Spec**: `sdd/specs/wikitoolkit-bookstore-conceptual-relations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2917
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 5, §3 Module 5, goal G6. One-way projection of
the book graph into a dedicated wikitoolkit plane so `wikitoolkit
query/related/communities` and `graph.html` work over books, plus
registration as namespace `bookstore` so `wikitoolkit query --ns
bookstore` resolves it. CLI-only; `parrot.knowledge.wiki` is imported
lazily inside the command so the MCP path stays lean.

---

## Scope

- Create `bookstore/wiki_export.py`:
  - `default_wiki_dir(location: LibraryLocation) -> Path` =
    `location.root / "wiki"`.
  - `card_to_page(card) -> WikiPageRecord` (`concept_id=f"book:{book_id}"`,
    `category="book"`, `title`, `summary`, body = rendered ficha
    (authors, year, language, genre, traditions, period, topics,
    community label, summary) + ToC digest, `source_id=source_path`,
    `origin="ingest"`, `content_hash=source_sha256`).
  - `relation_to_edge(rel) -> tuple[str, str, str, str]` =
    `("book:src", "book:dst", rel.rel, "inferred" if origin == "llm"
    else "extracted")`.
  - `async export_plane(cards, relations, communities_result,
    inter, assembler, out_dir, *, wiki_name="bookstore") -> dict`:
    `SQLiteWikiStore(out_dir / "wiki.db", wiki_name=…)` →
    `upsert_pages` → `add_edges` → `export_graph(assembler.graph,
    out_dir, communities=…, inter_community=…, title="Bookstore —
    Book Graph")` → stats dict `{pages, edges, html, json}`.
  - `register_namespace(store_dir: Path, *, scope: str, git_root:
    Path | None, name="bookstore", description="Bookstore book graph")
    -> Path`: project scope with a git root → `load_project_config(root)`;
    if `name` already in `config.namespaces` with a different `store`
    → raise `BookstoreError` (tell the user to run `wikitoolkit ns
    remove bookstore`); else set `WikiNamespaceConfig(store=<relative
    to root>, backend="sqlite", description=…)` and
    `save_project_config`; also refuse if `name` exists in the global
    registry (mirror `ns_add`). Global scope or no git root →
    `load_global_registry()` / `save_global_registry` with an absolute
    `store`.
  - All `parrot.knowledge.wiki.*` and `graphindex.export_html` imports
    inside the functions; `ImportError` → `BookstoreError("export-wiki
    requires the wiki package …")`.
- `Bookstore.export_wiki(output_dir=None, *, scope="project",
  register=True) -> dict`: cards = `list_books()`; relations =
  `merged_relations` (all origins incl. `same_community`); rebuild the
  graph + communities **without** persisting (reuse
  `detect_book_communities`, no LLM) to obtain `CommunitiesResult` /
  `InterCommunityGraph` for the HTML — or read them back from the
  `communities` table when present (prefer persisted labels: map
  `community_id → label` from `communities()` into the result's
  `Community.label` via `model_copy`); call `export_plane`; then
  `register_namespace` when `register`; return stats + `registered_in`.
- CLI: `bookstore export-wiki [--out DIR] [--global] [--no-register]`.
- Tests per the Test Specification (temp `PARROT_HOME` for the global
  registry; temp git root with `.parrot/wiki.json` for project).

**NOT in scope**: importing anything back from the wiki; changing
`wikitoolkit`'s `_CATEGORY_TO_NODE_KIND` (open question in spec §8);
ArangoDB planes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/wiki_export.py` | CREATE | pages/edges/graph.html/namespace |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `export_wiki` |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/cli.py` | MODIFY | `export-wiki` |
| `packages/ai-parrot/tests/knowledge/bookstore/test_export_wiki.py` | CREATE | export + registry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# lazy, inside functions only:
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord                 # store.py:711, 299
from parrot.knowledge.wiki.project import (WikiNamespaceConfig, WikiProjectConfig, GlobalWikiRegistry,
    find_project_root, load_project_config, save_project_config,
    global_registry_path, load_global_registry, save_global_registry)                  # project.py:175, 365, 344, 640, 667, 692, 955, 960, 986
from parrot.knowledge.graphindex.export_html import export_graph                       # export_html.py:552
# eager (already used by bookstore):
from parrot.knowledge.bookstore.config import LibraryLocation, resolve_locations       # config.py:31, 78
from parrot.knowledge.bookstore.models import BookCard, BookRelation, BookCommunity
from parrot.knowledge.bookstore.relations import detect_book_communities                # TASK-2917
from parrot.knowledge.bookstore.catalog import merged_relations                         # TASK-2913
```

### Existing Signatures to Use
```python
# wiki/store.py
class WikiPageRecord(BaseModel):   # line 299 — concept_id (min_length=1), node_id=None, title="", category: str="concept" (open string), summary="", body="", source_id, token_count, origin ("ingest"|"authored"|"memory"), asserted_by, updated_at (None→now), content_hash
class SQLiteWikiStore(BaseWikiStore):   # line 711
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False)   # line 759 — mkdir parents unless read_only
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int   # line 1134
    async def add_edges(self, edges: list[tuple]) -> int              # line 1154 — (src, dst, rel) or (src, dst, rel, provenance); INSERT OR REPLACE
    async def dump_pages(self) -> list[dict]; async def dump_edges(self) -> list[dict]   # 1715, 1729 (keys src, dst, rel)

# wiki/project.py
class WikiNamespaceConfig(BaseModel):   # line 175 — extra="forbid"; exactly one of path|store|database|vault; backend="sqlite"; credentials_env; description=""; weight=1.0
class WikiProjectConfig(BaseModel):     # line 365 — .namespaces: dict[str, WikiNamespaceConfig]; wiki_name
class GlobalWikiRegistry(BaseModel):    # line 344 — version, namespaces
def find_project_root(start=None) -> Path | None          # line 640 — nearest .parrot/wiki.json else nearest .git root
def load_project_config(root: Path) -> WikiProjectConfig  # line 667 — default config when no file; WikiConfigError when invalid
def save_project_config(root: Path, config) -> Path       # line 692 — writes <root>/.parrot/wiki.json
def global_registry_path() -> Path                        # line 955 — PARROT_HOME/wikis.json
def load_global_registry(path=None) -> GlobalWikiRegistry # line 960
def save_global_registry(registry, path=None) -> Path     # line 986
# wiki/cli.py:2218 ns_add — the semantics to mirror: refuse when name exists in the *other* registry; relative store path resolved against the registry's directory

# graphindex/export_html.py
def export_graph(graph, output_dir: Path, *, communities=None, analytics=None, inter_community=None, god_top_k=15, title="GraphIndex Knowledge Map", echarts_js=None, allow_cdn_fallback=True) -> tuple[Path, Path]   # line 552

# bookstore/config.py
class LibraryLocation: scope: Scope; root: Path; db_path -> Path   # line 31 — root is the `.../library` dir; git root = root.parent.parent when root == <git>/.parrot/library (do NOT assume; derive via find_project_root(root) or resolve_locations internals)
def resolve_locations(cwd=..., require_exists=...) -> list[LibraryLocation]   # line 78

# bookstore/library.py (after TASK-2917)
def communities(self) -> list[BookCommunity]; _stores(); list_books(); _visible_ids()
# relations.py (TASK-2917): detect_book_communities(cards, relations, *, resolution, seed, algorithm) -> (CommunitiesResult, InterCommunityGraph, GraphAssembler)
```

### Does NOT Exist
- ~~`parrot.knowledge.bookstore.wiki_export`~~, ~~`Bookstore.export_wiki`~~, ~~`bookstore export-wiki`~~ — created here.
- ~~`WikiPageCategory.BOOK`~~ — category is an open string; `"book"` is fine for the store but unknown to `wiki/cli.py:_CATEGORY_TO_NODE_KIND` (→ `WIKI_PAGE`) and default ranking.
- ~~`_REL_TO_EDGE_KIND["parallels"]` etc.~~ — wikitoolkit maps unknown rels to `REFERENCES`; the rel string survives only in the wiki `edges` table.
- ~~A public `register_namespace()` helper in `wiki/project.py`~~ — logic is inline in `wiki/cli.py:ns_add`; mirror it with the load/save functions; never import `wiki/cli.py`.
- ~~`WikiNamespaceConfig(kind=...)`~~ — no `kind` constructor field.
- ~~`LibraryLocation.git_root`~~ — not an attribute; derive the repo root explicitly.

---

## Implementation Notes

### Pattern to Follow
```python
# wiki_export.py — lazy import discipline (same as library.py's parrot_loaders imports)
async def export_plane(...):
    try:
        from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
        from parrot.knowledge.graphindex.export_html import export_graph
    except ImportError as exc:
        raise BookstoreError("export-wiki requires the wiki/graphindex packages (pip install ai-parrot[wiki])") from exc
```

### Key Constraints
- Idempotent: re-running `export-wiki` upserts pages and `INSERT OR REPLACE`s edges; stale edges for removed relations must be deleted — simplest is to delete the plane's `book:*` edges before re-adding (check `BaseWikiStore` for a delete-edges API; if none exists, recreate `wiki.db` from scratch on each export and say so in the docstring).
- Never write to a registry without the user's `register=True` (default on, `--no-register` off) and never overwrite a conflicting entry.
- Project registration stores the path **relative to the git root** (registry-relative resolution rule, `WikiNamespaceConfig` docstring); global stores absolute.
- `graph.html` may fall back to the ECharts CDN (`allow_cdn_fallback=True`) — acceptable; tests only assert file existence.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2218-2320` — `ns_add` semantics
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:956-1040` — `_export_graph_html` (communities → export_graph wiring)
- `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:_docx_to_markdown` — lazy-import + `BookstoreError` pattern

---

## Acceptance Criteria

- [ ] `export-wiki` writes `wiki.db` with one `category="book"` page per card and one edge per relation with provenance `extracted`/`inferred`
- [ ] `graph.html` and `graph.json` exist in the output dir
- [ ] Project scope registers `namespaces.bookstore` (store entry, relative path) in `<git root>/.parrot/wiki.json`; `--global` registers in `PARROT_HOME/wikis.json` (absolute path)
- [ ] Conflicting existing entry → error, registries untouched; `--no-register` leaves both registries untouched
- [ ] Missing wiki package → `ClickException` with an install hint; catalog untouched
- [ ] `SQLiteWikiStore.dump_pages()/dump_edges()` on the exported plane match the catalog counts (integration)
- [ ] `pytest packages/ai-parrot/tests/knowledge/bookstore/test_export_wiki.py -q` green; `ruff check` clean

---

## Test Specification

```python
# tests/knowledge/bookstore/test_export_wiki.py
async def test_export_wiki_pages_and_edges(store_with_relations, tmp_path): ...
async def test_export_wiki_writes_graph_html(store_with_relations, tmp_path): ...
async def test_export_wiki_idempotent_rerun(store_with_relations, tmp_path): ...
def test_export_wiki_registers_namespace_project(tmp_git_root, ...): ...
def test_export_wiki_registers_namespace_global(monkeypatch PARROT_HOME, ...): ...
def test_export_wiki_conflicting_namespace_refused(...): ...
def test_export_wiki_no_register_flag(...): ...
def test_export_wiki_without_wiki_package(monkeypatch sys.modules, ...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2917 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/wikitoolkit-bookstore-conceptual-relations.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2919-bookstore-export-wiki.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-06
**Notes**: New `wiki_export.py`: `default_wiki_dir`, `card_to_page`,
`relation_to_edge`, `export_plane` (deletes `wiki.db` before rebuilding
— no delete-edges API on `BaseWikiStore`, documented in the module
docstring per the task's own fallback instruction), `register_namespace`
(mirrors `ns_add` using only load/save primitives; same-store
re-registration is idempotent, different-store or cross-registry name
collision raises `BookstoreError`). `Bookstore.export_wiki` rebuilds
the clustering graph fresh (never persists it), relabels communities
from already-persisted labels when a partition exists, calls
`export_plane`, then optionally `register_namespace` (git root
resolved via `find_project_root`, falling back to the global registry
when `None`). CLI `export-wiki [--out] [--global] [--no-register]`.
`pytest packages/ai-parrot/tests/knowledge/bookstore/ -q` → 131 passed,
same 3 pre-existing unrelated failures as prior tasks. `ruff check`
clean on every file this task touched (the 1 remaining `F401` on
`cli.py`'s `sys` import is the same pre-existing issue noted in
TASK-2914/2915/2916/2917).

**Deviations from spec**: Fixed
`test_mcp_server.py::test_mcp_server_does_not_import_wiki` (added by
TASK-2918, not in this task's file list) — running the full bookstore
suite revealed it was order-dependent: once `test_export_wiki.py`
(this task, which legitimately imports `parrot.knowledge.wiki`) had
run earlier in the same pytest session, the module stayed cached in
`sys.modules` and the regression check failed regardless of whether
`create_bookstore_mcp_server` itself imported it. Fixed by popping any
`parrot.knowledge.wiki*` entries from `sys.modules` before the check
and restoring them after — verified the fix makes the full-suite run
green in both file orders.
